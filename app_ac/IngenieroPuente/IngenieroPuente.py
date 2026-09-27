# -*- coding: utf-8 -*-
"""App de Assetto Corsa: puente con el Ingeniero de carrera + HUD en pantalla.

- Publica los datos de TODOS los coches (posición, vueltas, tiempos, boxes...)
  en la memoria compartida "Local\\IngenieroPuente" para que el programa del
  ingeniero calcule diferencias y rivales (la memoria oficial de AC solo trae
  tu coche).
- Muestra en el juego lo que el ingeniero escribe en "Local\\IngenieroHUD":
  delta, posición, rivales, combustible y el último mensaje de radio.

Se ejecuta con el Python 3.3 que lleva AC: sin f-strings ni librerías externas.
"""
import mmap

import ac
import acsys

APP = "IngenieroPuente"
TAM_PUENTE = 65536
TAM_HUD = 8192
HZ_PUENTE = 20.0
HZ_HUD = 10.0
CAB = 22  # cabecera "%010d|%010d|"

ventana = None
puente = None
hud = None
seq = 0
t_puente = 0.0
t_hud = 0.0
etiquetas = {}

# Colores (r, g, b, a)
BLANCO = (0.93, 0.94, 0.96, 1.0)
TENUE = (0.62, 0.65, 0.72, 1.0)
VERDE = (0.21, 0.82, 0.50, 1.0)
ROJO = (1.0, 0.30, 0.37, 1.0)
AMARILLO = (1.0, 0.79, 0.25, 1.0)
CIAN = (0.24, 0.76, 1.0, 1.0)


def _limpio(txt):
    return str(txt).replace("|", "/").replace("\n", " ")


def _escribir(mem, texto):
    """Formato: seq(10)|largo(10)|datos|seq(10). El lector comprueba que ambos seq coinciden."""
    global seq
    seq = (seq + 1) % 1000000000
    datos = texto.encode("utf-8")
    datos = datos[:TAM_PUENTE - CAB - 12]
    mem.seek(0)
    mem.write(("%010d|%010d|" % (seq, len(datos))).encode("ascii"))
    mem.write(datos)
    mem.write(("|%010d" % seq).encode("ascii"))


def _leer(mem, tam):
    try:
        mem.seek(0)
        cab = mem.read(CAB).decode("ascii", "ignore")
        if len(cab) < CAB or cab[10] != "|":
            return None
        s1, largo = int(cab[0:10]), int(cab[11:21])
        if largo <= 0 or largo > tam - CAB - 11:
            return None
        datos = mem.read(largo)
        fin = mem.read(11).decode("ascii", "ignore")
        if fin[1:] != "%010d" % s1:
            return None
        return datos.decode("utf-8", "ignore")
    except Exception:
        return None


def _datos_coches():
    lineas = []
    try:
        pista = ac.getTrackName(0)
        config = ac.getTrackConfiguration(0)
        longitud = ac.getTrackLength(0)
    except Exception:
        pista, config, longitud = "", "", 0
    n = ac.getCarsCount()
    lineas.append("P|%s|%s|%.1f|%d|%d" % (_limpio(pista), _limpio(config), longitud, n, ac.getFocusedCar()))
    for i in range(n):
        try:
            if not ac.isConnected(i):
                continue
            x, y, z = ac.getCarState(i, acsys.CS.WorldPosition)
            try:
                compuesto = ac.getCarTyreCompound(i)
            except Exception:
                compuesto = ""
            lineas.append("C|%d|%s|%s|%d|%d|%.5f|%d|%d|%d|%d|%.1f|%d|%d|%.1f|%.1f|%s" % (
                i,
                _limpio(ac.getDriverName(i)),
                _limpio(ac.getCarName(i)),
                ac.getCarLeaderboardPosition(i),
                ac.getCarRealTimeLeaderboardPosition(i),
                ac.getCarState(i, acsys.CS.NormalizedSplinePosition),
                ac.getCarState(i, acsys.CS.LapCount),
                ac.getCarState(i, acsys.CS.LastLap),
                ac.getCarState(i, acsys.CS.BestLap),
                ac.getCarState(i, acsys.CS.LapTime),
                ac.getCarState(i, acsys.CS.SpeedKMH),
                1 if ac.isCarInPitline(i) else 0,
                1 if ac.isCarInPit(i) else 0,
                x, z,
                _limpio(compuesto),
            ))
        except Exception as e:
            ac.log("%s: coche %d: %s" % (APP, i, e))
    return "\n".join(lineas)


# ---------------------------------------------------------------- HUD
FILAS = [
    # clave, y, tamaño, alineación
    ("delta", 4, 34, "center"),
    ("pos", 48, 18, "center"),
    ("delante", 74, 17, "left"),
    ("detras", 98, 17, "left"),
    ("coche", 124, 16, "left"),
    ("msg", 150, 15, "left"),
    ("msg2", 170, 15, "left"),
]
ANCHO = 330


def _crear_hud():
    for clave, y, tam, alin in FILAS:
        lab = ac.addLabel(ventana, "")
        ac.setPosition(lab, ANCHO / 2 if alin == "center" else 10, y)
        ac.setFontSize(lab, tam)
        ac.setFontAlignment(lab, alin)
        ac.setFontColor(lab, *BLANCO)
        etiquetas[clave] = lab
    ac.setText(etiquetas["pos"], "Esperando al ingeniero...")
    ac.setFontColor(etiquetas["pos"], *TENUE)


def _color(nombre):
    return {"verde": VERDE, "rojo": ROJO, "amarillo": AMARILLO, "cian": CIAN, "tenue": TENUE}.get(nombre, BLANCO)


def _pintar_hud(texto):
    """Cada línea: clave=texto|color."""
    for linea in texto.split("\n"):
        if "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        if clave not in etiquetas:
            continue
        color = "blanco"
        if "|" in valor:
            valor, color = valor.rsplit("|", 1)
        ac.setText(etiquetas[clave], valor)
        ac.setFontColor(etiquetas[clave], *_color(color))


# ------------------------------------------------------------ ciclo de AC
def acMain(ac_version):
    global ventana, puente, hud
    ventana = ac.newApp(APP)
    ac.setTitle(ventana, "")
    ac.setSize(ventana, ANCHO, 196)
    ac.setIconPosition(ventana, 0, -10000)
    ac.drawBorder(ventana, 0)
    ac.setBackgroundOpacity(ventana, 0.55)
    _crear_hud()
    try:
        puente = mmap.mmap(-1, TAM_PUENTE, "Local\\IngenieroPuente")
        hud = mmap.mmap(-1, TAM_HUD, "Local\\IngenieroHUD")
        ac.log("%s: memoria compartida lista" % APP)
    except Exception as e:
        ac.log("%s: no se pudo crear la memoria compartida: %s" % (APP, e))
    return APP


def acUpdate(delta_t):
    global t_puente, t_hud
    ac.setBackgroundOpacity(ventana, 0.55)  # AC la reinicia al pasar el ratón
    t_puente += delta_t
    t_hud += delta_t
    if puente is not None and t_puente >= 1.0 / HZ_PUENTE:
        t_puente = 0.0
        try:
            _escribir(puente, _datos_coches())
        except Exception as e:
            ac.log("%s: error escribiendo: %s" % (APP, e))
    if hud is not None and t_hud >= 1.0 / HZ_HUD:
        t_hud = 0.0
        texto = _leer(hud, TAM_HUD)
        if texto:
            _pintar_hud(texto)


def acShutdown():
    for m in (puente, hud):
        try:
            if m is not None:
                m.close()
        except Exception:
            pass
