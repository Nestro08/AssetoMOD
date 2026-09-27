"""Voz neuronal offline con Piper (mucho más natural que la voz de Windows).

Necesita la librería `piper-tts` y un modelo de voz (.onnx + .onnx.json) en
model/piper/. Los modelos se descargan desde Ajustes, solo si el usuario lo pide.
"""
import glob
import logging
import os
import urllib.request

from . import rutas

log = logging.getLogger(__name__)
CARPETA = os.path.join(rutas.MODELOS, "piper")
BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES"
VOCES = {
    "es_ES-davefx-medium": ("Voz masculina (davefx, calidad media, ~63 MB)", f"{BASE_URL}/davefx/medium/es_ES-davefx-medium"),
    "es_ES-sharvard-medium": ("Voz alternativa (sharvard, calidad media, ~77 MB)",
                              f"{BASE_URL}/sharvard/medium/es_ES-sharvard-medium"),
}


def piper_instalado():
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def modelos_disponibles():
    return sorted(p for p in glob.glob(os.path.join(CARPETA, "*.onnx")) if os.path.isfile(p + ".json"))


def descargar_voz(clave, progreso=None):
    """Descarga el modelo `clave` (de VOCES) a model/piper/. progreso(bytes, total). Devuelve la ruta del .onnx."""
    os.makedirs(CARPETA, exist_ok=True)
    _, url = VOCES[clave]
    destino = os.path.join(CARPETA, clave + ".onnx")
    for sufijo in (".onnx.json", ".onnx"):
        ruta = os.path.join(CARPETA, clave + sufijo)
        tmp = ruta + ".descarga"
        with urllib.request.urlopen(url + sufijo, timeout=30) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            hecho = 0
            while True:
                bloque = r.read(1 << 16)
                if not bloque:
                    break
                f.write(bloque)
                hecho += len(bloque)
                if progreso:
                    progreso(hecho, total)
        os.replace(tmp, ruta)
    return destino


class VozPiper:
    def __init__(self, ruta_modelo=None, velocidad=1.05):
        if ruta_modelo is None or not os.path.isfile(ruta_modelo):
            modelos = modelos_disponibles()
            if not modelos:
                raise FileNotFoundError("No hay ningún modelo de voz Piper en model/piper")
            ruta_modelo = modelos[0]
        from piper import PiperVoice
        self.voz = PiperVoice.load(ruta_modelo)
        self.nombre = os.path.basename(ruta_modelo).replace(".onnx", "")
        self.velocidad = velocidad
        self._config = None
        try:  # piper-tts >= 1.3
            from piper import SynthesisConfig
            self._config = SynthesisConfig(length_scale=1.0 / velocidad)
        except ImportError:
            pass

    def sintetizar(self, texto):
        """Devuelve (muestras int16 como bytes, frecuencia de muestreo)."""
        if hasattr(self.voz, "synthesize_stream_raw"):  # piper-tts 1.2
            datos = b"".join(self.voz.synthesize_stream_raw(texto, length_scale=1.0 / self.velocidad))
            return datos, self.voz.config.sample_rate
        trozos = list(self.voz.synthesize(texto, syn_config=self._config) if self._config else self.voz.synthesize(texto))
        if not trozos:
            return b"", 22050
        return b"".join(t.audio_int16_bytes for t in trozos), trozos[0].sample_rate

    def hablar(self, texto):
        import numpy as np
        import sounddevice as sd
        datos, frecuencia = self.sintetizar(texto)
        if datos:
            sd.play(np.frombuffer(datos, dtype=np.int16), frecuencia)
            sd.wait()
