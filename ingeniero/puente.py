"""Comunicación con la app IngenieroPuente que corre dentro de AC.

  Local\\IngenieroPuente  (AC -> nosotros): datos de todos los coches
  Local\\IngenieroHUD     (nosotros -> AC): texto que se pinta en el HUD del juego

Formato de ambos bloques: "seq(10)|largo(10)|datos|seq(10)".
"""
import ctypes
import mmap
import time
from dataclasses import dataclass

from .memoria_ac import _FILE_MAP_READ, _k32

TAM_PUENTE = 65536
TAM_HUD = 8192
CAB = 22  # cabecera "%010d|%010d|"


@dataclass
class DatoCoche:
    id: int
    nombre: str
    coche: str
    pos: int  # posición en la clasificación (1 = primero)
    pos_rt: int  # posición en tiempo real (0 = primero)
    spline: float  # 0-1 a lo largo de la vuelta
    vueltas: int
    ultima: int  # ms
    mejor: int
    actual: int
    kmh: float
    pitlane: bool
    box: bool
    x: float
    z: float
    compuesto: str = ""


@dataclass
class DatosPuente:
    pista: str
    configuracion: str
    longitud: float
    coches: list
    enfocado: int
    t: float


def parsear(texto, t):
    pista, config, longitud, enfocado = "", "", 0.0, 0
    coches = []
    for linea in texto.split("\n"):
        c = linea.split("|")
        try:
            if c[0] == "P" and len(c) >= 6:
                pista, config, longitud, enfocado = c[1], c[2], float(c[3]), int(c[5])
            elif c[0] == "C" and len(c) >= 17:
                coches.append(DatoCoche(
                    id=int(c[1]), nombre=c[2], coche=c[3], pos=int(c[4]), pos_rt=int(c[5]),
                    spline=float(c[6]), vueltas=int(c[7]), ultima=int(c[8]), mejor=int(c[9]),
                    actual=int(c[10]), kmh=float(c[11]), pitlane=c[12] == "1", box=c[13] == "1",
                    x=float(c[14]), z=float(c[15]), compuesto=c[16],
                ))
        except (ValueError, IndexError):
            continue
    return DatosPuente(pista, config, longitud, coches, enfocado, t)


class LectorPuente:
    """Lee lo que publica la app de AC. Devuelve None si la app no está activa."""

    SIN_CAMBIOS_S = 3.0

    def __init__(self):
        self.handle = None
        self.ptr = None
        self._seq = None
        self._t_cambio = 0.0
        self._t_intento = 0.0
        self.activo = False

    def _abrir(self):
        ahora = time.monotonic()
        if ahora - self._t_intento < 2.0:
            return False
        self._t_intento = ahora
        h = _k32.OpenFileMappingW(_FILE_MAP_READ, False, "Local\\IngenieroPuente")
        if not h:
            return False
        ptr = _k32.MapViewOfFile(h, _FILE_MAP_READ, 0, 0, TAM_PUENTE)
        if not ptr:
            _k32.CloseHandle(h)
            return False
        self.handle, self.ptr = h, ptr
        self._t_cambio = ahora
        return True

    def leer(self):
        if self.ptr is None and not self._abrir():
            self.activo = False
            return None
        for _ in range(3):  # si pillamos una escritura a medias, reintentamos
            cab = ctypes.string_at(self.ptr, CAB).decode("ascii", "ignore")
            if len(cab) < CAB or cab[10] != "|":
                break
            try:
                s1, largo = int(cab[0:10]), int(cab[11:21])
            except ValueError:
                break
            if not 0 < largo <= TAM_PUENTE - CAB - 11:
                break
            bloque = ctypes.string_at(self.ptr + CAB, largo + 11)
            fin = bloque[largo:].decode("ascii", "ignore")
            if fin[1:] != "%010d" % s1:
                continue
            ahora = time.monotonic()
            if s1 != self._seq:
                self._seq, self._t_cambio = s1, ahora
            elif ahora - self._t_cambio > self.SIN_CAMBIOS_S:
                self.cerrar()  # AC cerrado o app desactivada
                return None
            self.activo = True
            return parsear(bloque[:largo].decode("utf-8", "ignore"), ahora)
        self.activo = False
        return None

    def cerrar(self):
        if self.ptr:
            _k32.UnmapViewOfFile(self.ptr)
        if self.handle:
            _k32.CloseHandle(self.handle)
        self.handle = self.ptr = None
        self.activo = False


class EscritorHUD:
    """Escribe las líneas del HUD. Cada línea: clave=texto|color."""

    def __init__(self):
        self.mem = None
        self.seq = 0
        try:
            self.mem = mmap.mmap(-1, TAM_HUD, "Local\\IngenieroHUD")
        except OSError:
            self.mem = None

    def escribir(self, lineas: dict):
        if self.mem is None:
            return
        texto = "\n".join(f"{k}={v}" for k, v in lineas.items())
        datos = texto.encode("utf-8")[:TAM_HUD - CAB - 12]
        self.seq = (self.seq + 1) % 1_000_000_000
        self.mem.seek(0)
        self.mem.write(f"{self.seq:010d}|{len(datos):010d}|".encode("ascii") + datos + f"|{self.seq:010d}".encode("ascii"))

    def cerrar(self):
        if self.mem is not None:
            try:
                self.escribir({"pos": "Ingeniero desconectado|tenue", "delta": "", "delante": "", "detras": "",
                               "coche": "", "msg": "", "msg2": ""})
                self.mem.close()
            except Exception:
                pass
            self.mem = None
