"""Estrategia de carrera: paradas, combustible, degradación, undercut y presiones."""
import logging
import math
import statistics
import time
from dataclasses import dataclass, field

from . import memoria_ac as mac
from .analisis import interpolar
from .ingeniero import apellido, voz_diferencia, voz_num, voz_vueltas
from .voz import ALTA, NORMAL

log = logging.getLogger(__name__)

K_COMBUSTIBLE = 0.035  # s por vuelta que cuesta cada litro de más (regla habitual)
PERDIDA_CARRIL_DEFECTO = 22.0  # s si aún no la hemos medido en esta pista
RITMO_REPOSTAJE_DEFECTO = 2.0  # L/s
TIEMPO_NEUMATICOS_DEFECTO = 8.0  # s


@dataclass
class Opcion:
    nombre: str
    viable: bool
    litros: float = 0.0
    neumaticos: bool = False
    vuelta_desde: int | None = None
    vuelta_hasta: int | None = None
    vuelta_ideal: int | None = None
    coste_s: float = 0.0  # tiempo perdido estimado (paradas + degradación)
    motivo: str = ""


def degradacion(vueltas, edad_max):
    """Segundos por vuelta que se pierden por cada vuelta de uso del neumático (regresión lineal).

    Solo usa el juego actual (edad <= edad_max, sin boxes, vueltas válidas) y corrige el peso del combustible.
    """
    juego = []
    for v in vueltas:
        if v.boxes or not v.valida or v.tiempo_ms <= 0 or v.edad_neumaticos > edad_max or v.edad_neumaticos < 2:
            continue
        combustible_inicio = v.combustible_fin + v.combustible
        juego.append((v.edad_neumaticos, v.tiempo_ms / 1000 - K_COMBUSTIBLE * combustible_inicio))
    # Solo las vueltas del juego actual (la secuencia de edades debe ser consecutiva hasta la última)
    juego = juego[-12:]
    if len(juego) < 3:
        return None
    # Descarta vueltas anómalas (tráfico, errores): más de 1,5 s por encima de la mediana
    mediana = statistics.median(t for _, t in juego)
    juego = [(e, t) for e, t in juego if t - mediana < 1.5]
    if len(juego) < 3:
        return None
    xs, ys = [e for e, _ in juego], [t for _, t in juego]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    pendiente = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    return max(0.0, pendiente)


def _coste_degradacion(d, edad, n):
    """Tiempo perdido por degradación en n vueltas empezando con un neumático de `edad` vueltas."""
    return d * sum(edad + i for i in range(1, int(math.ceil(n)) + 1))


def planificar(restantes, combustible, consumo, deposito, margen, degr, edad, perdida_carril, ritmo_repostaje,
               t_neumaticos, vueltas_neumatico, completadas, frac):
    """Opciones de estrategia hasta el final. `restantes` en vueltas (puede ser fraccionario)."""
    if not restantes or not consumo or consumo <= 0:
        return []
    d = degr or 0.0
    necesario = (restantes + margen) * consumo
    neum_ok = vueltas_neumatico is None or vueltas_neumatico >= restantes
    opciones = []

    # A. Sin parar
    comb_ok = combustible >= necesario
    motivo = []
    if not comb_ok:
        motivo.append(f"faltan {necesario - combustible:.1f} L")
    if not neum_ok:
        motivo.append("los neumáticos no llegan")
    opciones.append(Opcion("Sin parar", comb_ok and neum_ok, coste_s=_coste_degradacion(d, edad, restantes),
                           motivo=", ".join(motivo) or "llegas con combustible y neumáticos"))

    # Ventana de parada (en vueltas desde ahora)
    k_max = combustible / consumo - 0.3  # hay que llegar a boxes
    k_min = max(0.2, restantes + margen - deposito / consumo)  # lo que quede tiene que caber en el depósito

    def vuelta_de(k):
        return completadas + max(1, int(math.ceil(frac + k)) if k > 0 else 1)

    def opcion_parada(nombre, con_neumaticos, solo_neumaticos=False):
        lo, hi = (0.2, restantes - 0.5) if solo_neumaticos else (k_min, min(k_max, restantes - 0.3))
        if not con_neumaticos and not neum_ok:
            return Opcion(nombre, False, motivo="los neumáticos no llegan al final")
        if con_neumaticos and vueltas_neumatico is not None:
            hi = min(hi, vueltas_neumatico)  # hay que parar antes de que se acaben las ruedas
        if lo > hi:
            return Opcion(nombre, False, neumaticos=con_neumaticos,
                          motivo="no cabe todo el combustible: necesitarías dos paradas" if not solo_neumaticos
                          else "no queda carrera suficiente")
        mejor = None
        paso = max(0.5, (hi - lo) / 20)
        k = lo
        while k <= hi + 1e-6:
            litros = 0.0 if solo_neumaticos else max(0.0, necesario - combustible)
            parada = perdida_carril + litros / ritmo_repostaje + (t_neumaticos if con_neumaticos else 0.0)
            if con_neumaticos:
                coste = _coste_degradacion(d, edad, k) + _coste_degradacion(d, 0, restantes - k) + parada
            else:
                coste = _coste_degradacion(d, edad, restantes) + parada
            if mejor is None or coste < mejor[0] - 0.05:
                mejor = (coste, k, litros)
            k += paso
        coste, k, litros = mejor
        return Opcion(nombre, True, litros=round(litros, 1), neumaticos=con_neumaticos,
                      vuelta_desde=vuelta_de(lo), vuelta_hasta=vuelta_de(hi),
                      vuelta_ideal=vuelta_de(k) if con_neumaticos else None, coste_s=coste,
                      motivo=f"parada de {perdida_carril + litros / ritmo_repostaje + (t_neumaticos if con_neumaticos else 0):.0f} s")

    if not comb_ok:
        opciones.append(opcion_parada("Parar a repostar", False))
        opciones.append(opcion_parada("Repostar y neumáticos", True))
    else:
        opciones.append(opcion_parada("Parar solo a por neumáticos", True, solo_neumaticos=True))
    return opciones


def recomendada(opciones):
    viables = [o for o in opciones if o.viable]
    return min(viables, key=lambda o: o.coste_s) if viables else None


@dataclass
class EstadoPresiones:
    frio: list = field(default_factory=lambda: [None] * 4)  # psi en frío al empezar el juego
    subida: dict = field(default_factory=dict)  # eje -> psi que sube en caliente (medido hoy)
    capturado: bool = False


class ExtEstrategia:
    """Extensión: mide boxes, calcula el plan y avisa de la ventana de parada."""

    def __init__(self, app):
        self.app = app
        app.estrategia = self
        app.ingeniero.estrategia = self
        self.opciones = []
        self.plan = None
        self.degradacion = None
        self.perdida_carril = None
        self.fuente_perdida = "estimada"
        self.ritmo_repostaje = RITMO_REPOSTAJE_DEFECTO
        self.t_neumaticos = TIEMPO_NEUMATICOS_DEFECTO
        self.presiones = EstadoPresiones()
        self.parada_ahora = (None, None)  # (posición estimada, (gap, rival delante))
        self._entrada = None  # (t, frac) al entrar al pit lane
        self._parado_s = 0.0
        self._litros_parada = 0.0
        self._t_calculo = 0.0
        self._t_ultimo = None
        self._ventana_dicha = None
        self._aviso_entra = None
        self._clave = None

    # ----------------------------------------------------------- ayudas
    @property
    def _bd(self):
        ext = getattr(self.app, "base_datos", None)
        return ext.bd if ext else None

    def perdida_parada(self, litros=0.0, neumaticos=False):
        carril = self.perdida_carril if self.perdida_carril is not None else PERDIDA_CARRIL_DEFECTO
        return carril + litros / self.ritmo_repostaje + (self.t_neumaticos if neumaticos else 0.0)

    # ------------------------------------------------------------- ciclo
    def tick(self):
        a = self.app.analizador
        s = a.snap
        ahora = time.monotonic()
        dt = 0.0 if self._t_ultimo is None else ahora - self._t_ultimo
        self._t_ultimo = ahora
        if s is None or s.graphics.status != mac.STATUS_LIVE:
            return
        ph, gr = s.physics, s.graphics
        if gr.isInPit and ph.speedKmh < 1:
            self._parado_s += dt
        self._capturar_frio(ph)
        if ahora - self._t_calculo >= 1.0:
            self._t_calculo = ahora
            self._calcular(s)
            self._avisos(s)

    def _capturar_frio(self, ph):
        pr = self.presiones
        if pr.capturado or not any(ph.wheelsPressure):
            return
        # En frío = parado y con los neumáticos cerca de la temperatura ambiente
        if ph.speedKmh < 5 and max(ph.tyreCoreTemperature) < ph.airTemp + 12:
            pr.frio = list(ph.wheelsPressure)
            pr.capturado = True
        elif ph.speedKmh > 30:
            pr.capturado = True  # ya rodando: este juego no se puede medir en frío

    def _calcular(self, s):
        a, c = self.app.analizador, self.app.clasificacion
        ph, gr, st = s.physics, s.graphics, s.static
        self.degradacion = degradacion(a.vueltas[a.inicio_juego:], a.edad_neumaticos)
        if self.perdida_carril is None and self._bd and self._clave:
            aprendida = self._bd.perdida_boxes(self._clave[1], self._clave[2])
            if aprendida:
                self.perdida_carril, self.fuente_perdida = aprendida, "aprendida"
        self.opciones = planificar(
            a.vueltas_restantes, ph.fuel, a.combustible_por_vuelta, st.maxFuel or 100,
            self.app.config.margen_vueltas_combustible, self.degradacion, a.edad_neumaticos,
            self.perdida_carril if self.perdida_carril is not None else PERDIDA_CARRIL_DEFECTO,
            self.ritmo_repostaje, self.t_neumaticos, a.vueltas_neumatico, gr.completedLaps,
            gr.normalizedCarPosition) if gr.session == mac.SESION_CARRERA else []
        self.plan = recomendada(self.opciones)
        # ¿Dónde salgo si paro ahora?
        if c.activa and c.carrera:
            litros = self.plan.litros if self.plan and self.plan.nombre != "Sin parar" else 0.0
            neum = bool(self.plan and self.plan.neumaticos)
            self.parada_ahora = c.posicion_tras_parada(self.perdida_parada(litros, neum))
        else:
            self.parada_ahora = (None, None)

    # ---------------------------------------------------------- eventos
    def eventos(self, eventos):
        for ev in eventos:
            if ev.tipo == "sesion":
                self._clave = (ev.datos["coche"], ev.datos["pista"], ev.datos.get("config", ""))
                self.presiones = EstadoPresiones()
                self.perdida_carril, self.fuente_perdida = None, "estimada"
                self._ventana_dicha = self._aviso_entra = None
            elif ev.tipo == "boxes_entrada":
                self._entrada = (ev.datos["t"], ev.datos["frac"])
                self._parado_s, self._litros_parada = 0.0, 0.0
                self._decir_parada()
            elif ev.tipo == "repostaje":
                self._litros_parada += ev.datos["litros"]
            elif ev.tipo == "cambio_neumaticos":
                self.presiones = EstadoPresiones()
            elif ev.tipo == "boxes_salida" and self._entrada:
                self._medir_boxes(ev.datos["t"], ev.datos["frac"])
                self._entrada = None
            elif ev.tipo == "vuelta":
                self._aprender_presiones(ev.datos["vuelta"])

    def _medir_boxes(self, t_salida, frac_salida):
        """Pérdida del carril = tiempo en el pit lane - lo que se tarda en ese tramo en pista (sin la parada)."""
        guia = self.app.analizador.traza_guia
        t_entrada, frac_entrada = self._entrada
        en_carril = t_salida - t_entrada
        if guia is None or en_carril <= 0:
            return
        vuelta = guia["t"][-1] / 1000
        en_pista = interpolar(guia["t"], frac_salida) / 1000 - interpolar(guia["t"], frac_entrada) / 1000
        if en_pista < 0:
            en_pista += vuelta
        carril = en_carril - en_pista - self._parado_s
        if not 3 < carril < 90:
            return
        if self._litros_parada > 2 and self._parado_s > 1:
            self.ritmo_repostaje = max(0.3, self._litros_parada / self._parado_s)
        if self._bd and self._clave:
            self.perdida_carril = self._bd.aprender_perdida_boxes(self._clave[1], self._clave[2], carril)
        else:
            self.perdida_carril = carril
        self.fuente_perdida = "medida"
        log.info("Boxes: %.1f s en el carril, %.1f s parado, pérdida del carril %.1f s", en_carril, self._parado_s, carril)
        self.app.ingeniero.decir(f"Parada de {voz_num(self._parado_s, 1)} segundos. El paso por boxes aquí cuesta "
                                 f"{voz_num(carril + self._parado_s, 0)} segundos.", NORMAL, "medida_boxes", 30, caduca=30)

    def _aprender_presiones(self, v):
        pr = self.presiones
        if not v.valida or v.boxes or v.edad_neumaticos < 2 or not all(pr.frio):
            return
        for eje, ruedas in (("delanteros", (0, 1)), ("traseros", (2, 3))):
            subida = statistics.mean(v.presion[w] for w in ruedas) - statistics.mean(pr.frio[w] for w in ruedas)
            if not 0.2 < subida < 15:
                continue
            anterior = pr.subida.get(eje)
            pr.subida[eje] = subida if anterior is None else anterior * 0.5 + subida * 0.5
            coche = self._clave[0] if self._clave else ""
            if self._bd and coche:
                self._bd.aprender_subida_presion(coche, eje, subida)

    # ------------------------------------------------------- presiones
    def recomendacion_presiones(self):
        """Por eje: (presión en caliente actual, objetivo, subida frío->caliente, presión en frío recomendada)."""
        a = self.app.analizador
        perf = a.perfil
        objetivo = round((perf.psi_min + perf.psi_max) / 2, 1)
        v = a.resumen_neumaticos
        out = {}
        coche = self._clave[0] if self._clave else ""
        for eje, ruedas in (("delanteros", (0, 1)), ("traseros", (2, 3))):
            caliente = statistics.mean(v.presion[w] for w in ruedas) if v else None
            subida = self.presiones.subida.get(eje)
            if subida is None and self._bd and coche:
                subida = self._bd.subida_presion(coche, eje)[0]
            frio_rec = round(objetivo - subida, 1) if subida else None
            out[eje] = (caliente, objetivo, subida, frio_rec)
        return out

    # -------------------------------------------------------------- voz
    def _decir_parada(self):
        """Al entrar en boxes: cuánto echar y si cambiar ruedas."""
        a = self.app.analizador
        if a.vueltas_restantes is None or not a.combustible_por_vuelta or a.snap is None:
            return
        necesario = (a.vueltas_restantes + self.app.config.margen_vueltas_combustible) * a.combustible_por_vuelta
        litros = max(0.0, necesario - a.snap.physics.fuel)
        partes = []
        if litros > 0.3:
            partes.append(f"Echa {voz_num(litros)} litros para terminar")
        else:
            partes.append("No necesitas combustible")
        if a.vueltas_neumatico is not None and a.vueltas_neumatico < a.vueltas_restantes:
            partes.append("y cambia neumáticos")
        elif self.plan and self.plan.neumaticos:
            partes.append("y pon neumáticos nuevos")
        self.app.ingeniero.decir(" ".join(partes) + ".", ALTA, "parada_litros", 20, nivel=0, caduca=20)

    def _avisos(self, s):
        gr = s.graphics
        p = self.plan
        if gr.session != mac.SESION_CARRERA or p is None or p.nombre == "Sin parar" or gr.isInPitLane:
            return
        ing = self.app.ingeniero
        # Se anuncia una vez (a partir de la vuelta 2, con el consumo ya medido) y solo se repite si el plan
        # cambia de tipo o el final de la ventana se mueve 3 vueltas o más.
        dicha = self._ventana_dicha
        # (el inicio de la ventana avanza solo con cada vuelta: no cuenta como cambio)
        cambia = dicha is None or dicha[0] != p.nombre or abs((dicha[2] or 0) - (p.vuelta_hasta or 0)) >= 3
        if cambia and p.vuelta_desde and p.vuelta_hasta and gr.completedLaps >= 1:
            self._ventana_dicha = (p.nombre, p.vuelta_desde, p.vuelta_hasta)
            txt = f"Ventana de parada entre las vueltas {p.vuelta_desde} y {p.vuelta_hasta}"
            if p.vuelta_ideal:
                txt += f", la ideal es la {p.vuelta_ideal}"
            txt += "."
            if p.litros > 0:
                txt += f" Habrá que echar unos {voz_num(p.litros, 0)} litros."
            ing.decir(txt, NORMAL, "ventana", 120, nivel=0, caduca=40)
        vuelta_actual = gr.completedLaps + 1
        objetivo = p.vuelta_ideal or p.vuelta_hasta
        if objetivo and vuelta_actual == objetivo and self._aviso_entra != objetivo:
            self._aviso_entra = objetivo
            pos, delante = self.parada_ahora
            txt = "Entra en boxes al final de esta vuelta."
            if pos:
                txt += f" Saldrías P{pos}"
                if delante:
                    txt += f", detrás de {apellido(delante[1].nombre)}"
                txt += "."
            ing.decir(txt, ALTA, "entra", 60, nivel=0, caduca=30)

    def texto_estrategia(self):
        """Respuesta hablada a 'estrategia'."""
        a = self.app.analizador
        partes = []
        if a.vueltas_restantes is not None:
            partes.append(f"Quedan unas {voz_vueltas(a.vueltas_restantes + 0.5)}.")
        p = self.plan
        if p is None:
            if not self.opciones:
                return None
            return " ".join(partes + ["Ninguna opción es viable con una parada: habrá que parar dos veces o ahorrar mucho."])
        if p.nombre == "Sin parar":
            partes.append("Plan: sin parar. Llegamos con combustible y neumáticos.")
        else:
            txt = f"Plan: {p.nombre.lower()} entre las vueltas {p.vuelta_desde} y {p.vuelta_hasta}"
            if p.vuelta_ideal:
                txt += f", ideal la {p.vuelta_ideal}"
            if p.litros:
                txt += f", echando {voz_num(p.litros, 0)} litros"
            partes.append(txt + ".")
        if self.degradacion is not None and self.degradacion >= 0.02:
            partes.append(f"Los neumáticos pierden {voz_diferencia(self.degradacion * 1000)} por vuelta.")
        pos, delante = self.parada_ahora
        if pos:
            txt = f"Si paras ahora sales P{pos}"
            if delante:
                txt += f", a {voz_diferencia(delante[0] * 1000)} de {apellido(delante[1].nombre)}"
            partes.append(txt + ".")
        return " ".join(partes)

    def texto_presiones(self):
        rec = self.recomendacion_presiones()
        partes = []
        frios = []
        for eje, (caliente, objetivo, subida, frio_rec) in rec.items():
            if caliente is not None:
                partes.append(f"{eje.capitalize()} a {voz_num(caliente)} psi en caliente")
            if frio_rec is not None:
                frios.append(f"{voz_num(frio_rec)} {'delante' if eje == 'delanteros' else 'detrás'}")
        objetivo = next(iter(rec.values()))[1]
        txt = ". ".join(partes) + "." if partes else "Aún no tengo presiones en caliente de una vuelta limpia."
        if frios:
            txt += f" Para llegar a {voz_num(objetivo)} en caliente, pon en frío {' y '.join(frios)}."
        else:
            txt += " Para calcular las presiones en frío necesito salir de boxes con los neumáticos fríos y dar dos vueltas."
        return txt

    def cerrar(self):
        pass
