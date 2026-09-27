"""Ventana de análisis: comparar vueltas, curva a curva, mapa de ganancias y exportar a MoTeC."""
import logging
import os
from dataclasses import dataclass

import matplotlib

matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PyQt5.QtCore import Qt, QTimer  # noqa: E402
from PyQt5.QtGui import QColor  # noqa: E402
from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,  # noqa: E402
                             QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from . import curvas as mod_curvas  # noqa: E402
from . import motec, rutas, sesiones  # noqa: E402
from .analisis import N_BINS  # noqa: E402
from .ingeniero import fmt_tiempo  # noqa: E402

log = logging.getLogger(__name__)
COLORES = ["#3ec1ff", "#ff9f43", "#b36bff", "#35d07f", "#ff6bb5", "#ffc940"]
FONDO, PANEL, TEXTO, TENUE, REJILLA = "#11141a", "#161920", "#e8eaf0", "#8a91a0", "#252a35"


@dataclass
class VueltaAnalisis:
    etiqueta: str
    tiempo_ms: int
    traza: dict
    valida: bool
    es_referencia: bool = False


def _estilo_ejes(ax):
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=TENUE, labelsize=8)
    for lado in ax.spines.values():
        lado.set_color(REJILLA)
    ax.grid(True, color=REJILLA, linewidth=0.6)
    ax.yaxis.label.set_color(TENUE)
    ax.xaxis.label.set_color(TENUE)


class VentanaAnalisis(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Análisis de vueltas")
        self.setObjectName("raiz")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.resize(1500, 900)
        self.vueltas: list[VueltaAnalisis] = []
        self.sesion = None  # SesionGuardada si se ha abierto una de disco
        self.longitud = 0.0
        self._n_vueltas_vistas = -1

        raiz = QHBoxLayout(self)
        izq = QVBoxLayout()
        raiz.addLayout(izq, 0)

        self.fuente = QComboBox()
        self.fuente.setMinimumWidth(300)
        izq.addWidget(QLabel("Datos"))
        izq.addWidget(self.fuente)
        izq.addWidget(QLabel("Vueltas (la primera marcada es la base de comparación)"))
        self.lista = QListWidget()
        self.lista.itemChanged.connect(lambda _: self.dibujar())
        izq.addWidget(self.lista, 1)
        for texto, funcion in (("Marcar mejor y última", self.marcar_por_defecto),
                               ("Guardar vuelta marcada como referencia", self.guardar_referencia),
                               ("Exportar sesión a MoTeC (.ld)", self.exportar_motec),
                               ("Abrir sesión de otro sitio...", self.abrir_archivo)):
            b = QPushButton(texto)
            b.clicked.connect(funcion)
            izq.addWidget(b)
        self.info = QLabel()
        self.info.setObjectName("tenue")
        self.info.setWordWrap(True)
        izq.addWidget(self.info)

        self.pestanas = QTabWidget()
        self.pestanas.tabBar().setElideMode(Qt.ElideNone)
        self.pestanas.tabBar().setExpanding(False)
        raiz.addWidget(self.pestanas, 1)

        # Telemetría
        tele = QWidget()
        lt = QVBoxLayout(tele)
        self.fig = Figure(facecolor=FONDO)
        self.lienzo = FigureCanvasQTAgg(self.fig)
        lt.addWidget(NavigationToolbar2QT(self.lienzo, self))
        lt.addWidget(self.lienzo, 1)
        self.pestanas.addTab(tele, "Telemetría")

        # Curvas
        self.tabla = QTableWidget(0, 9)
        self.tabla.setHorizontalHeaderLabels(["Curva", "Tipo", "Δ tiempo", "Frenada (m antes)", "V mín",
                                              "V salida", "Gas a fondo (m)", "Marcha", "Consejo"])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        cab = self.tabla.horizontalHeader()
        cab.setSectionResizeMode(QHeaderView.ResizeToContents)
        cab.setStretchLastSection(True)
        curvas_w = QWidget()
        lc = QVBoxLayout(curvas_w)
        self.resumen_curvas = QLabel()
        self.resumen_curvas.setWordWrap(True)
        lc.addWidget(self.resumen_curvas)
        lc.addWidget(self.tabla, 1)
        self.pestanas.addTab(curvas_w, "Curva a curva")

        # Mapa de ganancias
        mapa_w = QWidget()
        lm = QVBoxLayout(mapa_w)
        self.fig_mapa = Figure(facecolor=FONDO)
        self.lienzo_mapa = FigureCanvasQTAgg(self.fig_mapa)
        lm.addWidget(self.lienzo_mapa, 1)
        self.pestanas.addTab(mapa_w, "Mapa de ganancias")

        self._llenar_fuentes()
        self.fuente.currentIndexChanged.connect(self.cargar_fuente)
        self.cargar_fuente()
        self._temporizador = QTimer(self)
        self._temporizador.timeout.connect(self._comprobar_nuevas)
        self._temporizador.start(2000)

    # ------------------------------------------------------------- datos
    def _llenar_fuentes(self):
        self.fuente.blockSignals(True)
        self.fuente.clear()
        self.fuente.addItem("Sesión actual (en directo)", None)
        for ruta, meta in sesiones.listar():
            titulo = f"{meta.get('inicio', os.path.basename(ruta))[:16].replace('T', ' ')} · " \
                     f"{meta.get('coche', '?')} · {meta.get('pista', '?')}" if meta else os.path.basename(ruta)
            self.fuente.addItem(titulo, ruta)
        self.fuente.blockSignals(False)

    def _vueltas_actuales(self):
        a = self.app.analizador
        out = []
        if a.referencia:
            out.append(VueltaAnalisis(f"Referencia  {fmt_tiempo(a.referencia['tiempo_ms'])}  "
                                      f"({a.referencia.get('fecha', '')[:10]})", a.referencia["tiempo_ms"],
                                      a.referencia["traza"], True, True))
        for v in a.vueltas:
            if v.traza is None:
                continue
            notas = " (no válida)" if not v.valida else " (boxes)" if v.boxes else ""
            if v is a.mejor:
                notas += "  ★ mejor"
            out.append(VueltaAnalisis(f"V{v.numero}  {fmt_tiempo(v.tiempo_ms)}{notas}", v.tiempo_ms, v.traza,
                                      v.valida and not v.boxes))
        return out

    def cargar_fuente(self):
        ruta = self.fuente.currentData()
        self.sesion = None
        try:
            if ruta is None:
                self.vueltas = self._vueltas_actuales()
                self.longitud = self.app.analizador.longitud_pista
                self._n_vueltas_vistas = len(self.app.analizador.vueltas)
            else:
                self.sesion = sesiones.abrir(ruta)
                self.longitud = float(self.sesion.meta.get("longitud_pista") or 0)
                self.vueltas = [VueltaAnalisis(f"V{v.numero}  {fmt_tiempo(v.tiempo_ms)}" +
                                               (" (boxes)" if v.boxes else " (no válida)" if not v.valida else ""),
                                               v.tiempo_ms, v.traza, v.valida and not v.boxes)
                                for v in self.sesion.vueltas]
        except Exception as e:
            log.exception("No se pudo abrir la sesión")
            QMessageBox.warning(self, "Análisis", f"No se pudo abrir la sesión: {e}")
            self.vueltas = []
        self._llenar_lista()
        self.marcar_por_defecto()

    def _llenar_lista(self):
        self.lista.blockSignals(True)
        self.lista.clear()
        for i, v in enumerate(self.vueltas):
            it = QListWidgetItem(v.etiqueta)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, i)
            if not v.valida:
                it.setForeground(QColor("#8a91a0"))
            self.lista.addItem(it)
        self.lista.blockSignals(False)

    def _comprobar_nuevas(self):
        if self.fuente.currentData() is None and len(self.app.analizador.vueltas) != self._n_vueltas_vistas:
            marcadas = {self.vueltas[i].etiqueta.split()[0] for i in self._marcadas()}
            self.vueltas = self._vueltas_actuales()
            self._n_vueltas_vistas = len(self.app.analizador.vueltas)
            self._llenar_lista()
            self.lista.blockSignals(True)
            for k in range(self.lista.count()):
                it = self.lista.item(k)
                if it.text().split()[0] in marcadas:
                    it.setCheckState(Qt.Checked)
            self.lista.blockSignals(False)
            self.dibujar()

    def marcar_por_defecto(self):
        """Base = referencia o mejor vuelta válida; comparada con la última vuelta."""
        if not self.vueltas:
            self.dibujar()
            return
        validas = [i for i, v in enumerate(self.vueltas) if v.valida]
        ref = next((i for i, v in enumerate(self.vueltas) if v.es_referencia), None)
        base = ref if ref is not None else (min(validas, key=lambda i: self.vueltas[i].tiempo_ms) if validas else 0)
        # Con qué comparar: la última vuelta que no sea la misma que la base (la referencia puede ser una de hoy)
        traza_base = self.vueltas[base].traza
        otras = [i for i, v in enumerate(self.vueltas) if i != base and v.traza is not traza_base
                 and v.tiempo_ms != self.vueltas[base].tiempo_ms]
        otra = otras[-1] if otras else None
        self.lista.blockSignals(True)
        for k in range(self.lista.count()):
            self.lista.item(k).setCheckState(Qt.Checked if k in (base, otra) else Qt.Unchecked)
        self.lista.blockSignals(False)
        self.dibujar()

    def _marcadas(self):
        return [self.lista.item(k).data(Qt.UserRole) for k in range(self.lista.count())
                if self.lista.item(k).checkState() == Qt.Checked]

    # ------------------------------------------------------------- dibujo
    def dibujar(self):
        marcadas = [self.vueltas[i] for i in self._marcadas()][:6]
        self._dibujar_telemetria(marcadas)
        self._tabla_curvas(marcadas)
        self._dibujar_mapa(marcadas)

    def _distancias(self, traza):
        m = mod_curvas.metros_por_punto(traza, self.longitud)
        return [i * m for i in range(N_BINS + 1)], m

    def _dibujar_telemetria(self, marcadas):
        self.fig.clear()
        if not marcadas:
            self.lienzo.draw_idle()
            return
        ejes = self.fig.subplots(5, 1, sharex=True, gridspec_kw={"height_ratios": [3, 2, 1.4, 1, 1.6]})
        self.fig.subplots_adjust(left=0.06, right=0.99, top=0.97, bottom=0.05, hspace=0.08)
        base = marcadas[0]
        x, m = self._distancias(base.traza)
        for i, v in enumerate(marcadas):
            col = COLORES[i % len(COLORES)]
            tr = v.traza
            ejes[0].plot(x, tr["v"], color=col, linewidth=1.3, label=v.etiqueta)
            ejes[1].plot(x, [g * 100 for g in tr["gas"]], color=col, linewidth=1.1)
            ejes[1].plot(x, [f * 100 for f in tr["freno"]], color=col, linewidth=1.1, linestyle="--")
            ejes[2].plot(x, tr["volante"], color=col, linewidth=1.0)
            ejes[3].plot(x, tr["marcha"], color=col, linewidth=1.0, drawstyle="steps-post")
            if i > 0:
                ejes[4].plot(x, [(a - b) / 1000 for a, b in zip(tr["t"], base.traza["t"])], color=col, linewidth=1.3)
        ejes[4].axhline(0, color=TENUE, linewidth=0.8)
        for ax, nombre in zip(ejes, ("km/h", "Gas / freno %", "Volante", "Marcha", f"Δ s vs {base.etiqueta.split()[0]}")):
            _estilo_ejes(ax)
            ax.set_ylabel(nombre, fontsize=8)
        ejes[-1].set_xlabel("Distancia (m)", fontsize=8)
        ley = ejes[0].legend(loc="lower left", fontsize=8, facecolor=PANEL, edgecolor=REJILLA)
        for t in ley.get_texts():
            t.set_color(TEXTO)
        # Curvas
        for c in mod_curvas.detectar_curvas(base.traza, self.longitud):
            for ax in ejes:
                ax.axvline(c.apice * m, color=REJILLA, linewidth=0.8, linestyle=":")
            ejes[0].text(c.apice * m, ejes[0].get_ylim()[1] * 0.97, f"C{c.numero}", color=TENUE,
                         fontsize=7, ha="center", va="top")
        self.lienzo.draw_idle()

    def _tabla_curvas(self, marcadas):
        self.tabla.setRowCount(0)
        if len(marcadas) < 2:
            self.resumen_curvas.setText("Marca dos vueltas: la primera es la base y se compara con la segunda.")
            return
        base, otra = marcadas[0], marcadas[1]
        cs = mod_curvas.detectar_curvas(base.traza, self.longitud)
        res = mod_curvas.comparar(otra.traza, base.traza, cs, self.longitud)
        res.sort(key=lambda r: r["curva"])
        total = otra.tiempo_ms - base.tiempo_ms
        peores = sorted(res, key=lambda r: -r["perdida_ms"])[:3]
        self.resumen_curvas.setText(
            f"<b>{otra.etiqueta}</b> frente a <b>{base.etiqueta}</b>: {total / 1000:+.3f} s en total.   "
            "Donde más se pierde: " + ", ".join(f"C{r['curva']} ({r['perdida_ms'] / 1000:+.2f} s)" for r in peores
                                                 if r["perdida_ms"] > 0))
        self.tabla.setRowCount(len(res))
        for fila, r in enumerate(res):
            mv, mr = r["vuelta"], r["ref"]

            def par(a, b, fmt="{:.0f}"):
                if a is None and b is None:
                    return "—"
                fa = "—" if a is None else fmt.format(a)
                fb = "—" if b is None else fmt.format(b)
                return f"{fa}  /  {fb}"
            valores = [f"C{r['curva']}", r["tipo"], f"{r['perdida_ms'] / 1000:+.3f}",
                       par(mv["frenada_m"], mr["frenada_m"]), par(mv["v_min"], mr["v_min"]),
                       par(mv["v_salida"], mr["v_salida"]), par(mv["gas_m"], mr["gas_m"]),
                       par(mv["marcha_min"], mr["marcha_min"], "{}"), "; ".join(r["consejos"])]
            for col, txt in enumerate(valores):
                it = QTableWidgetItem(txt)
                it.setTextAlignment(int(Qt.AlignCenter if col < 8 else Qt.AlignLeft | Qt.AlignVCenter))
                if col == 2:
                    p = r["perdida_ms"]
                    it.setForeground(QColor("#ff4d5e") if p > 50 else QColor("#35d07f") if p < -50 else QColor(TEXTO))
                self.tabla.setItem(fila, col, it)

    def _dibujar_mapa(self, marcadas):
        self.fig_mapa.clear()
        ax = self.fig_mapa.add_subplot(111)
        ax.set_facecolor(FONDO)
        ax.set_aspect("equal")
        ax.axis("off")
        if len(marcadas) < 2:
            ax.text(0.5, 0.5, "Marca dos vueltas para ver dónde ganas y pierdes tiempo", color=TENUE,
                    ha="center", va="center", transform=ax.transAxes)
            self.lienzo_mapa.draw_idle()
            return
        base, otra = marcadas[0], marcadas[1]
        xs, zs = base.traza["x"], base.traza["z"]
        # Ganancia por tramo: cuánto cambia la diferencia de tiempo en cada punto (s por punto)
        dif = [(a - b) for a, b in zip(otra.traza["t"], base.traza["t"])]
        cambio = [dif[i + 1] - dif[i] for i in range(N_BINS)]
        absolutos = sorted(abs(c) for c in cambio)
        lim = max(0.5, absolutos[int(len(absolutos) * 0.95)])  # percentil 95: un error grande no aplana el resto
        segmentos = [[(xs[i], zs[i]), (xs[i + 1], zs[i + 1])] for i in range(N_BINS)]
        lc = LineCollection(segmentos, cmap="RdYlGn_r", linewidths=5)
        lc.set_array([max(-lim, min(lim, c)) for c in cambio])
        lc.set_clim(-lim, lim)
        ax.add_collection(lc)
        ax.autoscale()
        for c in mod_curvas.detectar_curvas(base.traza, self.longitud):
            ax.annotate(f"C{c.numero}", (xs[c.apice], zs[c.apice]), color=TEXTO, fontsize=8,
                        xytext=(6, 6), textcoords="offset points")
        ax.set_title(f"Rojo: {otra.etiqueta.split()[0]} pierde · Verde: gana (frente a {base.etiqueta.split()[0]})",
                     color=TENUE, fontsize=10)
        ax.invert_yaxis()
        self.lienzo_mapa.draw_idle()

    # ------------------------------------------------------------ acciones
    def guardar_referencia(self):
        marcadas = [self.vueltas[i] for i in self._marcadas()]
        bd = getattr(self.app, "base_datos", None)
        if not marcadas or bd is None or bd.clave is None or self.sesion is not None:
            QMessageBox.information(self, "Referencia", "Marca una vuelta de la sesión actual para usarla como referencia.")
            return
        v = marcadas[-1]
        bd.bd.guardar_referencia(*bd.clave, v.tiempo_ms, [], v.traza, "manual")
        self.app.analizador.referencia = {"tiempo_ms": v.tiempo_ms, "traza": v.traza, "sectores": [],
                                          "fecha": "", "fuente": "manual"}
        QMessageBox.information(self, "Referencia", f"{v.etiqueta} es ahora tu vuelta de referencia.")
        self.cargar_fuente()

    def exportar_motec(self):
        import pandas as pd
        try:
            if self.sesion is not None:
                df, meta = self.sesion.datos, self.sesion.meta
                base = os.path.splitext(self.sesion.ruta)[0]
            else:
                g = self.app.grabador
                if not g.filas:
                    raise ValueError("Aún no hay datos grabados en esta sesión")
                df, meta = pd.DataFrame(g.filas), g._meta_completa()
                base = g._rutas()
            ld, ldx = motec.exportar(df, meta, base + ".ld")
            QMessageBox.information(self, "MoTeC", f"Exportado:\n{ld}\n{ldx}\n\nÁbrelo con MoTeC i2 Pro (gratuito).")
        except Exception as e:
            log.exception("Exportando a MoTeC")
            QMessageBox.warning(self, "MoTeC", f"No se pudo exportar: {e}")

    def abrir_archivo(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Abrir sesión", rutas.SESIONES, "Sesiones (*.parquet)")
        if ruta:
            self.fuente.addItem(os.path.basename(ruta), ruta)
            self.fuente.setCurrentIndex(self.fuente.count() - 1)
