"""Clasificación en vivo, diferencias con rivales y tráfico.

Diferencias "de cronometraje": cada coche guarda a qué hora pasó por cada uno de
los CHECKPOINTS puntos de control de la vuelta. La diferencia entre A (delante)
y B (detrás) es el tiempo que pasó entre que A y B cruzaron el último punto de
control que ha cruzado B. Es lo mismo que hacen los sistemas de cronometraje.
"""
import statistics
from collections import deque
from dataclasses import dataclass, field

from .analisis import Evento
from .puente import DatosPuente

CHECKPOINTS = 100
HISTORIAL_VUELTAS = 3


@dataclass
class Rival:
    id: int
    nombre: str
    coche: str = ""
    pos: int = 0
    spline: float = 0.0
    vueltas: int = 0
    ultima: int = 0
    mejor: int = 0
    actual: int = 0
    kmh: float = 0.0
    pitlane: bool = False
    box: bool = False
    x: float = 0.0
    z: float = 0.0
    compuesto: str = ""
    paradas: int = 0
    vuelta_ultima_parada: int = 0
    pasos: dict = field(default_factory=dict)  # índice de checkpoint absoluto -> t
    tiempos: list = field(default_factory=list)  # vueltas completas (ms)
    _previo: tuple | None = None  # (progreso, t) de la lectura anterior
    cruzo_salida: bool = False  # ya ha pasado por la línea al menos una vez
    intervalo: float | None = None  # s con el coche de delante en la clasificación
    gap_lider: float | None = None
    tendencia: float | None = None  # s/vuelta respecto al jugador (+ = se aleja de ti)

    @property
    def progreso(self):
        # En parrilla, antes de cruzar la línea, AC da 0 vueltas y spline ≈ 0,99
        if self.vueltas == 0 and self.spline > 0.9 and not self.cruzo_salida:
            return self.spline - 1.0
        return self.vueltas + self.spline

    @property
    def indice(self):
        return int(self.progreso * CHECKPOINTS)

    def ritmo(self, n=3):
        """Mediana de las últimas vueltas limpias (ms)."""
        tiempos = [t for t in self.tiempos[-n:] if t > 0]
        return statistics.median(tiempos) if tiempos else None


class Clasificacion:
    def __init__(self):
        self.reiniciar()

    def reiniciar(self):
        self.rivales: dict[int, Rival] = {}
        self.orden: list[Rival] = []
        self.jugador: Rival | None = None
        self.longitud = 0.0
        self.eventos = []
        self.activa = False
        self.carrera = False
        self.t = 0.0
        self._gaps_hist = {}  # id -> deque[(progreso_jugador, gap con el jugador)]
        self.id_jugador = 0
        self._vuelta_rapida = None  # ms

    def extraer_eventos(self):
        ev, self.eventos = self.eventos, []
        return ev

    def _evento(self, tipo, **datos):
        self.eventos.append(Evento(tipo, datos))

    # ------------------------------------------------------------ actualización
    def actualizar(self, datos: DatosPuente | None, carrera: bool, id_jugador=0):
        if datos is None or not datos.coches:
            self.activa = False
            return
        self.activa = True
        self.carrera = carrera
        self.id_jugador = id_jugador
        self.longitud = datos.longitud or self.longitud
        self.t = datos.t
        vistos = set()
        for d in datos.coches:
            r = self.rivales.get(d.id)
            if r is None or r.nombre != d.nombre:
                r = self.rivales[d.id] = Rival(d.id, d.nombre)
            vistos.add(d.id)
            self._actualizar_rival(r, d, datos.t)
        for i in list(self.rivales):
            if i not in vistos:
                del self.rivales[i]

        # Orden: en carrera por progreso en pista; si no, por mejor vuelta
        coches = list(self.rivales.values())
        if carrera:
            coches.sort(key=lambda r: -r.progreso)
        else:
            coches.sort(key=lambda r: (r.mejor <= 0, r.mejor if r.mejor > 0 else 0, r.pos))
        for i, r in enumerate(coches):
            r.pos = i + 1
        self.orden = coches
        self.jugador = self.rivales.get(id_jugador)
        self._calcular_gaps()

    def _actualizar_rival(self, r: Rival, d, t):
        # Vuelta completada
        if d.vueltas > r.vueltas and d.ultima > 0:
            r.tiempos.append(d.ultima)
            if self._vuelta_rapida is None or (0 < d.ultima < self._vuelta_rapida):
                if self._vuelta_rapida is not None and d.id != (self.jugador.id if self.jugador else 0):
                    self._evento("vuelta_rapida_rival", nombre=d.nombre, tiempo=d.ultima)
                self._vuelta_rapida = d.ultima
        # Paradas (la primera lectura no cuenta: el coche puede empezar en boxes)
        if r.pasos and d.pitlane and not r.pitlane:
            r.vuelta_ultima_parada = d.vueltas
            # Una parada invalida la tendencia de las diferencias con ese coche (o con todos si paras tú)
            if d.id == self.id_jugador:
                self._gaps_hist.clear()
            else:
                self._gaps_hist.pop(d.id, None)
            if d.vueltas > 0:
                r.paradas += 1
                if d.id != self.id_jugador:
                    self._evento("rival_boxes", id=d.id, nombre=d.nombre, pos=r.pos)
        for campo in ("coche", "spline", "vueltas", "ultima", "mejor", "actual", "kmh", "pitlane", "box",
                      "x", "z", "compuesto"):
            setattr(r, campo, getattr(d, campo))
        if d.vueltas > 0 or d.spline < 0.5:
            r.cruzo_salida = True
        # Puntos de control: interpolamos el instante exacto de cruce entre dos lecturas
        idx = r.indice
        prog = r.progreso
        if r.pasos:
            ultimo = max(r.pasos)
            if idx < ultimo - CHECKPOINTS:  # reinicio de sesión
                r.pasos.clear()
                r.pasos[idx] = t
            elif idx > ultimo and r._previo is not None:
                p0, t0 = r._previo
                for k in range(ultimo + 1, idx + 1):
                    frac = (k / CHECKPOINTS - p0) / max(1e-9, prog - p0)
                    r.pasos[k] = t0 + (t - t0) * max(0.0, min(1.0, frac))
        else:
            r.pasos[idx] = t
        r._previo = (prog, t)
        limite = idx - CHECKPOINTS * HISTORIAL_VUELTAS
        for k in [k for k in r.pasos if k < limite]:
            del r.pasos[k]

    # ---------------------------------------------------------------- gaps
    def gap(self, delante: Rival, detras: Rival):
        """Segundos que lleva `detras` respecto a `delante` (positivo si va detrás)."""
        if delante is detras:
            return 0.0
        if detras.progreso > delante.progreso:
            return -self.gap(detras, delante)
        idx = detras.indice
        t_detras = detras.pasos.get(idx)
        t_delante = delante.pasos.get(idx)
        if t_detras is not None and t_delante is not None:
            return max(0.0, t_detras - t_delante)
        # Sin historial: estimación por distancia y velocidad
        v = max(detras.kmh, 40.0) / 3.6
        return (delante.progreso - detras.progreso) * (self.longitud or 4000.0) / v

    def _calcular_gaps(self):
        if not self.orden:
            return
        lider = self.orden[0]
        lider.intervalo = lider.gap_lider = None
        for a, b in zip(self.orden, self.orden[1:]):
            b.intervalo = self.gap(a, b) if self.carrera else (b.mejor - a.mejor) / 1000 if a.mejor and b.mejor else None
            b.gap_lider = self.gap(lider, b) if self.carrera else (b.mejor - lider.mejor) / 1000 if lider.mejor and b.mejor else None
        yo = self.jugador
        if yo is None:
            return
        # Tendencia: cómo cambia la diferencia con el delante/detrás en la última vuelta
        for r in self.cercanos():
            if r is None:
                continue
            g = self.gap(r, yo) if r.progreso > yo.progreso else -self.gap(yo, r)
            hist = self._gaps_hist.setdefault(r.id, deque(maxlen=400))
            if not hist or yo.progreso - hist[-1][0] >= 0.02:
                hist.append((yo.progreso, g))
            hace_una = [gg for p, gg in hist if yo.progreso - p >= 0.95]
            tendencia = None if not hace_una else (abs(g) - abs(hace_una[-1]))
            # Un cambio enorme en una vuelta es una parada o un incidente, no ritmo
            r.tendencia = tendencia if tendencia is not None and abs(tendencia) < 3.0 else None

    # ------------------------------------------------------------- consultas
    def cercanos(self):
        """(el de delante, el de detrás) en la clasificación."""
        yo = self.jugador
        if yo is None or yo not in self.orden:
            return None, None
        i = self.orden.index(yo)
        delante = self.orden[i - 1] if i > 0 else None
        detras = self.orden[i + 1] if i + 1 < len(self.orden) else None
        return delante, detras

    def gap_con(self, r: Rival):
        """Diferencia en segundos con el jugador: positiva si el rival va delante."""
        yo = self.jugador
        if yo is None or r is None:
            return None
        if self.carrera:
            return self.gap(r, yo) if r.progreso > yo.progreso else -self.gap(yo, r)
        if r.mejor and yo.mejor:
            return (yo.mejor - r.mejor) / 1000
        return None

    def trafico(self, segundos=3.0):
        """Coches cerca en pista (sin importar vueltas): lista de (rival, segundos, tipo)."""
        yo = self.jugador
        if yo is None:
            return []
        out = []
        v = max(yo.kmh, 40.0) / 3.6
        for r in self.rivales.values():
            if r is yo or r.pitlane:
                continue
            d = ((r.spline - yo.spline + 0.5) % 1.0) - 0.5  # vueltas en pista (+ delante)
            s = d * (self.longitud or 4000.0) / v
            if abs(s) > segundos:
                continue
            vueltas = r.progreso - yo.progreso
            if s < 0 and vueltas > 0.5:
                tipo = "te_dobla"
            elif s > 0 and vueltas < -0.5:
                tipo = "doblado"
            else:
                tipo = "pelea"
            out.append((r, s, tipo))
        out.sort(key=lambda x: abs(x[1]))
        return out

    def posicion_tras_parada(self, perdida_s):
        """Posición estimada si el jugador para ahora y pierde `perdida_s` segundos."""
        yo = self.jugador
        if yo is None or not self.carrera:
            return None, None
        coches = []
        for r in self.orden:
            if r is yo:
                continue
            g = self.gap_con(r)
            if g is None:
                continue
            coches.append((g, r))
        # Tras la parada, el jugador tiene "perdida_s" más de retraso con todos
        delante = [(g + perdida_s, r) for g, r in coches if g + perdida_s > 0]
        pos = len(delante) + 1
        justo_delante = min(delante, key=lambda x: x[0]) if delante else None
        return pos, justo_delante
