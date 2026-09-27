"""Convierte las lecturas crudas en información útil y genera eventos.

El analizador no habla: solo calcula (delta, consumo, estrategia, estado de
neumáticos...) y deja una lista de `Evento` que el ingeniero traduce a frases.

Cada vuelta se guarda como una traza "por distancia": N_BINS puntos repartidos
a lo largo de la pista con tiempo, velocidad, pedales, volante, marcha, G y
posición. Esa traza es la base del delta, la comparación de vueltas, el
análisis por curvas, las vueltas de referencia y la exportación a MoTeC.
"""
import math
import statistics
from collections import deque
from dataclasses import dataclass, field

from . import memoria_ac as mac
from .config import PERFILES, Config, perfil_para_coche

N_BINS = 1000  # puntos por vuelta
N_ZONAS = 10  # zonas para localizar dónde se pierde tiempo
CANALES = ("t", "v", "gas", "freno", "volante", "marcha", "glat", "glon", "x", "z", "rpm")


@dataclass
class Evento:
    tipo: str
    datos: dict = field(default_factory=dict)


@dataclass
class Vuelta:
    numero: int
    tiempo_ms: int
    sectores: list
    combustible: float
    valida: bool
    boxes: bool
    vel_max: float
    posicion: int
    bloqueos: list  # por rueda
    patinadas: list
    salidas: int
    temp_i: list  # media por rueda
    temp_m: list
    temp_o: list
    presion: list
    temp_freno_max: list
    desgaste: list  # al final de la vuelta
    combustible_fin: float = 0.0
    edad_neumaticos: int = 0  # vueltas con este juego al terminar la vuelta
    traza: dict | None = None  # canal -> lista de N_BINS + 1 valores


class _Acumulador:
    """Medias por rueda durante una vuelta."""

    def __init__(self):
        self.n = 0
        self.i = [0.0] * 4
        self.m = [0.0] * 4
        self.o = [0.0] * 4
        self.p = [0.0] * 4
        self.freno_max = [0.0] * 4

    def sumar(self, ph):
        self.n += 1
        for w in range(4):
            self.i[w] += ph.tyreTempI[w]
            self.m[w] += ph.tyreTempM[w]
            self.o[w] += ph.tyreTempO[w]
            self.p[w] += ph.wheelsPressure[w]
            self.freno_max[w] = max(self.freno_max[w], ph.brakeTemp[w])

    def medias(self):
        n = max(1, self.n)
        return ([x / n for x in self.i], [x / n for x in self.m],
                [x / n for x in self.o], [x / n for x in self.p])


def interpolar(serie, frac):
    """Valor de una serie completa (N_BINS + 1 puntos) en la posición frac (0-1)."""
    f = max(0.0, min(1.0, frac)) * N_BINS
    b = min(N_BINS - 1, int(f))
    return serie[b] + (serie[b + 1] - serie[b]) * (f - b)


def completar_traza(bruta, tiempo_total):
    """Rellena huecos por interpolación. El canal 't' empieza en 0 y termina en el tiempo de vuelta."""
    out = {}
    for canal, valores in bruta.items():
        puntos = [(i, x) for i, x in enumerate(valores) if x is not None]
        if canal == "t":
            puntos = [(0, 0.0)] + [(i, x) for i, x in puntos if i > 0] + [(N_BINS, float(tiempo_total))]
        elif not puntos:
            out[canal] = [0.0] * (N_BINS + 1)
            continue
        else:
            puntos = [(0, puntos[0][1])] * (puntos[0][0] > 0) + puntos + [(N_BINS, puntos[-1][1])]
        serie = [0.0] * (N_BINS + 1)
        for (i0, x0), (i1, x1) in zip(puntos, puntos[1:]):
            for i in range(i0, i1 + 1):
                serie[i] = x0 + (x1 - x0) * (i - i0) / max(1, i1 - i0)
        if canal == "t":
            for i in range(1, len(serie)):
                serie[i] = max(serie[i], serie[i - 1])
        out[canal] = serie
    return out


class Analizador:
    def __init__(self, config: Config):
        self.cfg = config
        self.eventos: list[Evento] = []
        self.snap = None
        self.fuente = None
        self.trazas = deque(maxlen=900)  # (t, kmh, gas, freno) para la gráfica en vivo
        self.g_estela = deque(maxlen=45)
        self.referencia = None  # vuelta de referencia histórica (la pone la base de datos)
        self._reiniciar_sesion()

    # ------------------------------------------------------------------ estado
    def _reiniciar_sesion(self):
        self.vueltas: list[Vuelta] = []
        self.mejor: Vuelta | None = None
        self.n_sectores = 3
        self.mejores_sectores = [None] * self.n_sectores
        self.sectores_actuales = [None] * self.n_sectores
        self._bruta = self._traza_vacia()
        self.delta_ms = None
        self.delta_ultima_ms = None
        self.delta_ref_ms = None
        self.tiempo_previsto = None
        self.mapa = [None] * N_BINS
        self.marcas = deque(maxlen=120)  # (frac, tipo, rueda, n_vuelta)
        self.vuelta_valida = True
        self.vuelta_boxes = False
        self._acum = _Acumulador()
        self._bloqueos = [0] * 4
        self._patinadas = [0] * 4
        self._salidas = 0
        self._vel_max = 0.0
        self._combustible_inicio = None
        self._combustible_prev = None
        self._inicio_sector_ms = 0
        self._sector_prev = None
        self._vueltas_prev = None
        self._pos_prev = None
        self._bandera_prev = None
        self._pitlane_prev = None
        self._danio_prev = None
        self._desgaste_prev = None
        self._fuera_prev = 0
        self._aviso_limitador = False
        self._aviso_ultima = False
        self._aviso_fin = False
        self._t_bloqueo = [0.0] * 4
        self._t_patinada = [0.0] * 4
        self._pendiente = None
        self._ilast_prev = None
        self._ultimo_ms_actual = 0
        self._sesion_clave = None
        self._dist_prev = 0.0
        self._t_traza = 0.0
        self.edad_neumaticos = 0
        self.inicio_juego = 0  # índice en self.vueltas de la primera vuelta del juego de neumáticos actual
        self.longitud_pista = 0.0
        # Canales que el coche simula de verdad (se detectan viendo si varían)
        self._rango_freno = [1e9, -1e9]
        self.hay_temp_frenos = False
        self.resumen_neumaticos = None  # medias de la última vuelta limpia
        self.combustible_por_vuelta = None
        self.vueltas_con_combustible = None
        self.vueltas_restantes = None
        self.combustible_necesario = None
        self.combustible_sobra = None
        self.desgaste_por_vuelta = None
        self.vueltas_neumatico = None
        self.vuelta_media_ms = None
        self.perfil = PERFILES["gt"]

    @staticmethod
    def _traza_vacia():
        return {c: [None] * N_BINS for c in CANALES}

    def extraer_eventos(self):
        ev, self.eventos = self.eventos, []
        return ev

    def _evento(self, tipo, **datos):
        self.eventos.append(Evento(tipo, datos))

    def desconectado(self):
        if self.snap is not None:
            self._evento("desconectado")
        self.snap = None

    @property
    def traza_mejor(self):
        return self.mejor.traza if self.mejor else None

    @property
    def traza_ultima(self):
        for v in reversed(self.vueltas):
            if v.traza and not v.boxes:
                return v.traza
        return None

    @property
    def traza_guia(self):
        """La mejor traza disponible para saber cómo es la pista (frenadas, curvas)."""
        if self.referencia:
            return self.referencia["traza"]
        return self.traza_mejor or self.traza_ultima

    # ------------------------------------------------------------ actualización
    def actualizar(self, snap: mac.Snapshot):
        ph, gr, st = snap.physics, snap.graphics, snap.static
        # AC deja frames a cero mientras carga o sale al menú: los ignoramos
        if gr.status == mac.STATUS_LIVE and not any(ph.wheelsPressure) and ph.fuel == 0:
            return
        primera = self.snap is None
        self.fuente = snap.fuente

        clave = (st.carModel, st.track, st.trackConfiguration, gr.session)
        reinicio = (
            clave != self._sesion_clave
            or (self._vueltas_prev is not None and gr.completedLaps < self._vueltas_prev)
            or gr.distanceTraveled < self._dist_prev - 200
        )
        if reinicio:
            self._reiniciar_sesion()
            self._sesion_clave = clave
            self.perfil = perfil_para_coche(st.carModel, self.cfg.perfil_forzado, self.cfg.perfiles_personalizados)
            self.n_sectores = max(1, min(8, st.sectorCount or 3))
            self.mejores_sectores = [None] * self.n_sectores
            self.sectores_actuales = [None] * self.n_sectores
            self.longitud_pista = st.trackSPlineLength
            self.snap = snap
            self._evento("sesion", coche=st.carModel, pista=st.track, config=st.trackConfiguration,
                         sesion=mac.SESIONES.get(gr.session, "?"), primera=primera)
        self.snap = snap
        self._dist_prev = gr.distanceTraveled

        if gr.status != mac.STATUS_LIVE:
            return

        kmh = ph.speedKmh
        frac = gr.normalizedCarPosition
        en_pitlane = bool(gr.isInPitLane or gr.isInPit)

        if self._combustible_inicio is None:
            self._combustible_inicio = ph.fuel
        self._vel_max = max(self._vel_max, kmh)
        if en_pitlane:
            self.vuelta_boxes = True
        elif kmh > 60:
            self._acum.sumar(ph)

        # ¿Simula el coche la temperatura de frenos?
        fmax = max(ph.brakeTemp)
        self._rango_freno[0] = min(self._rango_freno[0], fmax)
        self._rango_freno[1] = max(self._rango_freno[1], fmax)
        self.hay_temp_frenos = self._rango_freno[1] - self._rango_freno[0] > 15

        # Gráfica en vivo
        if snap.t - self._t_traza >= 1 / 30:
            self._t_traza = snap.t
            self.trazas.append((snap.t, kmh, ph.gas, ph.brake))
            self.g_estela.append((ph.accG[0], ph.accG[2]))

        # Mapa de la pista (se construye en la primera vuelta)
        b = min(N_BINS - 1, int(frac * N_BINS))
        if not en_pitlane and self.mapa[b] is None and kmh > 20:
            self.mapa[b] = (gr.carCoordinates[0], gr.carCoordinates[2])

        self._repostajes_y_neumaticos(ph)
        self._vueltas_y_sectores(snap, frac)
        self._traza_y_delta(snap, frac)
        self._ruedas(snap, kmh, frac)
        self._salidas_pista(ph, frac)
        self._banderas_posicion_boxes(snap, en_pitlane, frac)
        self._danios(ph)
        self._estrategia(ph, gr, st, frac)

    # ------------------------------------------------ repostajes y neumáticos
    def _repostajes_y_neumaticos(self, ph):
        if self._combustible_prev is not None and ph.fuel - self._combustible_prev > 0.5:
            self._evento("repostaje", litros=ph.fuel - self._combustible_prev)
            self._combustible_inicio = None  # esta vuelta no cuenta para el consumo
        self._combustible_prev = ph.fuel
        desgaste = list(ph.tyreWear)
        if self._desgaste_prev and sum(desgaste) - sum(self._desgaste_prev) > 0.5:
            self.edad_neumaticos = 0
            self.inicio_juego = len(self.vueltas) + (1 if self._pendiente else 0)
            self._evento("cambio_neumaticos")
        self._desgaste_prev = desgaste

    # --------------------------------------------------------------- vueltas
    def _vueltas_y_sectores(self, snap, frac):
        gr, ph = snap.graphics, snap.physics
        if self._vueltas_prev is None:
            self._vueltas_prev = gr.completedLaps
            self._ilast_prev = gr.iLastTime
            self._sector_prev = gr.currentSectorIndex

        # Sectores (medidos con el crono de la vuelta)
        sec = gr.currentSectorIndex
        if sec != self._sector_prev and 0 < sec < self.n_sectores and sec == (self._sector_prev or 0) + 1:
            t = gr.iCurrentTime - self._inicio_sector_ms
            self._cerrar_sector(sec - 1, t)
            self._inicio_sector_ms = gr.iCurrentTime
        self._sector_prev = sec

        if gr.completedLaps > self._vueltas_prev and self._pendiente is None:
            # AC puede tardar un frame en actualizar iLastTime: esperamos un poco.
            self._pendiente = {
                "t": snap.t, "numero": gr.completedLaps, "medido": self._ultimo_ms_actual,
                "traza": self._bruta,
            }
            self._bruta = self._traza_vacia()
            self._vueltas_prev = gr.completedLaps
        if self._pendiente is not None:
            cambiado = gr.iLastTime != self._ilast_prev and gr.iLastTime > 0
            if cambiado or snap.t - self._pendiente["t"] > 1.0:
                tiempo = gr.iLastTime if cambiado else self._pendiente["medido"]
                self._cerrar_vuelta(ph, gr, tiempo)
                self._ilast_prev = gr.iLastTime
                self._pendiente = None
        self._ultimo_ms_actual = gr.iCurrentTime

    def _cerrar_sector(self, idx, t):
        if t <= 0:
            return
        self.sectores_actuales[idx] = t
        mejor = self.mejores_sectores[idx]
        es_mejor = self.vuelta_valida and (mejor is None or t < mejor)
        if es_mejor:
            self.mejores_sectores[idx] = t
        self._evento("sector", indice=idx, tiempo=t, mejor=es_mejor,
                     diferencia=None if mejor is None else t - mejor)

    def _cerrar_vuelta(self, ph, gr, tiempo):
        p = self._pendiente
        # Último sector = tiempo total menos los anteriores
        n = self.n_sectores
        previos = [s for s in self.sectores_actuales[:n - 1] if s]
        if len(previos) == n - 1:
            self._cerrar_sector(n - 1, tiempo - sum(previos))
        sectores = list(self.sectores_actuales)

        combustible = (self._combustible_inicio - ph.fuel) if self._combustible_inicio is not None else 0.0
        ti, tm, to, pr = self._acum.medias()
        valida = self.vuelta_valida and tiempo > 0
        self.edad_neumaticos += 1
        rellenos = sum(1 for x in p["traza"]["t"] if x is not None)
        traza = completar_traza(p["traza"], tiempo) if tiempo > 0 and rellenos > N_BINS * 0.2 else None
        v = Vuelta(
            numero=p["numero"], tiempo_ms=tiempo, sectores=sectores, combustible=combustible,
            valida=valida, boxes=self.vuelta_boxes, vel_max=self._vel_max, posicion=gr.position,
            bloqueos=list(self._bloqueos), patinadas=list(self._patinadas), salidas=self._salidas,
            temp_i=ti, temp_m=tm, temp_o=to, presion=pr, temp_freno_max=list(self._acum.freno_max),
            desgaste=list(ph.tyreWear), combustible_fin=ph.fuel, edad_neumaticos=self.edad_neumaticos,
            traza=traza,
        )
        mejor_prev = self.mejor
        zona = self._zona_perdida(traza) if traza and self.traza_mejor and not self.vuelta_boxes else None

        es_mejor = valida and not v.boxes and traza is not None and \
            (self.mejor is None or tiempo < self.mejor.tiempo_ms)
        if es_mejor:
            self.mejor = v
        self.vueltas.append(v)
        if self._acum.n > 50 and not v.boxes:
            self.resumen_neumaticos = v

        self._evento("vuelta", vuelta=v, mejor=es_mejor,
                     diferencia=None if mejor_prev is None else tiempo - mejor_prev.tiempo_ms,
                     zona=zona)

        # Reinicio de acumuladores de vuelta
        self.sectores_actuales = [None] * self.n_sectores
        self._acum = _Acumulador()
        self._bloqueos = [0] * 4
        self._patinadas = [0] * 4
        self._salidas = 0
        self._vel_max = 0.0
        self._combustible_inicio = ph.fuel
        self._inicio_sector_ms = 0
        self.vuelta_valida = True
        self.vuelta_boxes = bool(gr.isInPitLane or gr.isInPit)

    def _zona_perdida(self, traza):
        """Zona de la vuelta donde más tiempo se ha perdido respecto a la mejor."""
        peor, peor_zona = 0.0, None
        paso = N_BINS // N_ZONAS
        t, tm = traza["t"], self.traza_mejor["t"]
        for z in range(N_ZONAS):
            a, b = z * paso, (z + 1) * paso
            perdida = (t[b] - t[a]) - (tm[b] - tm[a])
            if perdida > peor:
                peor, peor_zona = perdida, z
        if peor_zona is None or peor < 120:
            return None
        centro = (peor_zona + 0.5) / N_ZONAS
        n = self.n_sectores
        return {"zona": peor_zona, "frac": centro, "sector": min(n - 1, int(centro * n)), "perdida": peor}

    def _traza_y_delta(self, snap, frac):
        gr, ph = snap.graphics, snap.physics
        t = gr.iCurrentTime
        if t < 3000 and frac > 0.9:  # aún antes de la línea de meta
            return
        b = min(N_BINS - 1, int(frac * N_BINS))
        bruta = self._bruta
        if bruta["t"][b] is None:
            bruta["t"][b] = t
            bruta["v"][b] = ph.speedKmh
            bruta["gas"][b] = ph.gas
            bruta["freno"][b] = ph.brake
            bruta["volante"][b] = ph.steerAngle
            bruta["marcha"][b] = ph.gear - 1
            bruta["glat"][b] = ph.accG[0]
            bruta["glon"][b] = ph.accG[2]
            bruta["x"][b] = gr.carCoordinates[0]
            bruta["z"][b] = gr.carCoordinates[2]
            bruta["rpm"][b] = ph.rpms
        if self.traza_mejor:
            self.delta_ms = t - interpolar(self.traza_mejor["t"], frac)
            self.tiempo_previsto = self.mejor.tiempo_ms + self.delta_ms
        ultima = self.traza_ultima
        if ultima:
            self.delta_ultima_ms = t - interpolar(ultima["t"], frac)
        if self.referencia:
            self.delta_ref_ms = t - interpolar(self.referencia["traza"]["t"], frac)

    def segundos_libres(self, frac=None):
        """Segundos hasta la próxima frenada o curva fuerte según la traza guía (None si no se sabe)."""
        guia = self.traza_guia
        if guia is None or self.snap is None:
            return None
        if frac is None:
            frac = self.snap.graphics.normalizedCarPosition
        b0 = min(N_BINS - 1, int(frac * N_BINS))
        t, freno, glat = guia["t"], guia["freno"], guia["glat"]
        vuelta = t[N_BINS]
        for paso in range(1, N_BINS):
            b = (b0 + paso) % N_BINS
            if freno[b] > 0.2 or abs(glat[b]) > 1.0:
                dt = t[b] - t[b0]
                if dt < 0:
                    dt += vuelta
                return dt / 1000.0
        return vuelta / 1000.0

    # ------------------------------------------------------ ruedas y pilotaje
    def _ruedas(self, snap, kmh, frac):
        ph, st = snap.physics, snap.static
        v = kmh / 3.6
        if kmh < self.cfg.velocidad_min_deteccion or snap.graphics.isInPitLane:
            return
        for w in range(4):
            r = st.tyreRadius[w] or 0.33
            ratio = (ph.wheelAngularSpeed[w] * r - v) / v
            if ph.brake > 0.2 and ratio < self.cfg.umbral_bloqueo:
                if snap.t - self._t_bloqueo[w] > 0.8:
                    self._bloqueos[w] += 1
                    self.marcas.append((frac, "bloqueo", w, len(self.vueltas) + 1))
                    self._evento("bloqueo", rueda=w, frac=frac)
                self._t_bloqueo[w] = snap.t
            if ph.gas > 0.3 and ratio > self.cfg.umbral_patinada:
                if snap.t - self._t_patinada[w] > 0.8:
                    self._patinadas[w] += 1
                    self.marcas.append((frac, "patinada", w, len(self.vueltas) + 1))
                    self._evento("patinada", rueda=w, frac=frac)
                self._t_patinada[w] = snap.t

    def _salidas_pista(self, ph, frac):
        fuera = ph.numberOfTyresOut
        if fuera >= 3 and self._fuera_prev < 3:
            self._salidas += 1
            self.marcas.append((frac, "salida", -1, len(self.vueltas) + 1))
            if self.vuelta_valida:
                self.vuelta_valida = False
                self._evento("vuelta_invalida", frac=frac)
        self._fuera_prev = fuera

    def _banderas_posicion_boxes(self, snap, en_pitlane, frac):
        ph, gr = snap.physics, snap.graphics
        if gr.flag != self._bandera_prev:
            if self._bandera_prev is not None:
                self._evento("bandera", bandera=gr.flag, anterior=self._bandera_prev)
            self._bandera_prev = gr.flag

        if gr.position > 0:
            if self._pos_prev and gr.position != self._pos_prev:
                self._evento("posicion", anterior=self._pos_prev, nueva=gr.position)
            self._pos_prev = gr.position

        if self._pitlane_prev is not None and en_pitlane != self._pitlane_prev:
            self._evento("boxes_entrada" if en_pitlane else "boxes_salida", t=snap.t, frac=frac,
                         vuelta=gr.completedLaps)
            self._aviso_limitador = False
        self._pitlane_prev = en_pitlane
        if gr.isInPitLane and not ph.pitLimiterOn and ph.speedKmh > 65 and not self._aviso_limitador:
            self._aviso_limitador = True
            self._evento("limitador")

        if gr.session == mac.SESION_CARRERA and gr.numberOfLaps > 0:
            if gr.completedLaps == gr.numberOfLaps - 1 and not self._aviso_ultima:
                self._aviso_ultima = True
                self._evento("ultima_vuelta")
        if gr.flag == mac.FLAG_CHECKERED and not self._aviso_fin:
            self._aviso_fin = True
            self._evento("fin", posicion=gr.position)

    def _danios(self, ph):
        d = list(ph.carDamage)
        if self._danio_prev is not None:
            inc = [a - b for a, b in zip(d, self._danio_prev)]
            if max(inc) > 0.5:
                self._evento("danio", zona=inc.index(max(inc)), cantidad=max(inc), total=d)
        self._danio_prev = d

    # ------------------------------------------------------------ estrategia
    def vueltas_limpias(self, n=5):
        return [v for v in self.vueltas[-n:] if v.valida and not v.boxes and v.tiempo_ms > 0]

    def _estrategia(self, ph, gr, st, frac):
        # La primera vuelta (salida parada) se descarta en cuanto hay otras
        consumos = [v.combustible for v in self.vueltas[-6:]
                    if not v.boxes and 0.05 < v.combustible < 50
                    and not (v.numero == 1 and len(self.vueltas) > 2)]
        if consumos:
            self.combustible_por_vuelta = statistics.mean(consumos[-4:])
        elif frac > 0.25 and self._combustible_inicio is not None and not self.vueltas:
            usado = self._combustible_inicio - ph.fuel
            if usado > 0.05:
                self.combustible_por_vuelta = usado / frac

        tiempos = [v.tiempo_ms for v in self.vueltas_limpias()]
        self.vuelta_media_ms = statistics.median(tiempos) if tiempos else None

        if gr.numberOfLaps > 0 and gr.session == mac.SESION_CARRERA:
            self.vueltas_restantes = max(0.0, gr.numberOfLaps - gr.completedLaps - frac)
        elif self.vuelta_media_ms and gr.sessionTimeLeft > 0:
            quedan = gr.sessionTimeLeft / self.vuelta_media_ms
            self.vueltas_restantes = math.ceil(quedan + frac) - frac + (1 if st.hasExtraLap else 0)
        else:
            self.vueltas_restantes = None

        cpv = self.combustible_por_vuelta
        if cpv:
            self.vueltas_con_combustible = ph.fuel / cpv
            if self.vueltas_restantes is not None:
                self.combustible_necesario = (self.vueltas_restantes + self.cfg.margen_vueltas_combustible) * cpv
                self.combustible_sobra = ph.fuel - self.combustible_necesario
        else:
            self.vueltas_con_combustible = None

        # Desgaste medio por vuelta (peor rueda), solo con el juego actual
        juego = [v for v in self.vueltas if v.edad_neumaticos >= 1][-4:]
        juego = [v for v in juego if v.edad_neumaticos <= self.edad_neumaticos]
        if len(juego) >= 2:
            a, b = juego[0], juego[-1]
            n = b.edad_neumaticos - a.edad_neumaticos
            if n > 0:
                por_vuelta = max((x - y) / n for x, y in zip(a.desgaste, b.desgaste))
                self.desgaste_por_vuelta = por_vuelta if por_vuelta > 0.001 else None
                if self.desgaste_por_vuelta:
                    peor = min(ph.tyreWear)
                    self.vueltas_neumatico = max(0.0, (peor - self.cfg.desgaste_critico) / self.desgaste_por_vuelta)

    # --------------------------------------------------------- diagnósticos
    def diagnostico_neumaticos(self):
        """Consejos de reglaje a partir de las temperaturas I/M/E y presiones de la última vuelta."""
        v = self.resumen_neumaticos
        if v is None:
            return []
        perf = self.perfil
        consejos = []
        for eje, ruedas in (("delanteros", (0, 1)), ("traseros", (2, 3))):
            i = statistics.mean(v.temp_i[w] for w in ruedas)
            m = statistics.mean(v.temp_m[w] for w in ruedas)
            o = statistics.mean(v.temp_o[w] for w in ruedas)
            p = statistics.mean(v.presion[w] for w in ruedas)
            bordes = (i + o) / 2
            if p > perf.psi_max:
                consejos.append(("presion_alta", eje, p))
            elif p < perf.psi_min:
                consejos.append(("presion_baja", eje, p))
            elif m - bordes > 3.5:
                consejos.append(("centro_caliente", eje, m - bordes))
            elif bordes - m > 3.5:
                consejos.append(("bordes_calientes", eje, bordes - m))
            if i - o > 9:
                consejos.append(("mucha_caida", eje, i - o))
            elif i - o < 2:
                consejos.append(("poca_caida", eje, i - o))
            media = (i + m + o) / 3
            if media < perf.temp_neum_min - 3:
                consejos.append(("frios", eje, media))
            elif media > perf.temp_neum_max + 3:
                consejos.append(("calientes", eje, media))
        if self.hay_temp_frenos:  # muchos coches de AC no simulan la temperatura de frenos
            for eje, ruedas in (("delanteros", (0, 1)), ("traseros", (2, 3))):
                fmax = max(v.temp_freno_max[w] for w in ruedas)
                if fmax > perf.temp_freno_max:
                    consejos.append(("frenos_calientes", eje, fmax))
                elif 0 < fmax < perf.temp_freno_min:
                    consejos.append(("frenos_frios", eje, fmax))
        return consejos

    def bloqueos_repetidos(self):
        """Ruedas y zonas donde se repiten bloqueos en las últimas dos vueltas."""
        vuelta_actual = len(self.vueltas) + 1
        zonas = {}
        for frac, tipo, rueda, n in self.marcas:
            if tipo == "bloqueo" and n >= vuelta_actual - 2:
                clave = (rueda, int(frac * N_ZONAS))
                zonas.setdefault(clave, set()).add(n)
        return [(r, z) for (r, z), vueltas in zonas.items() if len(vueltas) >= 2]
