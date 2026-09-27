"""Guarda y carga la configuración en datos/ajustes.json."""
import json
import logging
import os

from . import rutas
from .config import Config

log = logging.getLogger(__name__)


def cargar(config: Config):
    if os.path.isfile(rutas.AJUSTES):
        try:
            with open(rutas.AJUSTES, encoding="utf-8") as f:
                config.cargar_dict(json.load(f))
        except Exception:
            log.exception("Ajustes dañados, uso los valores por defecto")
    return config


def guardar(config: Config):
    rutas.asegurar()

    def escribir(p):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(config.a_dict(), f, ensure_ascii=False, indent=2)
    rutas.escribir_atomico(rutas.AJUSTES, escribir)
