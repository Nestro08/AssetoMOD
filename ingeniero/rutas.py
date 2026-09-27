"""Carpetas del programa (funciona igual ejecutando con Python o como .exe)."""
import os
import sys

if getattr(sys, "frozen", False):  # empaquetado con PyInstaller
    RAIZ = os.path.dirname(sys.executable)
else:
    RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATOS = os.path.join(RAIZ, "datos")
SESIONES = os.path.join(RAIZ, "sesiones")
MODELOS = os.path.join(RAIZ, "model")
APP_AC = os.path.join(RAIZ, "app_ac")
BASE_DATOS = os.path.join(DATOS, "ingeniero.db")
AJUSTES = os.path.join(DATOS, "ajustes.json")
REGISTRO = os.path.join(DATOS, "ingeniero.log")


def asegurar():
    for d in (DATOS, SESIONES):
        os.makedirs(d, exist_ok=True)


def escribir_atomico(ruta, escribir):
    """Escribe en un temporal y lo renombra: si el programa se cierra a medias, el archivo anterior sigue intacto."""
    raiz, ext = os.path.splitext(ruta)
    tmp = raiz + ".tmp" + ext  # algunas librerías exigen la extensión correcta
    escribir(tmp)
    os.replace(tmp, ruta)
