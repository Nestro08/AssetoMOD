"""Instala la app IngenieroPuente dentro de Assetto Corsa y la deja activada."""
import configparser
import os
import re
import shutil
import winreg

from . import rutas

NOMBRE_APP = "IngenieroPuente"


def _bibliotecas_steam():
    raices = []
    for clave, valor in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                         (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
        try:
            with winreg.OpenKey(clave, valor) as k:
                for nombre in ("SteamPath", "InstallPath"):
                    try:
                        raices.append(winreg.QueryValueEx(k, nombre)[0])
                    except OSError:
                        pass
        except OSError:
            pass
    bibliotecas = []
    for raiz in raices:
        raiz = os.path.normpath(raiz)
        bibliotecas.append(raiz)
        vdf = os.path.join(raiz, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            with open(vdf, encoding="utf-8", errors="ignore") as f:
                for ruta in re.findall(r'"path"\s+"([^"]+)"', f.read()):
                    bibliotecas.append(os.path.normpath(ruta.replace("\\\\", "\\")))
    vistas = []
    for b in bibliotecas:
        if b.lower() not in (v.lower() for v in vistas):
            vistas.append(b)
    return vistas


def buscar_ac():
    """Carpeta de instalación de Assetto Corsa o None."""
    candidatas = [os.path.join(b, "steamapps", "common", "assettocorsa") for b in _bibliotecas_steam()]
    candidatas += [r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa",
                   r"D:\SteamLibrary\steamapps\common\assettocorsa"]
    for c in candidatas:
        if os.path.isfile(os.path.join(c, "acs.exe")) or os.path.isdir(os.path.join(c, "apps", "python")):
            return c
    return None


def carpeta_documentos_ac():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
            docs = winreg.QueryValueEx(k, "Personal")[0]
    except OSError:
        docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs, "Assetto Corsa")


def instalada(ac=None):
    ac = ac or buscar_ac()
    return bool(ac) and os.path.isfile(os.path.join(ac, "apps", "python", NOMBRE_APP, NOMBRE_APP + ".py"))


def instalar(ac=None):
    """Copia la app y la activa. Devuelve (ok, mensaje)."""
    ac = ac or buscar_ac()
    if not ac:
        return False, "No encuentro Assetto Corsa. Copia a mano la carpeta app_ac\\IngenieroPuente en <AC>\\apps\\python\\"
    origen = os.path.join(rutas.APP_AC, NOMBRE_APP)
    destino = os.path.join(ac, "apps", "python", NOMBRE_APP)
    os.makedirs(destino, exist_ok=True)
    shutil.copy2(os.path.join(origen, NOMBRE_APP + ".py"), os.path.join(destino, NOMBRE_APP + ".py"))

    # Activarla en cfg/python.ini (lo leen AC y Content Manager)
    activada = False
    ini = os.path.join(carpeta_documentos_ac(), "cfg", "python.ini")
    if os.path.isdir(os.path.dirname(ini)):
        cp = configparser.ConfigParser()
        cp.optionxform = str
        if os.path.isfile(ini):
            cp.read(ini, encoding="utf-8")
        seccion = NOMBRE_APP.upper()
        if not cp.has_section(seccion):
            cp.add_section(seccion)
        cp.set(seccion, "ACTIVE", "1")
        with open(ini, "w", encoding="utf-8") as f:
            cp.write(f, space_around_delimiters=False)
        activada = True
    msg = f"App instalada en {destino}."
    msg += " Activada en python.ini." if activada else \
        " Actívala en AC: Opciones > General > UI Modules > IngenieroPuente."
    msg += " En pista, ábrela desde la barra de apps de la derecha para ver el HUD."
    return True, msg


if __name__ == "__main__":
    print(instalar()[1])
