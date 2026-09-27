"""Ventana de ajustes."""
import threading

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
                             QWidget)

from . import ajustes, instalar_ac, voz_neuronal
from .config import PERFILES, perfil_para_coche
from .ingeniero import nombre_coche
from .mandos import Mandos, dispositivos, nombre_codigo
from .voz import ALTA

ACCIONES_BOTONES = [
    ("hablar", "Hablar con el ingeniero (mantener pulsado)"), ("combustible", "Combustible"),
    ("neumaticos", "Neumáticos"), ("estrategia", "Estrategia"), ("rivales", "Rivales"), ("tiempos", "Tiempos"),
    ("curvas", "Curvas"), ("presiones", "Presiones"), ("resumen", "Resumen"), ("repite", "Repetir lo último"),
    ("silencio", "Silenciar / volver a hablar"),
]
CAMPOS_PERFIL = [("temp_neum_min", "Neumático: temperatura mínima", "°C", 20, 150),
                 ("temp_neum_max", "Neumático: temperatura máxima", "°C", 20, 150),
                 ("psi_min", "Presión en caliente mínima", "psi", 5, 60),
                 ("psi_max", "Presión en caliente máxima", "psi", 5, 60),
                 ("temp_freno_min", "Frenos: temperatura mínima", "°C", 0, 1500),
                 ("temp_freno_max", "Frenos: temperatura máxima", "°C", 0, 1500)]


def _nota(texto):
    lbl = QLabel(texto)
    lbl.setObjectName("tenue")
    lbl.setWordWrap(True)
    return lbl


class DialogoAjustes(QDialog):
    def __init__(self, app, padre=None):
        super().__init__(padre)
        self.app = app
        self.cfg = app.config
        self.setWindowTitle("Ajustes")
        self.resize(940, 640)
        self.botones = dict(self.cfg.botones)
        self._aprendiendo = None
        self._mandos_aprender = Mandos()
        self._descarga = None  # (hecho, total, error, terminado)

        lay = QVBoxLayout(self)
        self.pestanas = QTabWidget()
        lay.addWidget(self.pestanas, 1)
        self.pestanas.addTab(self._general(), "General")
        self.pestanas.addTab(self._voz(), "Voz y micrófono")
        self.pestanas.addTab(self._mandos(), "Botones del volante")
        self.pestanas.addTab(self._perfil(), "Perfil del coche")
        self.pestanas.addTab(self._integraciones(), "HUD, web y AC")

        pie = QHBoxLayout()
        pie.addWidget(_nota("Algunos cambios (motor de voz, micrófono, web, HUD) se aplican al reiniciar el programa."), 1)
        guardar = QPushButton("Guardar")
        guardar.clicked.connect(self.guardar)
        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(self.close)
        pie.addWidget(guardar)
        pie.addWidget(cerrar)
        lay.addLayout(pie)

        self._t = QTimer(self)
        self._t.timeout.connect(self._sondear)
        self._t.start(40)

    # ------------------------------------------------------------ pestañas
    def _general(self):
        w = QWidget()
        f = QFormLayout(w)
        self.verbosidad = QComboBox()
        self.verbosidad.addItems(["Solo lo crítico", "Normal", "Muy hablador"])
        self.verbosidad.setCurrentIndex(self.cfg.verbosidad)
        f.addRow("Cuánto habla el ingeniero", self.verbosidad)
        self.rectas = QCheckBox("Hablar solo en las rectas (lo urgente sale siempre)")
        self.rectas.setChecked(self.cfg.hablar_solo_en_rectas)
        f.addRow(self.rectas)
        self.coaching = QCheckBox("Consejos curva a curva al terminar cada vuelta")
        self.coaching.setChecked(self.cfg.coaching_curvas)
        f.addRow(self.coaching)
        self.pitido = QCheckBox("Pitido de radio antes de cada mensaje")
        self.pitido.setChecked(self.cfg.pitido_radio)
        f.addRow(self.pitido)
        self.delta = QComboBox()
        self.delta.addItem("Mejor vuelta de la sesión", "sesion")
        self.delta.addItem("Récord guardado (referencia)", "referencia")
        self.delta.setCurrentIndex(0 if self.cfg.modo_delta == "sesion" else 1)
        f.addRow("Delta contra", self.delta)
        self.perfil = QComboBox()
        self.perfil.addItem("Automático según el coche", None)
        for clave, p in PERFILES.items():
            self.perfil.addItem(p.nombre, clave)
        self.perfil.setCurrentIndex(max(0, self.perfil.findData(self.cfg.perfil_forzado)))
        f.addRow("Tipo de coche", self.perfil)
        self.margen = QDoubleSpinBox()
        self.margen.setRange(0, 5)
        self.margen.setSingleStep(0.5)
        self.margen.setSuffix(" vueltas")
        self.margen.setValue(self.cfg.margen_vueltas_combustible)
        f.addRow("Margen de combustible", self.margen)
        return w

    def _voz(self):
        w = QWidget()
        f = QFormLayout(w)
        self.voz_on = QCheckBox("El ingeniero habla")
        self.voz_on.setChecked(self.cfg.voz_activada)
        f.addRow(self.voz_on)
        self.motor = QComboBox()
        self.motor.addItem("Voz de Windows (SAPI)", "sapi")
        self.motor.addItem("Voz neuronal offline (Piper) — más natural", "piper")
        self.motor.setCurrentIndex(1 if self.cfg.motor_voz == "piper" else 0)
        f.addRow("Motor de voz", self.motor)
        self.modelo = QComboBox()
        self._llenar_modelos()
        f.addRow("Voz neuronal", self.modelo)
        estado = "instalada" if voz_neuronal.piper_instalado() else \
            "NO instalada (hace falta la librería piper-tts en el entorno)"
        f.addRow(_nota(f"Librería Piper: {estado}."))

        fila = QHBoxLayout()
        self.voz_descarga = QComboBox()
        for clave, (desc, _) in voz_neuronal.VOCES.items():
            self.voz_descarga.addItem(desc, clave)
        self.btn_descargar = QPushButton("Descargar voz")
        self.btn_descargar.clicked.connect(self._descargar)
        fila.addWidget(self.voz_descarga, 1)
        fila.addWidget(self.btn_descargar)
        f.addRow("Descargar (HuggingFace)", fila)
        self.progreso = QProgressBar()
        self.progreso.setRange(0, 100)
        self.progreso.setVisible(False)
        f.addRow(self.progreso)
        probar = QPushButton("Probar la voz actual")
        probar.clicked.connect(lambda: self.app.radio.decir(
            "Radio comprobada. Te oigo alto y claro. Vuelta rápida, 1 34 con 2.", ALTA))
        f.addRow(probar)

        self.micro_on = QCheckBox("Escuchar órdenes por micrófono")
        self.micro_on.setChecked(self.cfg.reconocimiento_activado)
        f.addRow(self.micro_on)
        self.micro = QComboBox()
        self.micro.addItem("Micrófono predeterminado de Windows", None)
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0 and d["hostapi"] == 0:
                    self.micro.addItem(d["name"], i)
        except Exception:
            pass
        self.micro.setCurrentIndex(max(0, self.micro.findData(self.cfg.dispositivo_micro)))
        f.addRow("Micrófono", self.micro)
        return w

    def _llenar_modelos(self):
        self.modelo.clear()
        modelos = voz_neuronal.modelos_disponibles()
        if not modelos:
            self.modelo.addItem("(ninguna descargada)", None)
        for m in modelos:
            self.modelo.addItem(m.split("\\")[-1].replace(".onnx", ""), m)
        self.modelo.setCurrentIndex(max(0, self.modelo.findData(self.cfg.voz_piper)))

    def _mandos(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        conectados = dispositivos()
        lay.addWidget(_nota("Mandos detectados: " + (", ".join(f"{n} (ID {i})" for i, n, _ in conectados) or "ninguno") +
                            ". Pulsa «Asignar» y después el botón del volante (o una tecla). Funcionan aunque AC tenga el foco."))
        f = QFormLayout()
        self.etiquetas_boton = {}
        for accion, texto in ACCIONES_BOTONES:
            fila = QHBoxLayout()
            lbl = QLabel(nombre_codigo(self.botones.get(accion)))
            lbl.setMinimumWidth(170)
            asignar = QPushButton("Asignar")
            asignar.clicked.connect(lambda _, a=accion: self._empezar_asignar(a))
            quitar = QPushButton("Quitar")
            quitar.clicked.connect(lambda _, a=accion: self._quitar(a))
            fila.addWidget(lbl)
            fila.addWidget(asignar)
            fila.addWidget(quitar)
            fila.addStretch(1)
            self.etiquetas_boton[accion] = lbl
            f.addRow(texto, fila)
        lay.addLayout(f)
        self.aviso_asignar = QLabel()
        self.aviso_asignar.setStyleSheet("color: #ffc940; font-weight: bold;")
        lay.addWidget(self.aviso_asignar)
        lay.addStretch(1)
        return w

    def _perfil(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        s = self.app.analizador.snap
        self.coche = s.static.carModel if s else None
        if not self.coche:
            lay.addWidget(_nota("Entra en pista con el coche para poder ajustar su perfil."))
            lay.addStretch(1)
            return w
        actual = self.app.analizador.perfil
        propio = self.coche in self.cfg.perfiles_personalizados
        lay.addWidget(QLabel(f"<b>{nombre_coche(self.coche)}</b> — ahora usa: {actual.nombre}"
                             + (" (personalizado)" if propio else "")))
        lay.addWidget(_nota("Las ventanas óptimas dependen del coche y del compuesto. Si sabes en qué rango trabaja "
                            "tu coche, ajústalo aquí: el ingeniero lo recordará para este coche."))
        f = QFormLayout()
        self.campos_perfil = {}
        for campo, texto, unidad, lo, hi in CAMPOS_PERFIL:
            sb = QDoubleSpinBox()
            sb.setRange(lo, hi)
            sb.setDecimals(1)
            sb.setSuffix(f" {unidad}")
            sb.setValue(getattr(actual, campo))
            self.campos_perfil[campo] = sb
            f.addRow(texto, sb)
        lay.addLayout(f)
        fila = QHBoxLayout()
        guardar = QPushButton("Usar estos valores para este coche")
        guardar.clicked.connect(self._guardar_perfil)
        auto = QPushButton("Volver al perfil automático")
        auto.clicked.connect(self._perfil_auto)
        fila.addWidget(guardar)
        fila.addWidget(auto)
        fila.addStretch(1)
        lay.addLayout(fila)
        lay.addStretch(1)
        return w

    def _integraciones(self):
        w = QWidget()
        f = QFormLayout(w)
        self.hud = QCheckBox("Mostrar el HUD del ingeniero dentro de AC (necesita la app IngenieroPuente)")
        self.hud.setChecked(self.cfg.hud_en_juego)
        f.addRow(self.hud)
        ac = instalar_ac.buscar_ac()
        estado = "no encuentro AC" if not ac else ("instalada" if instalar_ac.instalada(ac) else "no instalada")
        fila = QHBoxLayout()
        fila.addWidget(QLabel(f"App de AC: {estado}"))
        inst = QPushButton("Instalar / actualizar")
        inst.clicked.connect(self._instalar)
        fila.addWidget(inst)
        fila.addStretch(1)
        f.addRow(fila)

        self.web = QCheckBox("Panel web para móvil/tablet e ingeniero remoto (red local)")
        self.web.setChecked(self.cfg.web_activada)
        f.addRow(self.web)
        self.puerto = QSpinBox()
        self.puerto.setRange(1024, 65535)
        self.puerto.setValue(self.cfg.web_puerto)
        f.addRow("Puerto", self.puerto)
        self.pin = QLineEdit(self.cfg.web_pin)
        self.pin.setMaxLength(12)
        self.pin.setPlaceholderText("se genera al activar el panel")
        f.addRow("PIN", self.pin)
        web = getattr(self.app, "web", None)
        if web is not None and web.servidor:
            urls = "  ·  ".join(f"{u}/?pin={web.pin}" for u in web.urls())
            lbl = QLabel(f"Abre en el móvil: <b>{urls}</b>")
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            f.addRow(lbl)
        elif web is not None and web.error:
            f.addRow(_nota(web.error))
        f.addRow(_nota("La primera vez Windows preguntará si permites el acceso en red: acepta solo «redes privadas». "
                       "Cualquiera con el PIN en tu red puede ver los datos y hablarle al piloto."))
        return w

    # ---------------------------------------------------------------- acciones
    def _empezar_asignar(self, accion):
        self._aprendiendo = (accion, 0)
        self._mandos_aprender.empezar_aprendizaje()
        self.aviso_asignar.setText(f"Pulsa ahora el botón o la tecla para «{dict(ACCIONES_BOTONES)[accion]}»…")

    def _quitar(self, accion):
        self.botones.pop(accion, None)
        self.etiquetas_boton[accion].setText("—")

    def _sondear(self):
        if self._aprendiendo:
            accion, ticks = self._aprendiendo
            codigo = self._mandos_aprender.aprender()
            if codigo:
                self.botones[accion] = codigo
                self.etiquetas_boton[accion].setText(nombre_codigo(codigo))
                self.aviso_asignar.setText(f"Asignado: {nombre_codigo(codigo)}")
                self._aprendiendo = None
            elif ticks > 250:  # 10 s
                self.aviso_asignar.setText("No se ha pulsado nada. Vuelve a intentarlo.")
                self._aprendiendo = None
            else:
                self._aprendiendo = (accion, ticks + 1)
        if self._descarga:
            hecho, total, error, terminado = self._descarga
            if total:
                self.progreso.setValue(int(hecho * 100 / total))
            if terminado:
                self._descarga = None
                self.progreso.setVisible(False)
                self.btn_descargar.setEnabled(True)
                if error:
                    QMessageBox.warning(self, "Voz", f"No se pudo descargar: {error}")
                else:
                    self._llenar_modelos()
                    self.motor.setCurrentIndex(1)
                    QMessageBox.information(self, "Voz", "Voz descargada. Guarda y reinicia el programa para usarla.")

    def _descargar(self):
        clave = self.voz_descarga.currentData()
        desc = voz_neuronal.VOCES[clave][0]
        r = QMessageBox.question(self, "Descargar voz",
                                 f"Se descargará {desc} desde huggingface.co/rhasspy/piper-voices a la carpeta model/piper.\n\n¿Continuar?")
        if r != QMessageBox.Yes:
            return
        self._descarga = (0, 0, None, False)
        self.progreso.setVisible(True)
        self.btn_descargar.setEnabled(False)

        def trabajo():
            try:
                voz_neuronal.descargar_voz(clave, lambda h, t: setattr(self, "_descarga", (h, t, None, False)))
                self._descarga = (1, 1, None, True)
            except Exception as e:
                self._descarga = (0, 0, str(e), True)
        threading.Thread(target=trabajo, daemon=True).start()

    def _guardar_perfil(self):
        valores = {campo: sb.value() for campo, sb in self.campos_perfil.items()}
        if valores["temp_neum_min"] >= valores["temp_neum_max"] or valores["psi_min"] >= valores["psi_max"]:
            QMessageBox.warning(self, "Perfil", "El mínimo tiene que ser menor que el máximo.")
            return
        valores["nombre"] = f"Personalizado ({nombre_coche(self.coche)})"
        self.cfg.perfiles_personalizados = dict(self.cfg.perfiles_personalizados, **{self.coche: valores})
        self.app.analizador.perfil = perfil_para_coche(self.coche, self.cfg.perfil_forzado, self.cfg.perfiles_personalizados)
        ajustes.guardar(self.cfg)
        QMessageBox.information(self, "Perfil", "Perfil guardado para este coche.")

    def _perfil_auto(self):
        personalizados = dict(self.cfg.perfiles_personalizados)
        personalizados.pop(self.coche, None)
        self.cfg.perfiles_personalizados = personalizados
        self.app.analizador.perfil = perfil_para_coche(self.coche, self.cfg.perfil_forzado, personalizados)
        ajustes.guardar(self.cfg)
        actual = self.app.analizador.perfil
        for campo, sb in self.campos_perfil.items():
            sb.setValue(getattr(actual, campo))

    def _instalar(self):
        ok, msg = instalar_ac.instalar()
        (QMessageBox.information if ok else QMessageBox.warning)(self, "App de AC", msg)

    def guardar(self):
        c = self.cfg
        c.verbosidad = self.verbosidad.currentIndex()
        c.hablar_solo_en_rectas = self.rectas.isChecked()
        c.coaching_curvas = self.coaching.isChecked()
        c.pitido_radio = self.pitido.isChecked()
        c.modo_delta = self.delta.currentData()
        c.perfil_forzado = self.perfil.currentData()
        c.margen_vueltas_combustible = self.margen.value()
        c.voz_activada = self.voz_on.isChecked()
        c.motor_voz = self.motor.currentData()
        c.voz_piper = self.modelo.currentData()
        c.reconocimiento_activado = self.micro_on.isChecked()
        c.dispositivo_micro = self.micro.currentData()
        c.botones = dict(self.botones)
        c.hud_en_juego = self.hud.isChecked()
        c.web_activada = self.web.isChecked()
        c.web_puerto = self.puerto.value()
        c.web_pin = self.pin.text().strip()
        ajustes.guardar(c)
        # Lo que se puede aplicar en caliente
        app = self.app
        app.radio.solo_rectas = c.hablar_solo_en_rectas
        app.radio.pitido = c.pitido_radio
        app.radio.activada = c.voz_activada
        app.mandos.asignaciones = dict(c.botones)
        if app.escucha is not None:
            app.escucha.ptt = (lambda: app.mandos.pulsado("hablar")) if c.botones.get("hablar") else None
        s = app.analizador.snap
        if s is not None:
            app.analizador.perfil = perfil_para_coche(s.static.carModel, c.perfil_forzado, c.perfiles_personalizados)
        QMessageBox.information(self, "Ajustes", "Ajustes guardados.")
