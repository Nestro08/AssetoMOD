"""Radio del ingeniero: síntesis de voz (sale por los altavoces) y
reconocimiento de órdenes por micrófono (offline, con Vosk).

La radio solo habla cuando hay tiempo libre en pista (recta por delante):
el hilo principal actualiza `segundos_libres`/`tranquilo` y la radio espera
a que la frase quepa antes de la siguiente frenada. Lo crítico sale siempre.
"""
import itertools
import json
import logging
import os
import queue
import re
import threading
import time
import zipfile
from dataclasses import dataclass

from . import rutas

log = logging.getLogger(__name__)
MODELO_VOSK = os.path.join(rutas.MODELOS, "vosk-model-small-es-0.42")

# Prioridades: cuanto más bajo, antes se dice.
CRITICO, ALTA, NORMAL, BAJA = 0, 1, 2, 3
# Cuánto puede esperar cada prioridad a que llegue una recta antes de hablar igualmente
ESPERA_MAX = {CRITICO: 0.0, ALTA: 4.0, NORMAL: 1e9, BAJA: 1e9}
CARACTERES_POR_SEGUNDO = 15.0


@dataclass(order=True)
class _Frase:
    prioridad: int
    orden: int
    creada: float
    caduca: float
    texto: str


def duracion(texto):
    return 0.4 + len(texto) / CARACTERES_POR_SEGUNDO


def partir_frases(texto):
    """Divide en frases para poder soltarlas en rectas distintas."""
    partes = re.split(r"(?<=[.!?])\s+", texto.strip())
    return [p for p in partes if p]


class Radio:
    """Cola de frases habladas en un hilo propio, para que la voz no frene la telemetría."""

    def __init__(self, activada=True, pitido=True, motor="sapi", voz_piper=None):
        self.activada = activada
        self.pitido = pitido
        self.silenciada = False  # "silencio": solo avisos críticos
        self.solo_rectas = True
        self.hablando = threading.Event()
        self.estado = "iniciando"
        self.motor = motor
        self.voz_piper = voz_piper
        # Los escribe el hilo principal a cada lectura
        self.segundos_libres = None  # hasta la próxima frenada según la vuelta guía (None = no se sabe)
        self.tranquilo = True  # sin frenar ni girar fuerte ahora mismo
        self.al_hablar = None  # callback(texto) cuando empieza a decir una frase
        self._pendientes = []
        self._cerrojo = threading.Condition()
        self._orden = itertools.count()
        self._cerrar = False
        threading.Thread(target=self._bucle, name="radio", daemon=True).start()

    # ------------------------------------------------------------- entrada
    def decir(self, texto, prioridad=NORMAL, caduca=12.0):
        if not self.activada or not texto:
            return
        if self.silenciada and prioridad > CRITICO:
            return
        ahora = time.monotonic()
        with self._cerrojo:
            if prioridad == CRITICO:  # lo urgente pasa delante de la charla
                self._pendientes = [f for f in self._pendientes if f.prioridad <= ALTA]
            frases = partir_frases(texto)
            for i, frase in enumerate(frases):
                # Las frases de un mismo mensaje caducan más tarde cuanto más atrás van
                self._pendientes.append(_Frase(prioridad, next(self._orden), ahora, ahora + caduca + 6 * i, frase))
            self._pendientes.sort()
            self._cerrojo.notify()

    def pendientes(self):
        return len(self._pendientes)

    def cerrar(self):
        with self._cerrojo:
            self._cerrar = True
            self._cerrojo.notify()

    # ------------------------------------------------------------- motores
    def _crear_voz(self):
        if self.motor == "piper":
            hablar = self._crear_piper()
            if hablar:
                return hablar
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            voz = win32com.client.Dispatch("SAPI.SpVoice")
            for token in voz.GetVoices():
                desc = token.GetDescription()
                if any(k in desc for k in ("Spanish", "Español", "Helena", "Laura", "Pablo", "Sabina")):
                    voz.Voice = token
                    break
            voz.Rate = 1
            self.estado = f"voz: {voz.Voice.GetDescription()}"
            return voz.Speak
        except Exception:
            log.exception("SAPI no disponible")
        try:
            import pyttsx3
            motor = pyttsx3.init()
            self.estado = "voz: pyttsx3"

            def hablar(texto):
                motor.say(texto)
                motor.runAndWait()
            return hablar
        except Exception as e:
            self.estado = f"sin voz ({e})"
            return None

    def _crear_piper(self):
        """Voz neuronal offline (Piper). Mucho más natural que SAPI."""
        try:
            from .voz_neuronal import VozPiper
            voz = VozPiper(self.voz_piper)
            self.estado = f"voz neuronal: {voz.nombre}"
            return voz.hablar
        except Exception as e:
            log.warning("Piper no disponible, uso la voz de Windows: %s", e)
            return None

    # ---------------------------------------------------------- selección
    def _puede_decir(self, f: _Frase, ahora):
        if f.prioridad == CRITICO or not self.solo_rectas:
            return True
        if ahora - f.creada >= ESPERA_MAX[f.prioridad]:
            return True
        if not self.tranquilo:
            return False
        libre = self.segundos_libres
        if libre is None:  # aún no conocemos la pista: nos fiamos de "tranquilo"
            return True
        return libre >= min(duracion(f.texto), 5.0)

    def _siguiente(self):
        """Espera hasta que haya una frase que se pueda decir ahora."""
        with self._cerrojo:
            while not self._cerrar:
                ahora = time.monotonic()
                self._pendientes = [f for f in self._pendientes
                                    if f.caduca > ahora and not (self.silenciada and f.prioridad > CRITICO)]
                if self._pendientes:
                    primera = self._pendientes[0]
                    # Respeta el orden: no se adelanta una frase de otro mensaje del mismo nivel
                    if self._puede_decir(primera, ahora):
                        self._pendientes.pop(0)
                        return primera
                    self._cerrojo.wait(0.1)
                else:
                    self._cerrojo.wait(0.5)
            return None

    def _bucle(self):
        hablar = self._crear_voz()
        try:
            import winsound
        except ImportError:
            winsound = None
        anterior = 0.0
        while True:
            f = self._siguiente()
            if f is None:
                break
            if hablar is None or not self.activada:
                continue
            self.hablando.set()
            try:
                if self.al_hablar:
                    self.al_hablar(f.texto)
                # Un solo pitido por "transmisión", no por cada frase
                if self.pitido and winsound and time.monotonic() - anterior > 2.0:
                    winsound.Beep(1250, 60)
                hablar(f.texto)
            except Exception as e:
                self.estado = f"error de voz: {e}"
                log.exception("Error al hablar")
            anterior = time.monotonic()
            time.sleep(0.25)  # que el eco de la voz no llegue al micrófono
            self.hablando.clear()


# ---------------------------------------------------------------- órdenes
# Palabras clave -> intención. Se evalúan en orden: la primera que coincide gana.
INTENCIONES = [
    ("silencio", ("silencio", "calla", "cállate")),
    ("habla", ("habla",)),
    ("repite", ("repite", "repetir")),
    ("ayuda", ("ayuda",)),
    ("donde_pierdo", ("pierdo",)),
    ("curvas", ("curva", "curvas", "frenada", "pilotaje")),
    ("rivales", ("rivales", "rival", "delante", "detrás", "diferencia", "diferencias")),
    ("combustible", ("combustible", "gasolina", "litros", "repostar")),
    ("frenos", ("frenos", "freno")),
    ("presiones", ("presión", "presiones")),
    ("neumaticos", ("neumáticos", "neumático", "ruedas", "gomas", "desgaste")),
    ("ajustes", ("ajustes", "ajuste", "consejo", "consejos")),
    ("danios", ("daños", "daño", "averías", "mecánica", "coche")),
    ("estrategia", ("estrategia", "parada", "parar", "boxes", "box", "faltan", "falta", "quedan")),
    ("posicion", ("posición", "puesto", "clasificación")),
    ("clima", ("clima", "pista", "temperatura", "asfalto")),
    ("tiempos", ("tiempos", "vuelta", "vueltas", "mejor", "sector", "sectores", "ritmo", "delta", "tiempo")),
    ("resumen", ("resumen", "estado", "ingeniero")),
]
_RELLENO = ["qué", "cuánto", "cómo", "van", "los", "las", "me", "queda", "hay", "el", "la",
            "de", "tengo", "dónde", "dame", "dime", "vamos", "tal", "va", "voy", "quién"]
GRAMATICA = sorted({p for _, ps in INTENCIONES for p in ps} | set(_RELLENO)) + ["[unk]"]


def interpretar(texto):
    palabras = texto.lower().split()
    for intencion, claves in INTENCIONES:
        if any(c in palabras for c in claves):
            return intencion
    return None


class Escucha:
    """Escucha el micrófono y llama a `al_oir(intencion, texto)` con cada orden reconocida.

    `ptt`: función que devuelve True mientras se pulsa el botón de hablar (None = siempre escuchando).
    """

    def __init__(self, radio: Radio, al_oir, ptt=None, dispositivo=None):
        self.radio = radio
        self.al_oir = al_oir
        self.ptt = ptt
        self.dispositivo = dispositivo
        self.estado = "iniciando"
        self.ultimo_texto = ""
        self.activa = True
        self.nivel = 0.0  # volumen del micrófono (0-1), para el indicador
        self._parar = threading.Event()
        threading.Thread(target=self._bucle, name="escucha", daemon=True).start()

    def cerrar(self):
        self._parar.set()

    @staticmethod
    def _preparar_modelo():
        if os.path.isdir(MODELO_VOSK):
            return MODELO_VOSK
        zip_path = MODELO_VOSK + ".zip"
        if os.path.isfile(zip_path):
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(os.path.dirname(MODELO_VOSK))
            return MODELO_VOSK
        return None

    def _bucle(self):
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as e:
            self.estado = f"falta librería: {e.name}"
            return
        self.estado = "preparando modelo de voz..."
        ruta = self._preparar_modelo()
        if not ruta:
            self.estado = "modelo de voz no encontrado"
            return
        SetLogLevel(-1)
        modelo = Model(ruta)
        try:
            frecuencia = int(sd.query_devices(self.dispositivo, kind="input")["default_samplerate"])
        except Exception:
            self.estado = "sin micrófono"
            return
        rec = KaldiRecognizer(modelo, frecuencia, json.dumps(GRAMATICA, ensure_ascii=False))
        audio = queue.Queue()

        def captura(indata, frames, tiempo, status):
            audio.put(bytes(indata))

        try:
            flujo = sd.RawInputStream(samplerate=frecuencia, blocksize=frecuencia // 5, device=self.dispositivo,
                                      dtype="int16", channels=1, callback=captura)
        except Exception as e:
            self.estado = f"error de micrófono: {e}"
            return
        import array
        with flujo:
            pulsada_antes = False
            while not self._parar.is_set():
                self.estado = "escuchando" if self.ptt is None else "mantén el botón para hablar"
                try:
                    datos = audio.get(timeout=0.5)
                except queue.Empty:
                    continue
                muestras = array.array("h", datos)
                if muestras:
                    self.nivel = min(1.0, max(abs(x) for x in muestras[::8]) / 20000)
                if not self.activa or self.radio.hablando.is_set():
                    rec.Reset()  # no queremos oír al propio ingeniero
                    pulsada_antes = False
                    continue
                pulsada = True if self.ptt is None else bool(self.ptt())
                if not pulsada:
                    if pulsada_antes:  # soltó el botón: procesamos lo dicho
                        self._procesar(json.loads(rec.FinalResult()).get("text", ""))
                    pulsada_antes = False
                    continue
                if self.ptt is not None:
                    self.estado = "te escucho..."
                pulsada_antes = True
                if rec.AcceptWaveform(datos):
                    self._procesar(json.loads(rec.Result()).get("text", ""))

    def _procesar(self, texto):
        texto = texto.replace("[unk]", "").strip()
        if not texto:
            return
        intencion = interpretar(texto)
        if intencion:
            self.ultimo_texto = texto
            self.al_oir(intencion, texto)
