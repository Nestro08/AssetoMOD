"""El ingeniero de carrera: decide qué decir, cuándo y con qué urgencia."""
import math
import random
import statistics
import time
from collections import deque
from dataclasses import dataclass

from . import memoria_ac as mac
from .analisis import N_ZONAS, Analizador
from .config import Config
from .voz import ALTA, BAJA, CRITICO, NORMAL, Radio

EJES = {"delanteros": (0, 1), "traseros": (2, 3)}
ZONAS_DANIO = ("delantera", "trasera", "izquierda", "derecha", "central")


# ------------------------------------------------------------- formateo
def fmt_tiempo(ms):
    if not ms or ms <= 0:
        return "--:--.---"
    ms = int(ms)
    return f"{ms // 60000}:{(ms // 1000) % 60:02d}.{ms % 1000:03d}"


def fmt_delta(ms):
    if ms is None:
        return "--.--"
    return f"{ms / 1000:+.2f}"


def voz_tiempo(ms):
    """1:42.345 -> '1 42 con 3' (como lo diría un ingeniero)."""
    ms = int(ms)
    m, s, d = ms // 60000, (ms // 1000) % 60, (ms % 1000) // 100
    seg = f"cero {s}" if s < 10 and m else f"{s}"
    return f"{m} {seg} con {d}" if m else f"{s} con {d}"


def voz_diferencia(ms):
    ms = abs(ms)
    if ms < 50:
        return "menos de una décima"
    if ms < 950:
        d = round(ms / 100)
        return "una décima" if d == 1 else f"{d} décimas"
    return f"{ms / 1000:.1f} segundos".replace(".", ",")


def voz_num(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


def voz_vueltas(n):
    if n < 1:
        return "menos de una vuelta"
    n = int(math.floor(n))
    return "una vuelta" if n == 1 else f"{n} vueltas"


_ULTIMA_VARIANTE = {}


def variar(*frases):
    """Elige una de varias formas de decir lo mismo, sin repetir la última (suena menos a máquina)."""
    clave = frases[0]
    opciones = [f for f in frases if f != _ULTIMA_VARIANTE.get(clave)] or list(frases)
    elegida = random.choice(opciones)
    _ULTIMA_VARIANTE[clave] = elegida
    return elegida


def apellido(nombre):
    """'M. Pérez' -> 'Pérez'; 'Nestor Mengual' -> 'Mengual'."""
    partes = (nombre or "").replace("_", " ").split()
    return partes[-1] if partes else "el rival"


def nombre_coche(modelo):
    for pref in ("ks_", "rss_", "tatuusfa1", "urd_"):
        if modelo.startswith(pref):
            modelo = modelo[len(pref):]
    return modelo.replace("_", " ").title()


@dataclass
class Mensaje:
    hora: str
    texto: str
    prioridad: int
    origen: str  # "ingeniero" | "piloto"


class Ingeniero:
    def __init__(self, analizador: Analizador, radio: Radio, config: Config, rivales=None):
        self.a = analizador
        self.rivales = rivales  # Clasificacion (None si no hay datos de otros coches)
        self.curvas = None  # ExtCurvas (análisis curva a curva), si está cargada
        self.estrategia = None  # ExtEstrategia (paradas, presiones), si está cargada
        self.radio = radio
        self.cfg = config
        self.log = deque(maxlen=300)
        self.contador = 0  # mensajes añadidos al registro desde el inicio
        self._ultimo_por_categoria = {}
        self._ultimo_importante = None
        self._t_revision = 0.0
        self._ema_core = None
        self._ema_freno = None
        self._consejos_dichos = {}  # código -> número de vuelta
        self._aviso_desgaste = False
        self._pos_pendiente = None  # (anterior, nueva, t): se anuncia si se mantiene
        self._duelo = {}  # id rival -> "ataca"/"defiende" mientras siga cerca (histéresis)
        self._t_inicio_sesion = time.monotonic()

    # ------------------------------------------------------------ salida
    def decir(self, texto, prioridad=NORMAL, categoria=None, espera=0.0, nivel=1, caduca=15.0):
        """nivel: verbosidad mínima para decirlo (0 = siempre)."""
        if prioridad > CRITICO and self.cfg.verbosidad < nivel:
            return False
        ahora = time.monotonic()
        if categoria:
            if ahora - self._ultimo_por_categoria.get(categoria, -1e9) < espera:
                return False
            self._ultimo_por_categoria[categoria] = ahora
        self._anotar(texto, prioridad, "ingeniero")
        if prioridad <= NORMAL:
            self._ultimo_importante = texto
        self.radio.decir(texto, prioridad, caduca)
        return True

    def _anotar(self, texto, prioridad, origen):
        self.log.append(Mensaje(time.strftime("%H:%M:%S"), texto, prioridad, origen))
        self.contador += 1

    def registrar_piloto(self, texto):
        self._anotar(texto, NORMAL, "piloto")

    def mensaje_remoto(self, texto):
        """Mensaje de un ingeniero humano desde el panel web: se dice tal cual, con prioridad alta."""
        self._anotar(texto, ALTA, "remoto")
        self._ultimo_importante = texto
        self.radio.decir(texto, ALTA, 30)

    # ----------------------------------------------------------- eventos
    def procesar(self, eventos):
        for ev in eventos:
            manejador = getattr(self, "_ev_" + ev.tipo, None)
            if manejador:
                manejador(**ev.datos)

    def _ev_sesion(self, coche, pista, sesion, primera, referencia=None, estadisticas=None, **_):
        s = self.a.snap
        ph = s.physics
        self._consejos_dichos.clear()
        self._aviso_desgaste = False
        self._duelo.clear()
        self._pos_pendiente = None
        self._t_inicio_sesion = time.monotonic()
        self.decir(
            f"Radio comprobada. {nombre_coche(coche)} en {nombre_coche(pista)}, sesión de {sesion.lower()}. "
            f"Tenemos {voz_num(ph.fuel, 0)} litros. Aire a {ph.airTemp:.0f} grados y pista a {ph.roadTemp:.0f}."
            + (f" Tu referencia aquí es {voz_tiempo(referencia['tiempo_ms'])}." if referencia else
               " Es tu primera vez con este coche aquí: la mejor vuelta será tu referencia."
               if estadisticas is not None and not estadisticas.get("vueltas") else ""),
            ALTA, caduca=30)

    def _ev_vuelta(self, vuelta, mejor, diferencia, zona, curvas=None, record_personal=False,
                   record_anterior=None, **_):
        a, v = self.a, vuelta
        partes = []
        if v.boxes:
            partes.append(f"Vuelta {v.numero} con paso por boxes, {voz_tiempo(v.tiempo_ms)}.")
        elif not v.valida:
            partes.append(f"Vuelta {v.numero}, {voz_tiempo(v.tiempo_ms)}, no válida.")
        elif record_personal and record_anterior:
            partes.append(f"¡Récord personal! {voz_tiempo(v.tiempo_ms)}, mejoras tu referencia en "
                          f"{voz_diferencia(v.tiempo_ms - record_anterior)}.")
        elif mejor:
            txt = variar("¡Mejor vuelta!", "¡Vuelta rápida!", "¡Muy bien, mejor vuelta!") + f" {voz_tiempo(v.tiempo_ms)}."
            if diferencia is not None and diferencia < 0:
                txt += f" Mejoras {voz_diferencia(diferencia)}."
            partes.append(txt)
        else:
            txt = f"Vuelta {v.numero}, {voz_tiempo(v.tiempo_ms)}"
            if diferencia is not None:
                txt += f", a {voz_diferencia(diferencia)} de tu mejor"
            partes.append(txt + ".")
            frase = self._frase_curva(curvas) if self.cfg.coaching_curvas else None
            if frase:
                partes.append(frase)
            elif zona and zona["perdida"] > 200 and self.cfg.verbosidad >= 1:
                partes.append(f"Pierdes {voz_diferencia(zona['perdida'])} en el sector {zona['sector'] + 1}.")

        # Combustible: cada 3 vueltas o si el margen es justo
        vcomb = a.vueltas_con_combustible
        if vcomb is not None:
            justo = a.combustible_sobra is not None and a.combustible_sobra < 2 * (a.combustible_por_vuelta or 1)
            if v.numero % 3 == 0 or justo or vcomb < self.cfg.aviso_vueltas_combustible + 2:
                partes.append(f"Combustible para {voz_vueltas(vcomb)}.")

        if self.cfg.verbosidad >= 1:
            frase = self._frase_rivales()
            if frase:
                partes.append(frase)

        g = a.snap.graphics
        if g.session == mac.SESION_CARRERA and g.numberOfLaps > 0:
            quedan = g.numberOfLaps - g.completedLaps
            if 1 < quedan <= 5 or (quedan > 5 and quedan % 5 == 0):
                partes.append(f"Quedan {voz_vueltas(quedan)}.")

        # Un consejo por vuelta como mucho, sin repetir el mismo cada vez
        if v.numero >= 2 and self.cfg.verbosidad >= 1:
            for codigo, eje, valor in a.diagnostico_neumaticos():
                clave = (codigo, eje)
                if v.numero - self._consejos_dichos.get(clave, -99) >= 5:
                    self._consejos_dichos[clave] = v.numero
                    partes.append(self._texto_consejo(codigo, eje, valor))
                    break
        self.decir(" ".join(partes), NORMAL, nivel=0, caduca=25)

    def _ev_sector(self, indice, tiempo, mejor, diferencia, **_):
        if mejor and diferencia is not None:
            self.decir(f"Sector {indice + 1}, récord personal.", BAJA, nivel=2, caduca=6)

    def _ev_bandera(self, bandera, anterior, **_):
        textos = {
            mac.FLAG_YELLOW: (variar("Bandera amarilla. Cuidado, no adelantes.",
                                     "Amarilla, amarilla. Sin adelantar.", "Bandera amarilla, levanta y no adelantes."), CRITICO),
            mac.FLAG_BLUE: (variar("Bandera azul, deja pasar al coche que viene.",
                                   "Azul. Deja pasar sin perder mucho tiempo."), ALTA),
            mac.FLAG_BLACK: ("Bandera negra. Tienes que entrar en boxes.", CRITICO),
            mac.FLAG_WHITE: ("Bandera blanca, coche lento en pista.", ALTA),
            mac.FLAG_PENALTY: ("Te han puesto una penalización.", CRITICO),
        }
        if bandera in textos:
            texto, prio = textos[bandera]
            self.decir(texto, prio, categoria=f"bandera{bandera}", espera=8, nivel=0, caduca=6)
        elif bandera == mac.FLAG_NONE and anterior == mac.FLAG_YELLOW:
            self.decir("Pista despejada, verde.", NORMAL, categoria="verde", espera=8, caduca=6)

    def _ev_posicion(self, anterior, nueva, **_):
        base = self._pos_pendiente[0] if self._pos_pendiente else anterior
        self._pos_pendiente = (base, nueva, time.monotonic())

    def _anunciar_posicion(self):
        if not self._pos_pendiente:
            return
        anterior, nueva, t = self._pos_pendiente
        if time.monotonic() - t < 4.0 or self._en_pelea():
            return  # se anuncia cuando la posición se asienta
        self._pos_pendiente = None
        if nueva == anterior:
            return
        if nueva < anterior:
            txt = variar(f"¡Bien! Subes a P{nueva}.", f"¡Buen adelantamiento! P{nueva}.", f"P{nueva}, ¡bien hecho!") \
                if anterior - nueva == 1 else f"Ganas {anterior - nueva} posiciones, vas P{nueva}."
        else:
            txt = variar(f"Pierdes una posición, P{nueva}.", f"Te han pasado, vas P{nueva}.", f"P{nueva}. Tranquilo, sigue a lo tuyo.") \
                if nueva - anterior == 1 else f"Pierdes {nueva - anterior} posiciones, P{nueva}."
        self.decir(txt, ALTA, categoria="posicion", espera=4, caduca=8)

    def _ev_vuelta_invalida(self, frac, **_):
        self.decir("Vuelta invalidada por límites de pista.", ALTA, categoria="invalida", espera=10, caduca=8)

    def _ev_patinada(self, rueda, frac, **_):
        traseras = sum(self.a._patinadas[2:])
        if traseras >= 3:
            self.decir("Mucho patinaje a la salida de las curvas. Dosifica el acelerador o sube el control de tracción.",
                       NORMAL, categoria="patinada", espera=150)

    def _ev_danio(self, zona, cantidad, total, **_):
        grave = cantidad > 10 or max(total) > 30
        self.decir(f"Daños en la parte {ZONAS_DANIO[zona]}." + (" Son importantes, vigila el comportamiento del coche." if grave else ""),
                   ALTA if grave else NORMAL, categoria="danio", espera=5, nivel=0)

    def _ev_limitador(self, **_):
        self.decir("¡Limitador! Estás en el pit lane.", CRITICO, nivel=0, caduca=5)

    def _ev_boxes_salida(self, **_):
        self.decir(variar("Saliendo de boxes. Neumáticos fríos, cuidado en las primeras curvas.",
                          "Fuera de boxes. Ruedas frías, ve con cuidado la primera vuelta."), NORMAL,
                   categoria="boxes", espera=30)

    def _ev_ultima_vuelta(self, **_):
        self.decir("¡Última vuelta! A por ella.", ALTA, nivel=0)

    def _ev_fin(self, posicion, **_):
        mejor = self.a.mejor
        txt = f"Bandera a cuadros. Terminas P{posicion}."
        if mejor:
            txt += f" Tu mejor vuelta fue {voz_tiempo(mejor.tiempo_ms)}."
        self.decir(txt + " Buen trabajo.", ALTA, nivel=0, caduca=30)

    # ------------------------------------------------------------ rivales
    def _ev_rival_boxes(self, id, nombre, pos, **_):
        c = self.rivales
        yo = c.jugador if c else None
        cerca = yo is not None and abs(pos - yo.pos) <= 2
        if cerca or self.cfg.verbosidad >= 2:
            txt = f"{apellido(nombre)}, P{pos}, entra en boxes."
            if yo is not None and pos == yo.pos - 1:
                txt += " Aprieta ahora, es tu oportunidad."
            self.decir(txt, NORMAL, f"rboxes{id}", 30, caduca=15)

    def _ev_vuelta_rapida_rival(self, nombre, tiempo, **_):
        self.decir(f"Vuelta rápida de {apellido(nombre)}, {voz_tiempo(tiempo)}.", BAJA, "vrapida", 60, nivel=2, caduca=15)

    def _ev_repostaje(self, litros, **_):
        self.decir(f"Repostados {voz_num(litros, 0)} litros.", NORMAL, "repostaje", 20, caduca=20)

    def _ev_cambio_neumaticos(self, **_):
        self.decir("Neumáticos nuevos. Caliéntalos bien antes de apretar.", NORMAL, "neum_nuevos", 30, caduca=30)

    def _texto_gap(self, r, g, delante):
        txt = f"{'Delante' if delante else 'Detrás'}, {apellido(r.nombre)} a {voz_diferencia(abs(g) * 1000)}"
        t = r.tendencia
        if t is not None and abs(t) >= 0.1:
            if delante:
                txt += f", le recortas {voz_diferencia(t * 1000)}" if t < 0 else f", se escapa {voz_diferencia(t * 1000)}"
            else:
                txt += f", te recorta {voz_diferencia(t * 1000)}" if t < 0 else f", le sacas {voz_diferencia(t * 1000)}"
        return txt

    def _frase_rivales(self):
        c = self.rivales
        if not c or not c.activa or not c.carrera or c.jugador is None:
            return None
        delante, detras = c.cercanos()
        partes = []
        if delante is not None and not delante.pitlane:
            g = c.gap_con(delante)
            if g is not None and g < 20:
                partes.append(self._texto_gap(delante, g, True))
        if detras is not None and not detras.pitlane:
            g = c.gap_con(detras)
            if g is not None and -g < 20:
                partes.append(self._texto_gap(detras, g, False))
        return ". ".join(partes) + "." if partes else None

    def _en_pelea(self):
        """True si vas rueda con rueda con alguien (menos de 0,5 s)."""
        c = self.rivales
        if not c or not c.activa or not c.carrera or c.jugador is None:
            return False
        return any(r is not None and abs(c.gap_con(r) or 99) < 0.5 for r in c.cercanos())

    def _revisar_rivales(self):
        c = self.rivales
        if not c or not c.activa or c.jugador is None:
            return
        yo = c.jugador
        if yo.pitlane:
            return
        if c.carrera:
            delante, detras = c.cercanos()
            arrancando = time.monotonic() - self._t_inicio_sesion < 25  # la salida es un caos: sin avisos
            # Un aviso por duelo: al entrar en la zona de 1 s. No se repite hasta que el rival se aleje de
            # 1,6 s o pasen 2 minutos, aunque os adelantéis varias veces. Rueda con rueda (<0,25 s), silencio.
            for r, papel in ((detras, "defiende"), (delante, "ataca")):
                if r is None:
                    continue
                g = abs(c.gap_con(r) or 99)
                if r.pitlane or g > 1.6:
                    self._duelo.pop(r.id, None)
                    continue
                if arrancando or g >= 1.0 or g < 0.25 or r.id in self._duelo:
                    continue
                if papel == "defiende" and r.tendencia is not None and r.tendencia > 0.05:
                    continue  # se está quedando: no hace falta avisar
                nombre, dif = apellido(r.nombre), voz_diferencia(g * 1000)
                texto = (variar(f"{nombre} a {dif} detrás. Defiende.", f"Tienes a {nombre} encima, a {dif}. Cierra el interior.",
                                f"{nombre} a {dif}. Defiende la posición.") if papel == "defiende"
                         else variar(f"Tienes a {nombre} a {dif}. ¡Ataca!", f"{nombre} a {dif} delante. Ve a por él.",
                                     f"Estás a {dif} de {nombre}. ¡Presiona!"))
                if self.decir(texto, ALTA, f"duelo{r.id}", 120, caduca=6):
                    self._duelo[r.id] = papel
            if delante is not None and not delante.pitlane:
                g = c.gap_con(delante) or 99
                if 1.0 <= g < 4 and delante.tendencia is not None and delante.tendencia < -0.15:
                    vueltas = g / -delante.tendencia
                    if vueltas < 6:
                        self.decir(f"Le recortas {voz_diferencia(-delante.tendencia * 1000)} por vuelta a "
                                   f"{apellido(delante.nombre)}. Lo alcanzas en unas {voz_vueltas(vueltas + 0.5)}.",
                                   NORMAL, f"alcanza{delante.id}", 200)
        for r, s, tipo in c.trafico(2.5):
            if tipo == "te_dobla" and s > -2.0:
                self.decir(f"Coche más rápido detrás, {apellido(r.nombre)} te va a doblar. "
                           "Déjale pasar sin salirte de la trazada.", ALTA, f"dobla{r.id}", 60, caduca=5)
            elif tipo == "doblado" and 0 < s < 2.5:
                self.decir(f"Coche doblado delante, {apellido(r.nombre)}. Cuidado al pasarlo.",
                           NORMAL, f"doblado{r.id}", 60, caduca=5)
            elif tipo == "pelea" and not c.carrera and s < 0 and r.kmh > yo.kmh + 5:
                self.decir(f"Coche rápido detrás a {voz_diferencia(-s * 1000)}.", NORMAL, f"trafico{r.id}", 45, caduca=4)

    def _ev_desconectado(self, **_):
        self._anotar("Conexión con Assetto Corsa perdida.", BAJA, "sistema")

    # --------------------------------------------- revisión periódica
    def revisar(self):
        s = self.a.snap
        if s is None or s.graphics.status != mac.STATUS_LIVE:
            return
        ahora = time.monotonic()
        dt = ahora - self._t_revision
        if dt < 1.0:
            return
        self._t_revision = ahora
        ph, gr, a, perf = s.physics, s.graphics, self.a, self.a.perfil

        # Medias móviles (~20 s) para no avisar por un pico momentáneo
        alfa = min(1.0, dt / 20.0)
        core = list(ph.tyreCoreTemperature)
        freno = list(ph.brakeTemp)
        if self._ema_core is None or ph.speedKmh < 30:
            self._ema_core = self._ema_core or core
            self._ema_freno = self._ema_freno or freno
        else:
            self._ema_core = [e + (c - e) * alfa for e, c in zip(self._ema_core, core)]
            self._ema_freno = [e + (c - e) * alfa for e, c in zip(self._ema_freno, freno)]

        # Combustible
        vc = a.vueltas_con_combustible
        necesitamos = a.vueltas_restantes is None or (vc is not None and vc < a.vueltas_restantes + 0.3)
        if vc is not None and necesitamos and not gr.isInPitLane:
            if vc < 1.2:
                self.decir("Combustible crítico. Entra a repostar esta vuelta.", CRITICO, "comb_critico", 60, nivel=0)
            elif vc < self.cfg.aviso_vueltas_combustible:
                self.decir(f"Combustible bajo, te quedan {voz_vueltas(vc)}.", ALTA, "comb_bajo", 120, nivel=0)
        parada_prevista = self.estrategia is not None and self.estrategia.plan is not None             and self.estrategia.plan.nombre != "Sin parar"
        if (a.combustible_sobra is not None and a.combustible_sobra < 0 and gr.session == mac.SESION_CARRERA
                and len(a.vueltas) >= 2 and a.vueltas_restantes and a.vueltas_restantes > 1
                and not parada_prevista):
            ahorro = -a.combustible_sobra / a.vueltas_restantes
            self.decir(f"Con este consumo no llegamos al final: faltan {voz_num(-a.combustible_sobra)} litros. "
                       f"Ahorra {voz_num(ahorro, 2)} por vuelta levantando antes de las frenadas, o para a repostar.",
                       ALTA, "comb_final", 180, nivel=0)

        # Temperatura de neumáticos (solo en marcha y fuera de boxes)
        if ph.speedKmh > 80 and not gr.isInPitLane and (gr.iCurrentTime > 20000 or a.vueltas):
            for eje, ruedas in EJES.items():
                t = statistics.mean(self._ema_core[w] for w in ruedas)
                if t < perf.temp_neum_min - 10 and len(a.vueltas) >= 1:
                    self.decir(f"Los neumáticos {eje} siguen fríos, a {t:.0f} grados. Cuidado en las frenadas.",
                               NORMAL, f"frio{eje}", 120)
                elif t > perf.temp_neum_max + 10:
                    self.decir(f"Los neumáticos {eje} se están sobrecalentando, {t:.0f} grados. Sé más suave con el volante.",
                               ALTA, f"caliente{eje}", 120)
            for eje, ruedas in EJES.items() if a.hay_temp_frenos else ():
                t = max(self._ema_freno[w] for w in ruedas)
                if t > perf.temp_freno_max + 60:
                    self.decir(f"Frenos {eje} muy calientes, {t:.0f} grados. Alivia un poco en las frenadas.",
                               ALTA, f"freno{eje}", 150)

        # Desgaste
        peor = min(ph.tyreWear)
        rueda = list(ph.tyreWear).index(peor)
        if peor < self.cfg.desgaste_critico:
            self.decir(f"Neumáticos muy gastados, la {mac.RUEDAS_LARGO[rueda]} al {peor:.0f} por ciento. Piensa en parar.",
                       ALTA, "desgaste_critico", 300, nivel=0)
        elif peor < self.cfg.desgaste_aviso and not self._aviso_desgaste:
            self._aviso_desgaste = True
            self.decir(f"Los neumáticos empiezan a caer, la {mac.RUEDAS_LARGO[rueda]} está al {peor:.0f} por ciento.",
                       NORMAL, "desgaste")

        self._revisar_rivales()
        self._anunciar_posicion()

        # Bloqueos repetidos en la misma frenada
        for rueda, zona in a.bloqueos_repetidos():
            sector = min(a.n_sectores - 1, int((zona + 0.5) / N_ZONAS * a.n_sectores)) + 1
            self.decir(f"Estás bloqueando la {mac.RUEDAS_LARGO[rueda]} en la misma frenada del sector {sector}. "
                       "Frena un poco antes o suelta presión al final de la frenada.",
                       NORMAL, f"bloqueo{rueda}{zona}", 240)

    # --------------------------------------------------------- consejos
    def _texto_consejo(self, codigo, eje, valor):
        perf = self.a.perfil
        if codigo == "presion_alta":
            return f"Presión alta en los {eje}, {voz_num(valor)} psi. Baja unos {voz_num(max(0.5, valor - (perf.psi_min + perf.psi_max) / 2))} psi en frío."
        if codigo == "presion_baja":
            return f"Presión baja en los {eje}, {voz_num(valor)} psi. Sube unos {voz_num(max(0.5, (perf.psi_min + perf.psi_max) / 2 - valor))} psi en frío."
        if codigo == "centro_caliente":
            return f"El centro de los {eje} está más caliente que los bordes: sobra presión."
        if codigo == "bordes_calientes":
            return f"Los bordes de los {eje} se calientan más que el centro: falta presión."
        if codigo == "mucha_caida":
            return f"El interior de los {eje} va {valor:.0f} grados más caliente que el exterior: sobra caída negativa."
        if codigo == "poca_caida":
            return f"El exterior de los {eje} trabaja demasiado: puedes añadir caída negativa."
        if codigo == "frios":
            return f"Los {eje} no llegan a temperatura, van a {valor:.0f} grados."
        if codigo == "calientes":
            return f"Los {eje} van calientes, a {valor:.0f} grados. Conduce más suave o revisa presiones."
        if codigo == "frenos_calientes":
            return f"Frenos {eje} a {valor:.0f} grados, demasiado calientes. Abre los conductos de freno."
        if codigo == "frenos_frios":
            return f"Frenos {eje} fríos, a {valor:.0f} grados. Puedes cerrar los conductos."
        return ""

    def consejos_actuales(self):
        return [self._texto_consejo(c, e, v) for c, e, v in self.a.diagnostico_neumaticos()]

    # -------------------------------------------------------- preguntas
    def responder(self, intencion, texto_oido=None):
        if texto_oido:
            self.registrar_piloto(texto_oido)
        s = self.a.snap
        if intencion == "silencio":
            self.decir("Entendido, solo te hablaré si es importante.", CRITICO, nivel=0)
            self.radio.silenciada = True
            return
        if intencion == "habla":
            self.radio.silenciada = False
            self.decir("Radio abierta, te voy informando.", ALTA, nivel=0)
            return
        if intencion == "repite":
            self.decir(self._ultimo_importante or "No tengo nada que repetir.", ALTA, nivel=0)
            return
        if intencion == "ayuda":
            self.decir("Pregúntame por combustible, neumáticos, presiones, frenos, tiempos, curvas, rivales, posición, "
                       "daños, estrategia, clima, ajustes, dónde pierdo tiempo o resumen. "
                       "Di silencio para que me calle y habla para que vuelva.", ALTA, nivel=0)
            return
        if s is None:
            self.decir("Aún no recibo datos del coche.", ALTA, nivel=0)
            return
        metodo = getattr(self, "_r_" + intencion, None)
        if metodo:
            self.decir(metodo(s), ALTA, nivel=0, caduca=20)

    def _r_combustible(self, s):
        a, ph = self.a, s.physics
        txt = f"Te quedan {voz_num(ph.fuel)} litros"
        if a.combustible_por_vuelta:
            txt += f", para {voz_vueltas(a.vueltas_con_combustible)}. Gastas {voz_num(a.combustible_por_vuelta, 2)} por vuelta."
        else:
            txt += ". Aún no tengo el consumo medio."
        if a.combustible_sobra is not None and a.vueltas_restantes:
            if a.combustible_sobra >= 0:
                txt += f" Llegas al final con {voz_num(a.combustible_sobra)} litros de margen."
            else:
                txt += f" Te faltan {voz_num(-a.combustible_sobra)} litros para terminar."
        return txt

    def _r_neumaticos(self, s):
        ph, a = s.physics, self.a
        partes = []
        for eje, ruedas in EJES.items():
            t = statistics.mean(ph.tyreCoreTemperature[w] for w in ruedas)
            p = statistics.mean(ph.wheelsPressure[w] for w in ruedas)
            partes.append(f"{eje.capitalize()} a {t:.0f} grados y {voz_num(p)} psi")
        peor = min(ph.tyreWear)
        txt = ". ".join(partes) + f". La rueda más gastada está al {peor:.0f} por ciento."
        if a.vueltas_neumatico is not None:
            txt += f" Aguantan unas {voz_vueltas(a.vueltas_neumatico)} más."
        return txt

    def _r_frenos(self, s):
        ph = s.physics
        if not self.a.hay_temp_frenos:
            txt = "Este coche no simula la temperatura de frenos."
            if ph.brakeBias > 0:
                txt += f" El reparto está al {ph.brakeBias * 100:.0f} por ciento delante."
            return txt
        d = max(ph.brakeTemp[0], ph.brakeTemp[1])
        t = max(ph.brakeTemp[2], ph.brakeTemp[3])
        txt = f"Frenos delanteros a {d:.0f} grados, traseros a {t:.0f}."
        if ph.brakeBias > 0:
            txt += f" Reparto al {ph.brakeBias * 100:.0f} por ciento delante."
        return txt

    def _r_tiempos(self, s):
        a = self.a
        if not a.vueltas:
            return "Aún no hay vueltas completas."
        ultima = a.vueltas[-1]
        txt = f"Última vuelta {voz_tiempo(ultima.tiempo_ms)}."
        if a.mejor:
            txt += f" Mejor {voz_tiempo(a.mejor.tiempo_ms)}."
        if a.delta_ms is not None:
            txt += f" Ahora vas {voz_diferencia(a.delta_ms)} {'por delante' if a.delta_ms < 0 else 'por detrás'} de tu mejor."
        return txt

    def _r_posicion(self, s):
        g, st = s.graphics, s.static
        c = self.rivales
        total = len(c.orden) if c and c.activa else st.numCars
        pos = c.jugador.pos if c and c.activa and c.jugador else g.position
        txt = f"Vas P{pos}" + (f" de {total}" if total > 1 else "") + "."
        if c and c.activa and c.orden and c.jugador and c.orden[0] is not c.jugador and c.jugador.gap_lider:
            txt += f" El líder, {apellido(c.orden[0].nombre)}, a {voz_diferencia(c.jugador.gap_lider * 1000)}."
        if g.numberOfLaps > 0:
            txt += f" Vuelta {g.completedLaps + 1} de {g.numberOfLaps}."
        return txt

    def _r_rivales(self, s):
        c = self.rivales
        if not c or not c.activa:
            return "No recibo datos de los rivales. Activa la app IngenieroPuente en Assetto Corsa."
        if c.jugador is None:
            return "No te encuentro en la clasificación."
        delante, detras = c.cercanos()
        partes = []
        for r, es_delante in ((delante, True), (detras, False)):
            if r is None:
                continue
            g = c.gap_con(r)
            if g is None:
                continue
            txt = self._texto_gap(r, g, es_delante)
            ritmo, mio = r.ritmo(), c.jugador.ritmo()
            if ritmo and mio and abs(ritmo - mio) >= 50:
                dif = ritmo - mio
                txt += f". Su ritmo es {voz_diferencia(dif)} {'más lento' if dif > 0 else 'más rápido'} que el tuyo"
            if r.pitlane:
                txt += ", está en boxes"
            partes.append(txt + ".")
        return " ".join(partes) if partes else "No tienes a nadie cerca."

    def _r_danios(self, s):
        d = list(s.physics.carDamage)
        zonas = [f"{ZONAS_DANIO[i]} {v:.0f}" for i, v in enumerate(d) if v > 0.5]
        return "El coche no tiene daños." if not zonas else "Daños: " + ", ".join(zonas) + "."

    def _r_clima(self, s):
        ph, g = s.physics, s.graphics
        txt = f"Aire a {ph.airTemp:.0f} grados, pista a {ph.roadTemp:.0f}."
        if g.surfaceGrip > 0:
            txt += f" Agarre de la pista al {g.surfaceGrip * 100:.0f} por ciento."
        if g.windSpeed > 1:
            txt += f" Viento de {g.windSpeed:.0f} kilómetros por hora."
        return txt

    def _r_presiones(self, s):
        if self.estrategia is not None:
            return self.estrategia.texto_presiones()
        return self._r_neumaticos(s)

    def _r_estrategia(self, s):
        if self.estrategia is not None:
            txt = self.estrategia.texto_estrategia()
            if txt:
                return txt
        a = self.a
        partes = []
        if a.vueltas_restantes is not None:
            partes.append(f"Quedan unas {voz_vueltas(a.vueltas_restantes + 0.5)}.")
        if a.combustible_sobra is not None:
            if a.combustible_sobra >= 0:
                partes.append("Con el combustible llegamos sin parar.")
            else:
                partes.append(f"Necesitas {voz_num(-a.combustible_sobra)} litros más: repostar o ahorrar.")
        if a.vueltas_neumatico is not None and a.vueltas_restantes is not None:
            if a.vueltas_neumatico < a.vueltas_restantes:
                partes.append(f"Los neumáticos no llegan: aguantan unas {voz_vueltas(a.vueltas_neumatico)}.")
            else:
                partes.append("Los neumáticos aguantan hasta el final.")
        return " ".join(partes) or "Aún no tengo datos suficientes para la estrategia, dame un par de vueltas."

    def _r_ajustes(self, s):
        consejos = self.consejos_actuales()
        if not consejos:
            if self.a.resumen_neumaticos is None:
                return "Necesito una vuelta completa para darte consejos de ajustes."
            return "Los neumáticos trabajan bien, no cambiaría nada."
        return " ".join(consejos[:3])

    @staticmethod
    def _texto_curva(r, n_consejos=2):
        txt = f"Curva {r['curva']}: pierdes {voz_diferencia(r['perdida_ms'])}"
        consejos = r["consejos"][:n_consejos]
        if consejos:
            txt += ", " + " y ".join(consejos)
        return txt + "."

    def _frase_curva(self, curvas):
        """La curva donde más tiempo se ha perdido en la vuelta, con el consejo principal."""
        if not curvas or self.cfg.verbosidad < 1:
            return None
        for r in curvas:
            if 100 < r["perdida_ms"] < 1500 and r["consejos"]:
                return self._texto_curva(r)
        return None

    def _r_curvas(self, s):
        ext = self.curvas
        if ext is None or not ext.curvas:
            return "Aún no tengo una vuelta de referencia para analizar las curvas. Dame una vuelta limpia."
        partes = []
        if ext.ultimo:
            n, res = ext.ultimo
            peores = [r for r in res if r["perdida_ms"] > 80][:3]
            if peores:
                partes.append(f"En la vuelta {n}: " + " ".join(self._texto_curva(r, 1) for r in peores))
            else:
                partes.append(f"En la vuelta {n} no pierdes tiempo apreciable en ninguna curva.")
        debiles = ext.puntos_debiles(1)
        if debiles:
            c, media, veces = debiles[0]
            partes.append(f"Tu punto débil de la sesión es la curva {c}: pierdes una media de {voz_diferencia(media)}.")
        return " ".join(partes) or f"He detectado {len(ext.curvas)} curvas. Completa una vuelta para compararla."

    def _r_donde_pierdo(self, s):
        a = self.a
        if self.curvas is not None and self.curvas.ultimo:
            return self._r_curvas(s)
        partes = []
        if a.vueltas and a.mejor and a.vueltas[-1] is not a.mejor:
            ult, mej = a.vueltas[-1], a.mejor
            dif = [(i, u - m) for i, (u, m) in enumerate(zip(ult.sectores, mej.sectores)) if u and m]
            if dif:
                i, d = max(dif, key=lambda x: x[1])
                if d > 50:
                    partes.append(f"En la última vuelta pierdes {voz_diferencia(d)} en el sector {i + 1}.")
        for rueda, zona in a.bloqueos_repetidos()[:1]:
            partes.append(f"Además bloqueas la {mac.RUEDAS_LARGO[rueda]} hacia el {int((zona + 0.5) * 100 / N_ZONAS)} por ciento de la vuelta.")
        if a.mejores_sectores and all(a.mejores_sectores) and a.mejor:
            teorica = sum(a.mejores_sectores)
            if a.mejor.tiempo_ms - teorica > 100:
                partes.append(f"Tu vuelta ideal juntando los mejores sectores es {voz_tiempo(teorica)}.")
        return " ".join(partes) or "No veo pérdidas claras respecto a tu mejor vuelta."

    def _r_resumen(self, s):
        return " ".join((self._r_posicion(s), self._r_tiempos(s), self._r_combustible(s)))
