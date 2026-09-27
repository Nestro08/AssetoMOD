"""Monta la aplicación completa con todas sus extensiones."""
import logging

from .app import Aplicacion
from .config import Config

log = logging.getLogger(__name__)


def crear_aplicacion(config: Config, demo=False, vueltas=15, velocidad=1.0, parada_demo=None):
    if demo:
        from .demo import SimuladorDemo
        fuente = SimuladorDemo(vueltas=vueltas, velocidad=velocidad, parada=parada_demo)
        puente = fuente
    else:
        from .memoria_ac import LectorAC
        fuente, puente = LectorAC(), None
    app = Aplicacion(fuente, config, puente=puente)
    for nombre, cargar in _EXTENSIONES:
        try:
            ext = cargar(app)
            if ext is not None:
                app.extensiones.append(ext)
        except Exception:
            log.exception("No se pudo cargar la extensión %s", nombre)
    return app


def _curvas(app):
    from .curvas import ExtCurvas
    return ExtCurvas(app)


def _base_datos(app):
    from .base_datos import ExtBaseDatos
    return ExtBaseDatos(app)


def _estrategia(app):
    from .estrategia import ExtEstrategia
    return ExtEstrategia(app)


# Orden importante: las curvas analizan la vuelta contra la referencia ANTES de que la base de datos
# la sustituya si la vuelta es un récord.
def _web(app):
    if not app.config.web_activada:
        return None
    from .web import ExtWeb
    return ExtWeb(app)


_EXTENSIONES = [("curvas", _curvas), ("base de datos", _base_datos), ("estrategia", _estrategia), ("web", _web)]
