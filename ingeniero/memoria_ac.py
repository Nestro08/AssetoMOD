"""Lectura de la memoria compartida de Assetto Corsa.

AC publica tres bloques de memoria mientras corre:
  - Local\\acpmf_physics  -> físicas (≈ 300 Hz)
  - Local\\acpmf_graphics -> tiempos, vueltas, banderas (≈ 60 Hz)
  - Local\\acpmf_static   -> datos fijos de la sesión (coche, pista...)

Las estructuras siguen la documentación oficial de AC (v1.7). El orden de
las ruedas en todos los arrays es: 0=DI (del. izq.), 1=DD, 2=TI, 3=TD.

Se abren con OpenFileMappingW (nunca se crean): si abriésemos con
mmap(-1, ...) y AC aún no estuviera arrancado, crearíamos nosotros el
bloque con un tamaño erróneo y AC acabaría usando el nuestro.
"""
import ctypes
import time
from ctypes import c_float, c_int, c_wchar, wintypes
from dataclasses import dataclass


class SPageFilePhysics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int),
        ("gas", c_float),
        ("brake", c_float),
        ("fuel", c_float),
        ("gear", c_int),  # 0 = marcha atrás, 1 = punto muerto, 2 = 1ª...
        ("rpms", c_int),
        ("steerAngle", c_float),
        ("speedKmh", c_float),
        ("velocity", c_float * 3),
        ("accG", c_float * 3),  # x = lateral, y = vertical, z = longitudinal
        ("wheelSlip", c_float * 4),
        ("wheelLoad", c_float * 4),
        ("wheelsPressure", c_float * 4),  # psi
        ("wheelAngularSpeed", c_float * 4),  # rad/s
        ("tyreWear", c_float * 4),  # 100 = nuevo
        ("tyreDirtyLevel", c_float * 4),
        ("tyreCoreTemperature", c_float * 4),
        ("camberRAD", c_float * 4),
        ("suspensionTravel", c_float * 4),
        ("drs", c_float),
        ("tc", c_float),
        ("heading", c_float),
        ("pitch", c_float),
        ("roll", c_float),
        ("cgHeight", c_float),
        ("carDamage", c_float * 5),  # delante, detrás, izq., der., centro
        ("numberOfTyresOut", c_int),
        ("pitLimiterOn", c_int),
        ("abs", c_float),
        ("kersCharge", c_float),
        ("kersInput", c_float),
        ("autoShifterOn", c_int),
        ("rideHeight", c_float * 2),
        ("turboBoost", c_float),
        ("ballast", c_float),
        ("airDensity", c_float),
        ("airTemp", c_float),
        ("roadTemp", c_float),
        ("localAngularVel", c_float * 3),
        ("finalFF", c_float),
        ("performanceMeter", c_float),
        ("engineBrake", c_int),
        ("ersRecoveryLevel", c_int),
        ("ersPowerLevel", c_int),
        ("ersHeatCharging", c_int),
        ("ersIsCharging", c_int),
        ("kersCurrentKJ", c_float),
        ("drsAvailable", c_int),
        ("drsEnabled", c_int),
        ("brakeTemp", c_float * 4),
        ("clutch", c_float),
        ("tyreTempI", c_float * 4),
        ("tyreTempM", c_float * 4),
        ("tyreTempO", c_float * 4),
        ("isAIControlled", c_int),
        ("tyreContactPoint", (c_float * 3) * 4),
        ("tyreContactNormal", (c_float * 3) * 4),
        ("tyreContactHeading", (c_float * 3) * 4),
        ("brakeBias", c_float),
        ("localVelocity", c_float * 3),
    ]


class SPageFileGraphic(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int),
        ("status", c_int),
        ("session", c_int),
        ("currentTime", c_wchar * 15),
        ("lastTime", c_wchar * 15),
        ("bestTime", c_wchar * 15),
        ("split", c_wchar * 15),
        ("completedLaps", c_int),
        ("position", c_int),
        ("iCurrentTime", c_int),  # ms
        ("iLastTime", c_int),
        ("iBestTime", c_int),
        ("sessionTimeLeft", c_float),  # ms
        ("distanceTraveled", c_float),
        ("isInPit", c_int),
        ("currentSectorIndex", c_int),
        ("lastSectorTime", c_int),
        ("numberOfLaps", c_int),
        ("tyreCompound", c_wchar * 33),
        ("replayTimeMultiplier", c_float),
        ("normalizedCarPosition", c_float),
        ("carCoordinates", c_float * 3),
        ("penaltyTime", c_float),
        ("flag", c_int),
        ("idealLineOn", c_int),
        ("isInPitLane", c_int),
        ("surfaceGrip", c_float),
        ("mandatoryPitDone", c_int),
        ("windSpeed", c_float),
        ("windDirection", c_float),
    ]


class SPageFileStatic(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("smVersion", c_wchar * 15),
        ("acVersion", c_wchar * 15),
        ("numberOfSessions", c_int),
        ("numCars", c_int),
        ("carModel", c_wchar * 33),
        ("track", c_wchar * 33),
        ("playerName", c_wchar * 33),
        ("playerSurname", c_wchar * 33),
        ("playerNick", c_wchar * 33),
        ("sectorCount", c_int),
        ("maxTorque", c_float),
        ("maxPower", c_float),
        ("maxRpm", c_int),
        ("maxFuel", c_float),
        ("suspensionMaxTravel", c_float * 4),
        ("tyreRadius", c_float * 4),
        ("maxTurboBoost", c_float),
        ("deprecated_1", c_float),
        ("deprecated_2", c_float),
        ("penaltiesEnabled", c_int),
        ("aidFuelRate", c_float),
        ("aidTireRate", c_float),
        ("aidMechanicalDamage", c_float),
        ("aidAllowTyreBlankets", c_int),
        ("aidStability", c_float),
        ("aidAutoClutch", c_int),
        ("aidAutoBlip", c_int),
        ("hasDRS", c_int),
        ("hasERS", c_int),
        ("hasKERS", c_int),
        ("kersMaxJ", c_float),
        ("engineBrakeSettingsCount", c_int),
        ("ersPowerControllerCount", c_int),
        ("trackSPlineLength", c_float),
        ("trackConfiguration", c_wchar * 33),
        ("ersMaxJ", c_float),
        ("isTimedRace", c_int),
        ("hasExtraLap", c_int),
        ("carSkin", c_wchar * 33),
        ("reversedGridPositions", c_int),
        ("pitWindowStart", c_int),
        ("pitWindowEnd", c_int),
    ]


# --- Constantes de AC ---
STATUS_OFF, STATUS_REPLAY, STATUS_LIVE, STATUS_PAUSE = 0, 1, 2, 3

SESIONES = {
    -1: "Desconocida", 0: "Práctica", 1: "Clasificación", 2: "Carrera",
    3: "Hotlap", 4: "Contrarreloj", 5: "Drift", 6: "Drag",
}
SESION_CARRERA = 2

FLAG_NONE, FLAG_BLUE, FLAG_YELLOW, FLAG_BLACK, FLAG_WHITE, FLAG_CHECKERED, FLAG_PENALTY = range(7)
BANDERAS = {
    FLAG_NONE: "", FLAG_BLUE: "AZUL", FLAG_YELLOW: "AMARILLA", FLAG_BLACK: "NEGRA",
    FLAG_WHITE: "BLANCA", FLAG_CHECKERED: "CUADROS", FLAG_PENALTY: "PENALIZACIÓN",
}

RUEDAS = ("DI", "DD", "TI", "TD")
RUEDAS_LARGO = ("delantera izquierda", "delantera derecha", "trasera izquierda", "trasera derecha")


@dataclass
class Snapshot:
    """Una lectura coherente de los tres bloques de memoria."""
    physics: SPageFilePhysics
    graphics: SPageFileGraphic
    static: SPageFileStatic
    t: float  # time.monotonic() de la lectura
    fuente: str  # "ac" o "demo"


# --- Acceso a la API de Windows ---
_FILE_MAP_READ = 0x0004
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.OpenFileMappingW.restype = wintypes.HANDLE
_k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]


class _Bloque:
    def __init__(self, nombre, tipo):
        self.nombre = nombre
        self.tipo = tipo
        self.handle = None
        self.ptr = None

    def abrir(self):
        h = _k32.OpenFileMappingW(_FILE_MAP_READ, False, self.nombre)
        if not h:
            return False
        ptr = _k32.MapViewOfFile(h, _FILE_MAP_READ, 0, 0, ctypes.sizeof(self.tipo))
        if not ptr:
            _k32.CloseHandle(h)
            return False
        self.handle, self.ptr = h, ptr
        return True

    def leer(self):
        # Copiamos a una estructura propia para no tener punteros vivos a la memoria de AC.
        out = self.tipo()
        ctypes.memmove(ctypes.addressof(out), self.ptr, ctypes.sizeof(self.tipo))
        return out

    def cerrar(self):
        if self.ptr:
            _k32.UnmapViewOfFile(self.ptr)
        if self.handle:
            _k32.CloseHandle(self.handle)
        self.handle = self.ptr = None


class LectorAC:
    """Lee la memoria de AC; se reconecta solo si el juego se cierra y vuelve a abrirse."""

    TIEMPO_SIN_DATOS = 5.0  # s sin cambios en los paquetes -> reconectar

    def __init__(self):
        self.bloques = {
            "physics": _Bloque("Local\\acpmf_physics", SPageFilePhysics),
            "graphics": _Bloque("Local\\acpmf_graphics", SPageFileGraphic),
            "static": _Bloque("Local\\acpmf_static", SPageFileStatic),
        }
        self.conectado = False
        self._ultimo_intento = 0.0
        self._ultimo_paquete = None
        self._t_ultimo_cambio = 0.0

    def _conectar(self):
        ahora = time.monotonic()
        if ahora - self._ultimo_intento < 1.0:
            return False
        self._ultimo_intento = ahora
        if all(b.abrir() for b in self.bloques.values()):
            self.conectado = True
            self._t_ultimo_cambio = ahora
            return True
        self.cerrar()
        return False

    def leer(self):
        if not self.conectado and not self._conectar():
            return None
        phys = self.bloques["physics"].leer()
        graf = self.bloques["graphics"].leer()
        stat = self.bloques["static"].leer()
        ahora = time.monotonic()

        paquete = (phys.packetId, graf.packetId)
        if paquete != self._ultimo_paquete:
            self._ultimo_paquete = paquete
            self._t_ultimo_cambio = ahora
        elif ahora - self._t_ultimo_cambio > self.TIEMPO_SIN_DATOS and graf.status != STATUS_PAUSE:
            # AC cerrado (o colgado): soltamos la memoria para que Windows la libere.
            self.cerrar()
            return None
        if graf.status == STATUS_OFF:
            return None
        return Snapshot(phys, graf, stat, ahora, "ac")

    def cerrar(self):
        for b in self.bloques.values():
            b.cerrar()
        self.conectado = False
