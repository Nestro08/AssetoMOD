"""Simulador que rellena las mismas estructuras que AC, para probar sin el juego.

Genera una pista con curvas, un perfil de velocidad realista, cambios de
marcha, temperaturas de neumáticos y frenos, consumo, desgaste y eventos
aleatorios (bloqueos, salidas de pista, banderas, adelantamientos...).
"""
import math
import random
import time

from . import memoria_ac as mac
from .puente import DatoCoche, DatosPuente

N = 1000  # puntos de la pista
LONGITUD = 4500.0  # m
A_LAT_MAX = 16.0  # m/s² (≈1.6 g)
A_FRENO = 14.0
V_MAX = 76.0  # m/s (≈275 km/h)
RADIO_RUEDA = 0.33
MAX_RPM = 8000
# Velocidad (km/h) a corte de cada marcha 1ª..6ª
VEL_MARCHA = [0, 88, 124, 160, 196, 232, 280]

# (posición 0-1, ángulo en grados con signo, anchura en m)
CURVAS = [
    (0.07, 100, 35), (0.14, -40, 50), (0.23, 60, 70), (0.32, 125, 30), (0.41, -55, 55),
    (0.51, 90, 40), (0.59, -70, 40), (0.69, 110, 32), (0.79, 45, 80), (0.90, 150, 28),
]


NOMBRES = ["M. Pérez", "L. Rossi", "J. García", "A. Müller", "C. Dubois", "S. Kowalski", "R. Silva",
           "T. Nakamura", "E. Jensen", "D. Moreau", "P. Romano"]
# Ritmo relativo de cada rival (>1 = más rápido que el ritmo base). El último es un doblado.
RITMOS = [1.006, 1.003, 1.0015, 1.0, 0.9995, 0.998, 0.996, 0.994, 0.991, 0.987, 0.94]
V_PITLANE = 60 / 3.6
T_PARADA = 9.0


class _RivalDemo:
    def __init__(self, id_, nombre, ritmo, s0, parada):
        self.id, self.nombre, self.ritmo = id_, nombre, ritmo
        self.s = s0  # metros absolutos desde la salida (negativo = detrás de la línea)
        self.v = 0.0
        self.t_vuelta = 0.0
        self.ultima = self.mejor = 0
        self.parada = parada  # vuelta en la que para (None = no para)
        self.estado = "pista"
        self.t_box = 0.0
        self.fase = random.uniform(0, 6.28)

    @property
    def vuelta(self):
        return math.floor(self.s / LONGITUD)

    def paso(self, pista, dt, bandera_fin):
        antes = self.vuelta
        pos = self.s % LONGITUD
        if self.estado == "pista":
            ruido = 1 + 0.004 * math.sin(self.fase + self.s / 700)
            objetivo = pista.muestra(pista.v, pos) * self.ritmo * ruido * (0.6 if bandera_fin else 1.0)
            self.v = min(objetivo, self.v + 8.5 * dt)
            if self.parada is not None and self.vuelta == self.parada and pos > 0.97 * LONGITUD:
                self.estado = "pitlane"
        elif self.estado == "pitlane":
            self.v = V_PITLANE
            if pos < 0.5 * LONGITUD and self.parada is not None:  # ha cruzado la línea: al box
                self.estado, self.t_box, self.parada = "box", T_PARADA, None
            elif pos > 0.03 * LONGITUD and self.parada is None and pos < 0.5 * LONGITUD:
                self.estado = "pista"
        elif self.estado == "box":
            self.v = 0.0
            self.t_box -= dt
            if self.t_box <= 0:
                self.estado = "pitlane"
        self.s += self.v * dt
        self.t_vuelta += dt
        if self.vuelta > antes and self.vuelta >= 1:
            self.ultima = int(self.t_vuelta * 1000)
            if self.mejor == 0 or self.ultima < self.mejor:
                self.mejor = self.ultima
            self.t_vuelta = 0.0
        elif self.vuelta > antes:
            self.t_vuelta = 0.0


def _formato(ms):
    ms = max(0, int(ms))
    return f"{ms // 60000}:{(ms // 1000) % 60:02d}:{ms % 1000:03d}"


class _Pista:
    def __init__(self):
        ds = LONGITUD / N
        k = [0.0] * N
        for frac, ang, sigma in CURVAS:
            centro = frac * LONGITUD
            a = math.radians(ang)
            for i in range(N):
                d = i * ds - centro
                d = (d + LONGITUD / 2) % LONGITUD - LONGITUD / 2
                k[i] += a * math.exp(-0.5 * (d / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
        # Corrección para que la pista cierre (giro total = 360°)
        extra = (2 * math.pi - sum(k) * ds) / LONGITUD
        self.k = [x + extra for x in k]

        # Perfil de velocidad: límite por curvatura + pasadas de aceleración y frenada
        lim = [min(V_MAX, math.sqrt(A_LAT_MAX / max(abs(x), 1e-6))) for x in self.k]
        v = lim[:]
        for _ in range(2):
            for j in range(2 * N):  # aceleración hacia delante
                i, s = j % N, (j + 1) % N
                acc = 8.0 * (1 - v[i] / (V_MAX * 1.05))
                v[s] = min(lim[s], math.sqrt(v[i] ** 2 + 2 * max(acc, 0.3) * ds))
            for j in range(2 * N, 0, -1):  # frenada hacia atrás
                i, p = j % N, (j - 1) % N
                v[p] = min(v[p], math.sqrt(v[i] ** 2 + 2 * A_FRENO * ds))
        self.v = v

        # Trazado XY para el mapa
        x = y = rumbo = 0.0
        pts = []
        for i in range(N):
            pts.append((x, y))
            rumbo += self.k[i] * ds
            x += math.cos(rumbo) * ds
            y += math.sin(rumbo) * ds
        dx, dy = x / N, y / N  # repartimos el pequeño error de cierre
        self.xy = [(px - dx * i, py - dy * i) for i, (px, py) in enumerate(pts)]
        self.xs = [q[0] for q in self.xy]
        self.ys = [q[1] for q in self.xy]

    def muestra(self, arr, s):
        f = (s % LONGITUD) / LONGITUD * N
        i = int(f) % N
        j = (i + 1) % N
        t = f - int(f)
        return arr[i] * (1 - t) + arr[j] * t


class SimuladorDemo:
    def __init__(self, vueltas=15, velocidad=1.0, parada=None, litros_parada=25.0):
        self.pista = _Pista()
        self.escala = velocidad
        self.phys = mac.SPageFilePhysics()
        self.graf = mac.SPageFileGraphic()
        self.stat = mac.SPageFileStatic()
        self._t_real = time.monotonic()
        self._rng = random.Random()

        st = self.stat
        st.smVersion, st.acVersion = "1.7", "1.16 DEMO"
        st.numberOfSessions, st.numCars = 1, 12
        st.carModel, st.track, st.trackConfiguration = "ks_ferrari_488_gt3", "demo_circuito", "gp"
        st.playerName, st.playerSurname = "Piloto", "Demo"
        st.sectorCount, st.maxRpm, st.maxFuel = 3, MAX_RPM, 120.0
        st.maxPower, st.maxTorque = 441000.0, 700.0
        for i in range(4):
            st.tyreRadius[i] = RADIO_RUEDA
        st.aidFuelRate = st.aidTireRate = st.aidMechanicalDamage = 1.0
        st.trackSPlineLength = LONGITUD
        st.penaltiesEnabled = 1

        g = self.graf
        g.status, g.session, g.numberOfLaps = mac.STATUS_LIVE, mac.SESION_CARRERA, vueltas
        g.position, g.tyreCompound = 5, "Slick Medium (M)"
        g.sessionTimeLeft = 3_600_000.0
        g.surfaceGrip = 0.97

        p = self.phys
        p.fuel = 45.0
        p.airTemp, p.roadTemp, p.airDensity = 24.0, 33.0, 1.18
        p.brakeBias = 0.56
        p.engineBrake = 3
        p.tc, p.abs = 0.3, 0.3
        for i in range(4):
            p.tyreWear[i] = 100.0
            p.tyreCoreTemperature[i] = p.airTemp
            p.tyreTempI[i] = p.tyreTempM[i] = p.tyreTempO[i] = p.airTemp
            p.brakeTemp[i] = 150.0
            p.wheelLoad[i] = 3000.0

        self.s = 0.0  # metros recorridos en la vuelta
        self.v = 0.0  # salida parada
        self.marcha = 1
        self.t_vuelta = 0.0
        self.t_sector = 0.0
        self._nueva_vuelta_aleatoria()
        self._bloqueo = None  # (rueda, t_restante)
        self._patinada = 0.0
        self._fuera = 0.0
        self._bandera_t = 0.0
        self._frenando = False
        self._tirada_bloqueo = False

        # Parada en boxes del jugador (para probar la estrategia)
        self.parada = parada
        self.litros_parada = litros_parada
        self._estado_boxes = "pista"
        self._t_box = 0.0

        # Rivales en parrilla: el jugador sale 5º
        self.rivales = []
        rng = random.Random(7)
        for i, (nombre, ritmo) in enumerate(zip(NOMBRES, RITMOS)):
            puesto = i + 1 if i < 4 else i + 2
            s0 = (5 - puesto) * 14.0
            parada_r = rng.randint(max(2, vueltas // 3), max(3, 2 * vueltas // 3)) if rng.random() < 0.6 else None
            self.rivales.append(_RivalDemo(i + 1, nombre, ritmo, s0, parada_r))

    def _nueva_vuelta_aleatoria(self):
        r = self._rng
        self._ritmo = r.gauss(1.0, 0.004)
        self._ondas = [(r.uniform(-0.012, 0.012), r.uniform(0, 2 * math.pi), r.choice((2, 3, 5)))
                       for _ in range(3)]
        self._salida_en = r.random() * LONGITUD if r.random() < 0.15 else None
        self._bandera_en = r.random() * LONGITUD if r.random() < 0.2 else None
        self._danio_en = r.random() * LONGITUD if r.random() < 0.05 else None

    def _factor(self, s):
        f = self._ritmo
        frac = s / LONGITUD
        for amp, fase, n in self._ondas:
            f += amp * math.sin(2 * math.pi * n * frac + fase)
        return f

    def leer(self):
        ahora = time.monotonic()
        dt_total = min(0.25, ahora - self._t_real) * self.escala
        self._t_real = ahora
        # Subpasos para que la física no dependa de la frecuencia de lectura
        pasos = max(1, int(dt_total / 0.01))
        for _ in range(pasos):
            self._paso(dt_total / pasos)
        # Posición del jugador según el progreso en pista
        yo = self.graf.completedLaps + self.s / LONGITUD
        self.graf.position = 1 + sum(1 for r in self.rivales if r.s / LONGITUD > yo)
        return mac.Snapshot(
            mac.SPageFilePhysics.from_buffer_copy(self.phys),
            mac.SPageFileGraphic.from_buffer_copy(self.graf),
            mac.SPageFileStatic.from_buffer_copy(self.stat),
            ahora, "demo",
        )

    def cerrar(self):
        pass

    def leer_puente(self):
        """Lo mismo que publicaría la app IngenieroPuente dentro de AC."""
        g, p = self.graf, self.phys
        coches = [DatoCoche(0, "Piloto Demo", self.stat.carModel, g.position, g.position - 1,
                            self.s / LONGITUD, g.completedLaps, g.iLastTime, g.iBestTime, g.iCurrentTime,
                            p.speedKmh, bool(g.isInPitLane), bool(g.isInPit),
                            g.carCoordinates[0], g.carCoordinates[2], "M")]
        for r in self.rivales:
            pos = r.s % LONGITUD
            coches.append(DatoCoche(
                r.id, r.nombre, "ks_ferrari_488_gt3", 0, 0, pos / LONGITUD, max(0, r.vuelta),
                r.ultima, r.mejor, int(r.t_vuelta * 1000), r.v * 3.6,
                r.estado != "pista", r.estado == "box",
                self.pista.muestra(self.pista.xs, pos), self.pista.muestra(self.pista.ys, pos), "M"))
        return DatosPuente("demo_circuito", "gp", LONGITUD, coches, 0, time.monotonic())

    def _boxes(self, v_obj, dt):
        """Parada del jugador: pit lane al final de la vuelta `parada`, repostaje y ruedas nuevas."""
        g, p = self.graf, self.phys
        e = self._estado_boxes
        if e == "pista" and self.parada is not None and g.completedLaps + 1 == self.parada                 and self.s > 0.965 * LONGITUD:
            e = "pitlane"
        elif e == "pitlane_salida" and 0.03 * LONGITUD < self.s < 0.5 * LONGITUD:
            e = "pista"
        if e == "pitlane" and self.s < 0.5 * LONGITUD:  # ha cruzado la línea: al box
            e, self._t_box = "box", T_PARADA
        if e == "box":
            self._t_box -= dt
            p.fuel = min(self.stat.maxFuel, p.fuel + self.litros_parada * dt / T_PARADA)
            if self._t_box <= 0:
                for i in range(4):
                    p.tyreWear[i] = 100.0
                    p.tyreCoreTemperature[i] = 45.0
                    p.tyreTempM[i] = 45.0
                e, self.parada = "pitlane_salida", None
        self._estado_boxes = e
        g.isInPitLane = int(e != "pista")
        g.isInPit = int(e == "box")
        p.pitLimiterOn = int(e != "pista")
        if e == "box":
            return 0.0
        if e != "pista":
            return min(v_obj, V_PITLANE)
        return v_obj

    def _paso(self, dt):
        if dt <= 0:
            return
        p, g, r, pista = self.phys, self.graf, self._rng, self.pista
        terminado = g.flag == mac.FLAG_CHECKERED

        # --- Movimiento ---
        # Cada litro de combustible cuesta ~0,035 s por vuelta (como en la realidad)
        peso = 1 - 0.00037 * (p.fuel - 20)
        v_obj = pista.muestra(pista.v, self.s) * self._factor(self.s) * peso * (0.6 if terminado else 1.0)
        if self._fuera > 0:
            v_obj *= 0.8
        v_obj = self._boxes(v_obj, dt)
        v_prev = self.v
        self.v += max(-A_FRENO * 1.1, min(9.0, (v_obj - self.v) / 0.15)) * dt
        self.v = max(0.0 if self._estado_boxes == "box" or self.t_vuelta < 3 and self.graf.completedLaps == 0
                     else 5.0, self.v)
        acc = (self.v - v_prev) / dt
        self.s += self.v * dt
        self.t_vuelta += dt
        self.t_sector += dt

        # --- Pedales ---
        if acc < -1.5:
            p.brake = min(1.0, -acc / A_FRENO * 1.1)
            p.gas = 0.0
            if not self._frenando:
                self._frenando, self._tirada_bloqueo = True, False
            if not self._tirada_bloqueo and p.brake > 0.6:
                self._tirada_bloqueo = True
                # La frenada de la curva 4 tiende a bloquear la delantera izquierda
                if 0.26 < self.s / LONGITUD < 0.33 and r.random() < 0.6:
                    self._bloqueo = (0, 0.4)
                elif r.random() < 0.08:
                    self._bloqueo = (r.choice((0, 1, 2)), 0.35)
        else:
            self._frenando = False
            p.brake = 0.0
            p.gas = min(1.0, 0.25 + max(0.0, acc) / 6.0) if acc > 0.2 else 0.3
        p.clutch = 1.0

        # --- Marchas y RPM ---
        kmh = self.v * 3.6
        m = self.marcha
        rpm = MAX_RPM * 0.99 * kmh / VEL_MARCHA[m]
        if rpm > 7750 and m < 6:
            m += 1
        elif m > 1 and MAX_RPM * 0.99 * kmh / VEL_MARCHA[m - 1] < 7000:
            m -= 1
        self.marcha = m
        p.gear = m + 1
        p.rpms = int(max(2500, MAX_RPM * 0.99 * kmh / VEL_MARCHA[m]))
        p.speedKmh = kmh

        # --- Fuerzas G y volante ---
        k = pista.muestra(pista.k, self.s)
        lat = max(-1.75, min(1.75, self.v ** 2 * k / 9.81))
        p.accG[0] = lat + r.gauss(0, 0.03)
        p.accG[2] = acc / 9.81 + r.gauss(0, 0.02)
        p.accG[1] = 1.0
        p.steerAngle = max(-1.0, min(1.0, k * 35))
        p.velocity[0] = self.v

        # --- Ruedas: velocidad angular, bloqueos y patinadas ---
        w = [self.v / RADIO_RUEDA] * 4
        if self._bloqueo:
            rueda, resto = self._bloqueo
            w[rueda] *= 0.55
            resto -= dt
            self._bloqueo = (rueda, resto) if resto > 0 and p.brake > 0.2 else None
        if p.gas > 0.95 and kmh < 120 and acc > 3 and r.random() < 0.0015:
            self._patinada = 0.4
        if self._patinada > 0:
            w[2] *= 1.35
            w[3] *= 1.3
            self._patinada -= dt
        for i in range(4):
            p.wheelAngularSpeed[i] = w[i]
            p.wheelSlip[i] = abs(w[i] * RADIO_RUEDA - self.v) / max(self.v, 1)
        carga_izq = 1 + max(0.0, -lat) * 0.35 - max(0.0, lat) * 0.35
        for i in range(4):
            lado = carga_izq if i in (0, 2) else 2 - carga_izq
            eje = 1.0 + (0.15 * p.brake if i < 2 else -0.1 * p.brake)
            p.wheelLoad[i] = 3100 * lado * eje + self.v ** 2 * 0.35

        # --- Temperaturas de neumáticos ---
        for i in range(4):
            lado_ext = (lat < 0) if i in (0, 2) else (lat > 0)  # rueda exterior en la curva
            carga = abs(lat) * (1.5 if lado_ext else 0.6)
            obj = 58 + 24 * carga + (10 * p.brake if i < 2 else 7 * p.gas) + kmh * 0.05
            if self._bloqueo and self._bloqueo[0] == i:
                obj += 60
            core = p.tyreCoreTemperature[i]
            core += (obj + 8 - core) * dt / 25.0
            p.tyreCoreTemperature[i] = core
            m_ = p.tyreTempM[i] + (obj - p.tyreTempM[i]) * dt / 4.0
            p.tyreTempM[i] = m_
            # Demo: delanteras algo infladas (centro más caliente) y traseras con mucha caída
            if i < 2:
                p.tyreTempI[i], p.tyreTempO[i] = m_ - 1.5, m_ - 5.5
            else:
                p.tyreTempI[i], p.tyreTempO[i] = m_ + 7.5, m_ - 4.0
            frio = 24.3 if i < 2 else 23.2
            p.wheelsPressure[i] = frio + (core - 25) * 0.068
            p.tyreWear[i] = max(80.0, p.tyreWear[i] - dt * (0.0015 + 0.004 * carga))
            p.tyreDirtyLevel[i] = 0.0

        # --- Frenos ---
        for i in range(4):
            calor = (135 if i < 2 else 85) * p.brake
            enfr = (p.brakeTemp[i] - p.airTemp) * (0.012 + self.v * 0.0007)
            p.brakeTemp[i] += (calor - enfr) * dt

        # --- Combustible y entorno ---
        p.fuel = max(0.0, p.fuel - (0.004 + 0.04 * p.gas) * dt)
        p.roadTemp = min(40.0, p.roadTemp + dt * 0.0015)
        g.surfaceGrip = min(1.0, g.surfaceGrip + dt * 0.00005)

        # --- Salidas de pista, banderas, daños ---
        if self._salida_en is not None and self.s >= self._salida_en:
            self._salida_en, self._fuera = None, 1.3
        if self._fuera > 0:
            self._fuera -= dt
            p.numberOfTyresOut = 3
        else:
            p.numberOfTyresOut = 0
        if not terminado:
            if self._bandera_en is not None and self.s >= self._bandera_en:
                self._bandera_en, self._bandera_t = None, 9.0
                g.flag = mac.FLAG_YELLOW if r.random() < 0.75 else mac.FLAG_BLUE
            if self._bandera_t > 0:
                self._bandera_t -= dt
                if self._bandera_t <= 0:
                    g.flag = mac.FLAG_NONE
        if self._danio_en is not None and self.s >= self._danio_en:
            self._danio_en = None
            p.carDamage[0] += r.uniform(3, 12)

        for rv in self.rivales:
            rv.paso(pista, dt, terminado)

        # --- Vuelta, sectores, tiempos ---
        g.iCurrentTime = int(self.t_vuelta * 1000)
        g.currentTime = _formato(g.iCurrentTime)
        sector = min(2, int(self.s / LONGITUD * 3))
        if sector != g.currentSectorIndex and self.s < LONGITUD:
            g.lastSectorTime = int(self.t_sector * 1000)
            self.t_sector = 0.0
            g.currentSectorIndex = sector
        if self.s >= LONGITUD:
            self.s -= LONGITUD
            g.lastSectorTime = int(self.t_sector * 1000)
            self.t_sector = 0.0
            g.currentSectorIndex = 0
            vuelta_ms = int(self.t_vuelta * 1000)
            valida = True  # AC real decide la validez; aquí la trata el analizador
            g.iLastTime = vuelta_ms
            g.lastTime = _formato(vuelta_ms)
            if valida and (g.iBestTime == 0 or vuelta_ms < g.iBestTime):
                g.iBestTime = vuelta_ms
                g.bestTime = _formato(vuelta_ms)
            self.t_vuelta = 0.0
            g.completedLaps += 1
            if g.numberOfLaps and g.completedLaps >= g.numberOfLaps:
                g.flag = mac.FLAG_CHECKERED
            self._nueva_vuelta_aleatoria()

        frac = self.s / LONGITUD
        g.normalizedCarPosition = frac
        g.distanceTraveled += self.v * dt
        x, y = pista.muestra(pista.xs, self.s), pista.muestra(pista.ys, self.s)
        g.carCoordinates[0], g.carCoordinates[1], g.carCoordinates[2] = x, 0.0, y
        g.sessionTimeLeft = max(0.0, g.sessionTimeLeft - dt * 1000)
        p.packetId += 1
        g.packetId += 1
