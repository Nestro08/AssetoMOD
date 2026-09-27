"""Ventana principal."""
import html
import logging
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QKeySequence
from PyQt5.QtWidgets import (QAbstractItemView, QAction, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QHeaderView,
                             QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton, QShortcut, QTableWidget,
                             QTableWidgetItem, QTextBrowser, QToolBar, QVBoxLayout, QWidget)

from . import instalar_ac
from .app import Aplicacion
from .ingeniero import fmt_delta, fmt_tiempo
from .voz import ALTA, CRITICO
from .widgets import (C, Cabecera, Coche, Combustible, GMetro, Mapa, Motor, Neumaticos, Panel, Pedales, Tiempos,
                      Trazas)

log = logging.getLogger(__name__)

ESTILO = f"""
QMainWindow, QWidget#raiz, QDialog {{ background: {C['fondo'].name()}; }}
QLabel {{ color: {C['texto'].name()}; font-family: 'Segoe UI'; font-size: 12px; }}
QLabel#tenue {{ color: {C['tenue'].name()}; }}
QLabel#titulo {{ color: {C['tenue'].name()}; font-weight: bold; font-size: 11px; }}
QPushButton {{
    background: #1f2430; color: {C['texto'].name()}; border: 1px solid {C['borde'].name()};
    border-radius: 6px; padding: 6px 8px; font-family: 'Segoe UI'; font-size: 12px;
}}
QPushButton:hover {{ background: #283042; border-color: {C['cian'].name()}; }}
QPushButton:pressed {{ background: {C['cian'].name()}; color: #000; }}
QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QRadioButton, QGroupBox {{
    color: {C['texto'].name()}; font-family: 'Segoe UI'; font-size: 12px; }}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: #1f2430; border: 1px solid {C['borde'].name()}; border-radius: 5px; padding: 3px 6px; }}
QComboBox QAbstractItemView {{ background: #1f2430; color: {C['texto'].name()}; }}
QGroupBox {{ border: 1px solid {C['borde'].name()}; border-radius: 6px; margin-top: 10px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {C['tenue'].name()}; }}
QTextBrowser {{
    background: #11141a; color: {C['texto'].name()}; border: 1px solid {C['borde'].name()};
    border-radius: 6px; font-family: 'Segoe UI'; font-size: 13px; padding: 4px;
}}
QTableWidget {{
    background: #11141a; color: {C['texto'].name()}; gridline-color: {C['borde'].name()};
    border: 1px solid {C['borde'].name()}; border-radius: 6px; font-family: 'Bahnschrift'; font-size: 13px;
}}
QHeaderView::section {{
    background: #1a1e27; color: {C['tenue'].name()}; border: none; padding: 4px; font-family: 'Segoe UI'; font-size: 11px;
}}
QListWidget {{ background: #11141a; color: {C['texto'].name()}; border: 1px solid {C['borde'].name()};
    border-radius: 6px; font-family: 'Bahnschrift'; font-size: 13px; }}
QScrollBar:vertical {{ background: #11141a; width: 8px; }}
QScrollBar::handle:vertical {{ background: {C['borde'].name()}; border-radius: 4px; }}
QToolBar {{ background: {C['fondo'].name()}; border: none; spacing: 6px; padding: 2px 6px; }}
QToolBar QToolButton {{
    color: {C['texto'].name()}; background: #1a1e27; border: 1px solid {C['borde'].name()};
    border-radius: 5px; padding: 4px 10px; font-family: 'Segoe UI'; font-size: 12px; }}
QToolBar QToolButton:hover {{ border-color: {C['cian'].name()}; }}
QTabWidget::pane {{ border: 1px solid {C['borde'].name()}; border-radius: 6px; }}
QTabBar::tab {{ background: #1a1e27; color: {C['tenue'].name()}; padding: 6px 16px; min-width: 120px; border-top-left-radius: 5px;
    border-top-right-radius: 5px; font-family: 'Segoe UI'; }}
QTabBar::tab:selected {{ background: #283042; color: {C['texto'].name()}; }}
QProgressBar {{ background: #1f2430; border: none; border-radius: 3px; height: 6px; }}
QProgressBar::chunk {{ background: {C['verde'].name()}; border-radius: 3px; }}
"""

PREGUNTAS = [
    ("Combustible", "combustible", "F1"), ("Neumáticos", "neumaticos", "F2"), ("Frenos", "frenos", "F3"),
    ("Tiempos", "tiempos", "F4"), ("Estrategia", "estrategia", "F5"), ("Ajustes", "ajustes", "F6"),
    ("Dónde pierdo", "donde_pierdo", "F7"), ("Resumen", "resumen", "F8"), ("Repite", "repite", "F9"),
    ("Rivales", "rivales", "F10"), ("Curvas", "curvas", "F11"), ("Presiones", "presiones", "F12"),
]


def _item(texto, alinear=Qt.AlignCenter):
    it = QTableWidgetItem(texto)
    it.setTextAlignment(int(alinear))
    return it


class TablaVueltas(QTableWidget):
    COLUMNAS = ["Vta", "Tiempo", "Δ mejor", "S1", "S2", "S3", "Comb.", "Pos", "Notas"]

    def __init__(self, app):
        super().__init__(0, len(self.COLUMNAS))
        self.app = app
        self._firma = None
        self.setHorizontalHeaderLabels(self.COLUMNAS)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        cab = self.horizontalHeader()
        cab.setSectionResizeMode(QHeaderView.ResizeToContents)
        cab.setStretchLastSection(True)

    def refrescar(self):
        a = self.app.analizador
        firma = (len(a.vueltas), a.mejor.numero if a.mejor else None, a.n_sectores)
        if firma == self._firma:
            return
        self._firma = firma
        n = a.n_sectores
        cols = self.COLUMNAS[:3] + [f"S{i + 1}" for i in range(n)] + self.COLUMNAS[6:]
        if self.columnCount() != len(cols):
            self.setColumnCount(len(cols))
        self.setHorizontalHeaderLabels(cols)
        self.setRowCount(len(a.vueltas))
        for fila, v in enumerate(reversed(a.vueltas)):
            dif = v.tiempo_ms - a.mejor.tiempo_ms if a.mejor else None
            notas = []
            if not v.valida:
                notas.append("no válida")
            if v.boxes:
                notas.append("boxes")
            if sum(v.bloqueos):
                notas.append(f"{sum(v.bloqueos)} bloq.")
            if sum(v.patinadas):
                notas.append(f"{sum(v.patinadas)} patin.")
            valores = [str(v.numero), fmt_tiempo(v.tiempo_ms), "" if v is a.mejor or dif is None else fmt_delta(dif)]
            valores += [fmt_tiempo(s)[2:] if s else "—" for s in (v.sectores + [None] * n)[:n]]
            valores += [f"{v.combustible:.2f}", f"P{v.posicion}" if v.posicion else "", ", ".join(notas)]
            for col, txt in enumerate(valores):
                item = _item(txt, Qt.AlignCenter if col < len(valores) - 1 else Qt.AlignLeft | Qt.AlignVCenter)
                if v is a.mejor:
                    item.setBackground(QColor(C["morado"].red(), C["morado"].green(), C["morado"].blue(), 70))
                if not v.valida:
                    item.setForeground(C["rojo"])
                if 3 <= col < 3 + n:
                    s = v.sectores[col - 3] if col - 3 < len(v.sectores) else None
                    if s and a.mejores_sectores[col - 3] and s <= a.mejores_sectores[col - 3]:
                        item.setForeground(C["morado"])
                self.setItem(fila, col, item)


class TablaClasificacion(QTableWidget):
    COLUMNAS = ["P", "Piloto", "Int.", "Líder", "Última", "Mejor", "Par.", ""]

    def __init__(self, app):
        super().__init__(0, len(self.COLUMNAS))
        self.app = app
        self._t = 0.0
        self.setHorizontalHeaderLabels(self.COLUMNAS)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(22)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        cab = self.horizontalHeader()
        cab.setSectionResizeMode(QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(1, QHeaderView.Stretch)

    def refrescar(self):
        ahora = time.monotonic()
        if ahora - self._t < 0.25:
            return
        self._t = ahora
        c = self.app.clasificacion
        if not c.activa:
            self.setRowCount(1)
            msg = _item("Sin datos de rivales: instala/activa la app IngenieroPuente en AC", Qt.AlignLeft | Qt.AlignVCenter)
            msg.setForeground(C["tenue"])
            self.setSpan(0, 0, 1, len(self.COLUMNAS))
            self.setItem(0, 0, msg)
            return
        self.clearSpans()
        yo = c.jugador
        delante, detras = c.cercanos()
        mejor_sesion = min((r.mejor for r in c.orden if r.mejor > 0), default=0)
        self.setRowCount(len(c.orden))
        negrita = QFont("Bahnschrift")
        negrita.setBold(True)
        for fila, r in enumerate(c.orden):
            intervalo = "" if r.intervalo is None else f"+{r.intervalo:.2f}" if c.carrera else f"+{r.intervalo:.3f}"
            lider = "" if r.gap_lider is None else f"+{r.gap_lider:.1f}"
            vueltas_menos = c.orden[0].vueltas - r.vueltas if c.carrera and c.orden else 0
            if c.carrera and vueltas_menos >= 1 and r.progreso < c.orden[0].progreso - 1:
                lider = f"+{int(c.orden[0].progreso - r.progreso)}V"
            estado = "BOX" if r.pitlane else ""
            valores = [str(r.pos), r.nombre, intervalo, lider, fmt_tiempo(r.ultima), fmt_tiempo(r.mejor),
                       str(r.paradas) if r.paradas else "", estado]
            for col, txt in enumerate(valores):
                it = _item(txt, Qt.AlignLeft | Qt.AlignVCenter if col == 1 else Qt.AlignCenter)
                if r is yo:
                    it.setBackground(QColor(62, 193, 255, 60))
                    it.setFont(negrita)
                elif r is delante or r is detras:
                    it.setBackground(QColor(255, 255, 255, 14))
                if col == 5 and r.mejor and r.mejor == mejor_sesion:
                    it.setForeground(C["morado"])
                if col == 7 and estado:
                    it.setForeground(C["amarillo"])
                self.setItem(fila, col, it)


class PanelIngeniero(QWidget):
    def __init__(self, app: Aplicacion):
        super().__init__()
        self.app = app
        self._vistos = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        titulo = QLabel("RADIO DEL INGENIERO")
        titulo.setObjectName("titulo")
        lay.addWidget(titulo)
        self.log = QTextBrowser()
        self.log.setOpenLinks(False)
        lay.addWidget(self.log, 1)

        rejilla = QGridLayout()
        rejilla.setSpacing(4)
        for i, (texto, intencion, tecla) in enumerate(PREGUNTAS):
            b = QPushButton(f"{texto} ({tecla})")
            b.clicked.connect(lambda _, it=intencion: self.app.ingeniero.responder(it))
            rejilla.addWidget(b, i // 4, i % 4)
        lay.addLayout(rejilla)

        controles = QHBoxLayout()
        self.chk_voz = QCheckBox("Voz")
        self.chk_voz.setChecked(app.radio.activada)
        self.chk_voz.toggled.connect(lambda v: setattr(app.radio, "activada", v))
        self.chk_mic = QCheckBox("Micro")
        self.chk_mic.setChecked(app.escucha is not None)
        self.chk_mic.setEnabled(app.escucha is not None)
        self.chk_mic.toggled.connect(lambda v: setattr(app.escucha, "activa", v) if app.escucha else None)
        self.chk_silencio = QCheckBox("Solo urgente")
        self.chk_silencio.toggled.connect(lambda v: setattr(app.radio, "silenciada", v))
        self.chk_rectas = QCheckBox("Solo en rectas")
        self.chk_rectas.setToolTip("El ingeniero espera a que haya una recta para hablar (lo urgente sale siempre)")
        self.chk_rectas.setChecked(app.radio.solo_rectas)
        self.chk_rectas.toggled.connect(lambda v: setattr(app.radio, "solo_rectas", v))
        self.combo = QComboBox()
        self.combo.addItems(["Solo lo crítico", "Normal", "Muy hablador"])
        self.combo.setCurrentIndex(app.config.verbosidad)
        self.combo.currentIndexChanged.connect(lambda i: setattr(app.config, "verbosidad", i))
        for w in (self.chk_voz, self.chk_mic, self.chk_silencio, self.chk_rectas):
            controles.addWidget(w)
        controles.addStretch(1)
        controles.addWidget(self.combo)
        lay.addLayout(controles)

        fila_mic = QHBoxLayout()
        self.estado = QLabel()
        self.estado.setObjectName("tenue")
        self.estado.setWordWrap(True)
        self.nivel = QProgressBar()
        self.nivel.setRange(0, 100)
        self.nivel.setTextVisible(False)
        self.nivel.setFixedWidth(70)
        self.nivel.setToolTip("Volumen del micrófono")
        fila_mic.addWidget(self.estado, 1)
        fila_mic.addWidget(self.nivel)
        lay.addLayout(fila_mic)

        tit2 = QLabel("CONSEJOS DE REGLAJE (última vuelta)")
        tit2.setObjectName("titulo")
        lay.addWidget(tit2)
        self.consejos = QLabel()
        self.consejos.setWordWrap(True)
        self.consejos.setMinimumHeight(48)
        self.consejos.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(self.consejos)
        self._t_lento = 0.0

    def refrescar(self):
        ing = self.app.ingeniero
        nuevos = ing.contador - self._vistos
        if nuevos > 0:
            for m in list(ing.log)[-min(nuevos, len(ing.log)):]:
                if m.origen == "piloto":
                    color, quien = C["cian"].name(), "TÚ"
                elif m.origen == "sistema":
                    color, quien = C["tenue"].name(), "SISTEMA"
                elif m.origen == "remoto":
                    color, quien = C["morado"].name(), "ING. REMOTO"
                else:
                    color = {CRITICO: C["rojo"].name(), ALTA: C["amarillo"].name()}.get(m.prioridad, C["texto"].name())
                    quien = "ING."
                self.log.append(f'<span style="color:{C["muy_tenue"].name()}">{m.hora}</span> '
                                f'<b style="color:{color}">{quien}</b> '
                                f'<span style="color:{color}">{html.escape(m.texto)}</span>')
            self._vistos = ing.contador
            barra = self.log.verticalScrollBar()
            barra.setValue(barra.maximum())

        esc = self.app.escucha
        if esc:
            self.nivel.setValue(int(esc.nivel * 100))
        ahora = time.monotonic()
        if ahora - self._t_lento < 0.5:
            return
        self._t_lento = ahora
        partes = [self.app.radio.estado]
        if esc:
            partes.append(f"micro: {esc.estado}")
            if esc.ultimo_texto:
                partes.append(f'oído: "{esc.ultimo_texto}"')
        else:
            partes.append("micrófono desactivado")
        pend = self.app.radio.pendientes()
        if pend:
            partes.append(f"{pend} frase(s) esperando una recta")
        self.estado.setText("   ·   ".join(partes))
        consejos = ing.consejos_actuales()
        a = self.app.analizador
        if consejos:
            self.consejos.setText("\n".join("• " + c for c in consejos))
        elif a.resumen_neumaticos is not None:
            self.consejos.setText("Los neumáticos trabajan dentro de la ventana. Nada que cambiar.")
        else:
            self.consejos.setText("Completa una vuelta para analizar las temperaturas.")


class Marco(Panel):
    """Panel con fondo para envolver widgets normales de Qt."""

    def __init__(self, app, interior, titulo=""):
        super().__init__(app)
        self.titulo = titulo
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 24 if titulo else 6, 8, 6)
        lay.addWidget(interior)


class VentanaPrincipal(QMainWindow):
    def __init__(self, app: Aplicacion):
        super().__init__()
        self.app = app
        self.setWindowTitle("Ingeniero de carrera · Assetto Corsa")
        self.setStyleSheet(ESTILO)
        self.resize(1800, 1000)
        self._ventanas = {}

        self._barra_herramientas()

        raiz = QWidget()
        raiz.setObjectName("raiz")
        self.setCentralWidget(raiz)
        general = QVBoxLayout(raiz)
        general.setContentsMargins(6, 0, 6, 6)
        general.setSpacing(0)

        self.cabecera = Cabecera(app)
        self.cabecera.setFixedHeight(64)
        general.addWidget(self.cabecera)

        columnas = QHBoxLayout()
        columnas.setSpacing(0)
        general.addLayout(columnas, 1)
        self.paneles = [self.cabecera]

        def columna(ancho, *items):
            lay = QVBoxLayout()
            lay.setSpacing(0)
            for widget, alto in items:
                lay.addWidget(widget, alto)
                if isinstance(widget, Panel):
                    self.paneles.append(widget)
            columnas.addLayout(lay, ancho)

        self.tabla = TablaVueltas(app)
        self.clasif = TablaClasificacion(app)
        self.ingeniero = PanelIngeniero(app)
        columna(10, (Motor(app), 22), (Pedales(app), 24), (GMetro(app), 20), (Coche(app), 14))
        columna(13, (Tiempos(app), 30), (Trazas(app), 22), (Marco(app, self.tabla), 30))
        columna(12, (Neumaticos(app), 46), (Combustible(app), 22), (Mapa(app), 32))
        columna(13, (Marco(app, self.clasif, "Clasificación en vivo"), 36), (Marco(app, self.ingeniero), 64))
        for w in self.paneles:
            w.setMinimumSize(120, 60)

        for texto, intencion, tecla in PREGUNTAS:
            QShortcut(QKeySequence(tecla), self, activated=lambda it=intencion: app.ingeniero.responder(it))

        self.t_datos = QTimer(self)
        self.t_datos.timeout.connect(self._tick)
        self.t_datos.start(15)
        self.t_ui = QTimer(self)
        self.t_ui.timeout.connect(self.refrescar)
        self.t_ui.start(33)
        QTimer.singleShot(1500, self._comprobar_app_ac)

    def _barra_herramientas(self):
        barra = QToolBar("Herramientas")
        barra.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, barra)
        self.acciones = {}
        for clave, texto, funcion in [
            ("analisis", "📈  Análisis de vueltas", self.abrir_analisis),
            ("estrategia", "⛽  Estrategia", self.abrir_estrategia),
            ("ajustes", "⚙  Ajustes", self.abrir_ajustes),
            ("app_ac", "🔌  Instalar app en AC", self.instalar_app_ac),
        ]:
            accion = QAction(texto, self)
            accion.triggered.connect(funcion)
            barra.addAction(accion)
            self.acciones[clave] = accion
        barra.addSeparator()
        self.lbl_puente = QLabel()
        barra.addWidget(self.lbl_puente)

    # ------------------------------------------------------------ ventanas
    def _abrir(self, clave, crear):
        v = self._ventanas.get(clave)
        if v is None or not v.isVisible():
            try:
                v = crear()
            except Exception as e:
                log.exception("No se pudo abrir %s", clave)
                QMessageBox.warning(self, "Error", f"No se pudo abrir la ventana: {e}")
                return
            v.setStyleSheet(ESTILO)
            self._ventanas[clave] = v
        v.show()
        v.raise_()
        v.activateWindow()

    def abrir_analisis(self):
        from .analisis_ui import VentanaAnalisis
        self._abrir("analisis", lambda: VentanaAnalisis(self.app))

    def abrir_estrategia(self):
        from .estrategia_ui import VentanaEstrategia
        self._abrir("estrategia", lambda: VentanaEstrategia(self.app))

    def abrir_ajustes(self):
        from .ajustes_ui import DialogoAjustes
        self._abrir("ajustes", lambda: DialogoAjustes(self.app, self))

    def instalar_app_ac(self):
        try:
            ok, msg = instalar_ac.instalar()
        except Exception as e:
            ok, msg = False, f"Error instalando: {e}"
        (QMessageBox.information if ok else QMessageBox.warning)(self, "App de Assetto Corsa", msg)

    def _comprobar_app_ac(self):
        if self.app.analizador.fuente == "demo":
            return
        try:
            if instalar_ac.buscar_ac() and not instalar_ac.instalada():
                r = QMessageBox.question(
                    self, "App de Assetto Corsa",
                    "Para ver a los rivales y el HUD dentro del juego hace falta la app IngenieroPuente en AC.\n\n"
                    "¿La instalo ahora?")
                if r == QMessageBox.Yes:
                    self.instalar_app_ac()
        except Exception:
            log.exception("Comprobando la app de AC")

    # ------------------------------------------------------------ ciclo
    def _tick(self):
        try:
            self.app.tick()
        except Exception:
            log.exception("Error en el ciclo principal")

    def refrescar(self):
        for p in self.paneles:
            p.update()
        self.tabla.refrescar()
        self.clasif.refrescar()
        self.ingeniero.refrescar()
        activo = self.app.clasificacion.activa
        web = getattr(self.app, "web", None)
        self.lbl_puente.setText(("  🟢 Rivales en vivo" if activo else "  ⚪ Sin datos de rivales") +
                                ("   ·   HUD en juego activo" if self.app.hud and self.app.hud.mem else "") +
                                (f"   ·   📱 {web.urls()[0]}  (PIN {web.pin})" if web is not None and web.servidor else ""))

    def closeEvent(self, ev):
        self.t_datos.stop()
        self.t_ui.stop()
        for v in self._ventanas.values():
            v.close()
        archivos = self.app.cerrar()
        for f in archivos:
            log.info("Sesión guardada: %s", f)
        super().closeEvent(ev)
