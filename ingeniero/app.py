"""Núcleo de la aplicación (sin interfaz): une fuente de datos, analizador,
rivales, ingeniero, voz, mandos, HUD del juego y grabación."""
import logging
import queue
import textwrap
import time

from . import memoria_ac as mac
from .analisis import Analizador
from .config import Config
from .grabador import Grabador
from .ingeniero import Ingeniero, apellido, fmt_delta, fmt_tiempo
from .mandos import Mandos
from .puente import EscritorHUD, LectorPuente
from .rivales import Clasificacion
from .voz import Escucha, Radio

log = logging.getLogger(__name__)
ACCIONES = ("combustible", "neumaticos", "frenos", "tiempos", "estrategia", "ajustes", "donde_pierdo", "resumen",
            "repite", "rivales", "posicion", "curvas", "presiones", "silencio", "habla")


class Aplicacion:
    def __init__(self, fuente, config: Config, puente=None):
        self.config = config
        self.fuente = fuente
        self.analizador = Analizador(config)
        self.clasificacion = Clasificacion()
        # Datos de todos los coches: la demo los simula; en AC los da la app IngenieroPuente
        self.puente = puente if puente is not None else LectorPuente()
        self._leer_puente = getattr(self.puente, "leer_puente", None) or self.puente.leer
        self.radio = Radio(activada=config.voz_activada, pitido=config.pitido_radio,
                           motor=config.motor_voz, voz_piper=config.voz_piper)
        self.radio.solo_rectas = config.hablar_solo_en_rectas
        self.radio.al_hablar = self._al_hablar
        self.ingeniero = Ingeniero(self.analizador, self.radio, config, rivales=self.clasificacion)
        self.grabador = Grabador(self.analizador, config.hz_grabacion)
        self.mandos = Mandos(config.botones)
        self.hud = EscritorHUD() if config.hud_en_juego else None
        self.ordenes = queue.Queue()
        self.extensiones = []  # módulos que reciben tick(): base de datos, estrategia, web...
        self.escucha = None
        if config.reconocimiento_activado:
            ptt = (lambda: self.mandos.pulsado("hablar")) if config.botones.get("hablar") else None
            self.escucha = Escucha(self.radio, lambda i, t: self.ordenes.put((i, t)), ptt=ptt,
                                   dispositivo=config.dispositivo_micro)
        self._t_lento = 0.0
        self._hud_msg = ("", 0.0)

    # ------------------------------------------------------------------ bucle
    def tick(self):
        snap = self.fuente.leer()
        if snap is None:
            self.analizador.desconectado()
        else:
            self.analizador.actualizar(snap)
            self.grabador.registrar(snap)
        self._repartir(self.analizador.extraer_eventos())

        ahora = time.monotonic()
        if ahora - self._t_lento >= 0.1:  # tareas a 10 Hz
            self._t_lento = ahora
            self._rivales(snap)
            self._ventana_radio(snap)
            self.ingeniero.revisar()
            if self.hud:
                try:
                    self.hud.escribir(self.lineas_hud())
                except Exception:
                    log.exception("Error escribiendo el HUD")
        for ext in self.extensiones:
            try:
                ext.tick()
            except Exception:
                log.exception("Error en %s", type(ext).__name__)

        for accion in self.mandos.sondear():
            self.accion(accion)
        while True:
            try:
                intencion, texto = self.ordenes.get_nowait()
            except queue.Empty:
                break
            self.ingeniero.responder(intencion, texto)

    def _repartir(self, eventos):
        """Las extensiones ven los eventos primero y pueden completarlos (p. ej. análisis de curvas de la vuelta)."""
        if not eventos:
            return
        for ext in self.extensiones:
            if hasattr(ext, "eventos"):
                try:
                    ext.eventos(eventos)
                except Exception:
                    log.exception("Error en %s con los eventos", type(ext).__name__)
        self.ingeniero.procesar(eventos)

    def _rivales(self, snap):
        datos = self._leer_puente()
        carrera = snap is not None and snap.graphics.session == mac.SESION_CARRERA
        self.clasificacion.actualizar(datos, carrera)
        self.ingeniero.procesar(self.clasificacion.extraer_eventos())

    def _ventana_radio(self, snap):
        """Le dice a la radio cuánto tiempo libre hay antes de la próxima frenada."""
        r = self.radio
        if snap is None or snap.graphics.status != mac.STATUS_LIVE:
            r.segundos_libres, r.tranquilo = 99.0, True
            return
        ph, gr = snap.physics, snap.graphics
        if ph.speedKmh < 40 or gr.isInPitLane:
            r.segundos_libres, r.tranquilo = 99.0, True
            return
        r.tranquilo = ph.brake < 0.1 and abs(ph.accG[0]) < 1.1
        r.segundos_libres = self.analizador.segundos_libres()

    def accion(self, nombre):
        """Acción de un botón del volante o de la interfaz."""
        if nombre == "silencio":
            self.ingeniero.responder("habla" if self.radio.silenciada else "silencio")
        elif nombre in ACCIONES:
            self.ingeniero.responder(nombre)

    def _al_hablar(self, texto):
        self._hud_msg = (texto, time.monotonic())

    # -------------------------------------------------------------------- HUD
    def delta_actual(self):
        a = self.analizador
        if self.config.modo_delta == "referencia" and a.delta_ref_ms is not None:
            return a.delta_ref_ms
        return a.delta_ms

    def lineas_hud(self):
        a, c = self.analizador, self.clasificacion
        s = a.snap
        vacio = {"delta": "", "pos": "", "delante": "", "detras": "", "coche": "", "msg": "", "msg2": ""}
        if s is None:
            vacio["pos"] = "Ingeniero: esperando datos...|tenue"
            return vacio
        g, ph = s.graphics, s.physics
        lineas = dict(vacio)
        d = self.delta_actual()
        lineas["delta"] = "--.--|tenue" if d is None else f"{fmt_delta(d)}|{'verde' if d < 0 else 'rojo'}"
        pos = c.jugador.pos if c.activa and c.jugador else g.position
        total = len(c.orden) if c.activa else s.static.numCars
        vuelta = f"{g.completedLaps + 1}" + (f"/{g.numberOfLaps}" if g.numberOfLaps else "")
        lineas["pos"] = f"P{pos}/{total}   V{vuelta}   Ult {fmt_tiempo(g.iLastTime)}"
        if c.activa and c.jugador:
            delante, detras = c.cercanos()
            if delante is not None:
                gd = c.gap_con(delante)
                if gd is not None:
                    tend = "" if delante.tendencia is None else f" ({delante.tendencia:+.1f})"
                    lineas["delante"] = f"DEL  {apellido(delante.nombre)[:14]}  +{gd:.2f}{tend}|" + \
                                        ("amarillo" if gd < 1 else "blanco")
            if detras is not None:
                gt = c.gap_con(detras)
                if gt is not None:
                    tend = "" if detras.tendencia is None else f" ({detras.tendencia:+.1f})"
                    lineas["detras"] = f"DET  {apellido(detras.nombre)[:14]}  -{abs(gt):.2f}{tend}|" + \
                                       ("rojo" if abs(gt) < 1 else "blanco")
        partes = []
        if a.vueltas_con_combustible is not None:
            partes.append(f"Comb {a.vueltas_con_combustible:.1f}v ({ph.fuel:.1f}L)")
        else:
            partes.append(f"Comb {ph.fuel:.1f}L")
        partes.append(f"Neum {min(ph.tyreWear):.0f}%")
        if a.combustible_sobra is not None and a.combustible_sobra < 0:
            partes.append(f"FALTAN {-a.combustible_sobra:.1f}L")
        lineas["coche"] = "   ".join(partes) + ("|rojo" if a.combustible_sobra is not None and a.combustible_sobra < 0 else "")
        texto, t = self._hud_msg
        if texto and time.monotonic() - t < 10:
            trozos = textwrap.wrap(texto, 44)
            lineas["msg"] = trozos[0] + "|cian"
            lineas["msg2"] = (" ".join(trozos[1:])[:46] + "|cian") if len(trozos) > 1 else ""
        return lineas

    # ------------------------------------------------------------------ cierre
    def cerrar(self):
        for ext in self.extensiones:
            try:
                ext.cerrar()
            except Exception:
                log.exception("Error cerrando %s", type(ext).__name__)
        if self.escucha:
            self.escucha.cerrar()
        self.radio.cerrar()
        if self.hud:
            self.hud.cerrar()
        self.fuente.cerrar()
        if self.puente is not self.fuente and hasattr(self.puente, "cerrar"):
            self.puente.cerrar()
        return self.grabador.guardar()
