"""Botones del volante / mandos y teclas globales (funcionan aunque AC tenga el foco).

Códigos de asignación:
  "J0B5"  -> dispositivo de juego 0, botón 5 (1-32)
  "K7C"   -> tecla virtual 0x7C (F13)
"""
import ctypes
from ctypes import wintypes

_winmm = ctypes.WinDLL("winmm")
_user32 = ctypes.WinDLL("user32")

JOY_RETURNBUTTONS = 0x00000080
MAX_JOY = 16


class JOYINFOEX(ctypes.Structure):
    _fields_ = [(n, wintypes.DWORD) for n in (
        "dwSize", "dwFlags", "dwXpos", "dwYpos", "dwZpos", "dwRpos", "dwUpos", "dwVpos",
        "dwButtons", "dwButtonNumber", "dwPOV", "dwReserved1", "dwReserved2")]


class JOYCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("szPname", wintypes.WCHAR * 32)] + \
               [(n, wintypes.UINT) for n in ("wXmin", "wXmax", "wYmin", "wYmax", "wZmin", "wZmax", "wNumButtons",
                                             "wPeriodMin", "wPeriodMax", "wRmin", "wRmax", "wUmin", "wUmax",
                                             "wVmin", "wVmax", "wCaps", "wMaxAxes", "wNumAxes", "wMaxButtons")] + \
               [("szRegKey", wintypes.WCHAR * 32), ("szOEMVxD", wintypes.WCHAR * 260)]


_winmm.joyGetPosEx.argtypes = [wintypes.UINT, ctypes.POINTER(JOYINFOEX)]
_winmm.joyGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(JOYCAPSW), wintypes.UINT]
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short

NOMBRES_TECLA = {0x20: "Espacio", 0x0D: "Intro", 0x09: "Tab", 0x10: "Mayús", 0x11: "Ctrl", 0x12: "Alt",
                 0x2D: "Insert", 0x2E: "Supr", 0x24: "Inicio", 0x23: "Fin", 0x21: "RePág", 0x22: "AvPág",
                 0x91: "Bloq Despl", 0x13: "Pausa"}


def botones_joystick(i):
    info = JOYINFOEX()
    info.dwSize = ctypes.sizeof(JOYINFOEX)
    info.dwFlags = JOY_RETURNBUTTONS
    if _winmm.joyGetPosEx(i, ctypes.byref(info)) != 0:
        return None
    return info.dwButtons


def dispositivos():
    """[(id, nombre, número de botones)] de los mandos conectados."""
    out = []
    for i in range(MAX_JOY):
        if botones_joystick(i) is None:
            continue
        caps = JOYCAPSW()
        nombre = f"Mando {i}"
        n = 0
        if _winmm.joyGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            nombre, n = caps.szPname or nombre, caps.wNumButtons
        out.append((i, nombre, n))
    return out


def tecla_pulsada(vk):
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def nombre_codigo(codigo):
    if not codigo:
        return "—"
    if codigo.startswith("J"):
        j, b = codigo[1:].split("B")
        return f"Mando {j} · botón {b}"
    if codigo.startswith("K"):
        vk = int(codigo[1:], 16)
        if 0x70 <= vk <= 0x87:
            return f"Tecla F{vk - 0x6F}"
        if 0x60 <= vk <= 0x69:
            return f"Tecla Num {vk - 0x60}"
        if 0x30 <= vk <= 0x5A:
            return f"Tecla {chr(vk)}"
        return f"Tecla {NOMBRES_TECLA.get(vk, hex(vk))}"
    return codigo


def estado_codigo(codigo, cache_joy=None):
    if not codigo:
        return False
    try:
        if codigo.startswith("J"):
            j, b = codigo[1:].split("B")
            j, b = int(j), int(b)
            botones = cache_joy.get(j) if cache_joy is not None and j in cache_joy else botones_joystick(j)
            if cache_joy is not None:
                cache_joy[j] = botones
            return bool(botones and botones & (1 << (b - 1)))
        if codigo.startswith("K"):
            return tecla_pulsada(int(codigo[1:], 16))
    except ValueError:
        return False
    return False


class Mandos:
    """Asignaciones acción -> código. `hablar` es "mantener pulsado"; el resto se dispara al pulsar."""

    def __init__(self, asignaciones=None):
        self.asignaciones = dict(asignaciones or {})
        self._antes = {}
        self._aprendiendo = None  # estado previo mientras se aprende un botón

    def pulsado(self, accion):
        return estado_codigo(self.asignaciones.get(accion))

    def ptt(self):
        """Para la escucha: True si el botón de hablar está pulsado, o None si no hay botón asignado."""
        return self.pulsado("hablar") if self.asignaciones.get("hablar") else None

    def sondear(self):
        """Acciones cuyo botón acaba de pulsarse (flanco de subida)."""
        cache = {}
        disparadas = []
        for accion, codigo in self.asignaciones.items():
            ahora = estado_codigo(codigo, cache)
            if ahora and not self._antes.get(accion) and accion != "hablar":
                disparadas.append(accion)
            self._antes[accion] = ahora
        return disparadas

    # ------------------------------------------------------------ aprender
    def _foto(self):
        joys = {i: botones_joystick(i) for i in range(MAX_JOY)}
        teclas = {vk for vk in range(0x08, 0xFF) if vk not in (0x10, 0x11, 0x12) and tecla_pulsada(vk)}
        return joys, teclas

    def empezar_aprendizaje(self):
        self._aprendiendo = self._foto()

    def aprender(self):
        """Llamar periódicamente tras empezar_aprendizaje(): devuelve el primer botón/tecla nuevo o None."""
        if self._aprendiendo is None:
            return None
        joys0, teclas0 = self._aprendiendo
        joys, teclas = self._foto()
        for i, b in joys.items():
            if b is None:
                continue
            nuevos = b & ~(joys0.get(i) or 0)
            if nuevos:
                self._aprendiendo = None
                return f"J{i}B{(nuevos & -nuevos).bit_length()}"
        for vk in sorted(teclas - teclas0):
            if vk in (0x01, 0x02, 0x04, 0x05, 0x06):  # botones del ratón
                continue
            self._aprendiendo = None
            return f"K{vk:X}"
        # Si se sueltan botones que estaban pulsados, se actualiza la foto
        self._aprendiendo = (joys, teclas & teclas0)
        return None
