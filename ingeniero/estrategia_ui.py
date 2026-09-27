"""Ventana de estrategia: plan de paradas, posición tras parar, presiones y degradación."""
import matplotlib

matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PyQt5.QtCore import Qt, QTimer  # noqa: E402
from PyQt5.QtGui import QColor  # noqa: E402
from PyQt5.QtWidgets import (QAbstractItemView, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,  # noqa: E402
                             QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import memoria_ac as mac  # noqa: E402
from .estrategia import K_COMBUSTIBLE, PERDIDA_CARRIL_DEFECTO  # noqa: E402
from .ingeniero import apellido  # noqa: E402

FONDO, PANEL, TEXTO, TENUE, REJILLA = "#11141a", "#161920", "#e8eaf0", "#8a91a0", "#252a35"


def _tabla(columnas):
    t = QTableWidget(0, len(columnas))
    t.setHorizontalHeaderLabels(columnas)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionMode(QAbstractItemView.NoSelection)
    cab = t.horizontalHeader()
    cab.setSectionResizeMode(QHeaderView.ResizeToContents)
    cab.setStretchLastSection(True)
    return t


class VentanaEstrategia(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Estrategia")
        self.setObjectName("raiz")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.resize(1250, 820)
        raiz = QGridLayout(self)

        # Situación
        caja = QGroupBox("Situación")
        self.form = QFormLayout(caja)
        self.valores = {}
        for clave in ("Vueltas restantes", "Combustible", "Consumo por vuelta", "Autonomía", "Necesario hasta el final",
                      "Neumáticos (vida)", "Edad del juego", "Degradación", "Pérdida en boxes (carril)",
                      "Ritmo de repostaje", "Si paro ahora"):
            lbl = QLabel("—")
            lbl.setWordWrap(True)
            self.form.addRow(clave, lbl)
            self.valores[clave] = lbl
        raiz.addWidget(caja, 0, 0)

        # Ajustes del plan
        ajustes = QGroupBox("Supuestos")
        fa = QFormLayout(ajustes)
        self.margen = QDoubleSpinBox()
        self.margen.setRange(0, 5)
        self.margen.setSingleStep(0.5)
        self.margen.setValue(app.config.margen_vueltas_combustible)
        self.margen.setSuffix(" vueltas")
        self.margen.valueChanged.connect(lambda v: setattr(app.config, "margen_vueltas_combustible", v))
        fa.addRow("Margen de combustible", self.margen)
        self.t_neum = QDoubleSpinBox()
        self.t_neum.setRange(0, 60)
        self.t_neum.setSuffix(" s")
        self.t_neum.setValue(getattr(app, "estrategia").t_neumaticos)
        self.t_neum.valueChanged.connect(lambda v: setattr(app.estrategia, "t_neumaticos", v))
        fa.addRow("Tiempo de cambio de ruedas", self.t_neum)
        self.ritmo = QDoubleSpinBox()
        self.ritmo.setRange(0.2, 10)
        self.ritmo.setSingleStep(0.1)
        self.ritmo.setSuffix(" L/s")
        self.ritmo.setValue(app.estrategia.ritmo_repostaje)
        self.ritmo.valueChanged.connect(lambda v: setattr(app.estrategia, "ritmo_repostaje", v))
        fa.addRow("Ritmo de repostaje", self.ritmo)
        nota = QLabel("La pérdida en boxes y el ritmo de repostaje se miden solos en cuanto paras una vez.")
        nota.setObjectName("tenue")
        nota.setWordWrap(True)
        fa.addRow(nota)
        raiz.addWidget(ajustes, 1, 0)

        # Opciones
        caja_plan = QGroupBox("Plan de carrera")
        lp = QVBoxLayout(caja_plan)
        self.recom = QLabel()
        self.recom.setWordWrap(True)
        lp.addWidget(self.recom)
        self.tabla = _tabla(["Opción", "Viable", "Ventana (vueltas)", "Ideal", "Litros", "Ruedas", "Coste estimado", "Notas"])
        lp.addWidget(self.tabla)
        raiz.addWidget(caja_plan, 0, 1)

        # Presiones
        caja_pres = QGroupBox("Presiones (calculadora)")
        lpr = QVBoxLayout(caja_pres)
        self.tabla_pres = _tabla(["Eje", "En caliente", "Objetivo", "Sube frío→caliente", "Pon en frío"])
        lpr.addWidget(self.tabla_pres)
        self.nota_pres = QLabel()
        self.nota_pres.setObjectName("tenue")
        self.nota_pres.setWordWrap(True)
        lpr.addWidget(self.nota_pres)
        raiz.addWidget(caja_pres, 1, 1)

        # Degradación
        caja_deg = QGroupBox("Tiempo por vuelta y degradación del neumático")
        ld = QHBoxLayout(caja_deg)
        self.fig = Figure(facecolor=FONDO)
        self.lienzo = FigureCanvasQTAgg(self.fig)
        ld.addWidget(self.lienzo)
        raiz.addWidget(caja_deg, 2, 0, 1, 2)
        raiz.setRowStretch(2, 1)
        raiz.setColumnStretch(1, 1)

        self._n_vueltas = -1
        self._t = QTimer(self)
        self._t.timeout.connect(self.refrescar)
        self._t.start(1000)
        self.refrescar()

    def refrescar(self):
        a, e = self.app.analizador, self.app.estrategia
        s = a.snap
        v = self.valores
        if s is None:
            v["Vueltas restantes"].setText("Sin datos")
            return
        ph, st = s.physics, s.static

        def fmt(x, patron, vacio="—"):
            return vacio if x is None else patron.format(x)
        v["Vueltas restantes"].setText(fmt(a.vueltas_restantes, "{:.1f}") +
                                       ("" if s.graphics.session == mac.SESION_CARRERA else "  (el plan solo se calcula en carrera)"))
        v["Combustible"].setText(f"{ph.fuel:.1f} L de {st.maxFuel:.0f} L")
        v["Consumo por vuelta"].setText(fmt(a.combustible_por_vuelta, "{:.2f} L"))
        v["Autonomía"].setText(fmt(a.vueltas_con_combustible, "{:.1f} vueltas"))
        v["Necesario hasta el final"].setText(fmt(a.combustible_necesario, "{:.1f} L") +
                                              ("" if a.combustible_sobra is None else
                                               f"   ({'sobran' if a.combustible_sobra >= 0 else 'faltan'} {abs(a.combustible_sobra):.1f} L)"))
        v["Neumáticos (vida)"].setText(f"{min(ph.tyreWear):.1f}% · " + fmt(a.vueltas_neumatico, "~{:.0f} vueltas más"))
        v["Edad del juego"].setText(f"{a.edad_neumaticos} vueltas")
        v["Degradación"].setText(fmt(e.degradacion, "{:.3f} s por vuelta", "necesito 3 vueltas limpias con este juego"))
        carril = e.perdida_carril if e.perdida_carril is not None else PERDIDA_CARRIL_DEFECTO
        v["Pérdida en boxes (carril)"].setText(f"{carril:.1f} s ({e.fuente_perdida})")
        v["Ritmo de repostaje"].setText(f"{e.ritmo_repostaje:.2f} L/s")
        pos, delante = e.parada_ahora
        if pos:
            txt = f"Saldrías P{pos}"
            if delante:
                txt += f", a {delante[0]:.1f} s de {apellido(delante[1].nombre)}"
            v["Si paro ahora"].setText(txt)
        else:
            v["Si paro ahora"].setText("sin datos de rivales" if not self.app.clasificacion.activa else "—")

        p = e.plan
        if p is None:
            self.recom.setText("<b>Sin plan todavía</b>: hace falta estar en carrera y conocer el consumo." if not e.opciones
                               else "<b style='color:#ff4d5e'>Ninguna opción de una parada es viable.</b>")
        else:
            txt = f"<b>Recomendado: {p.nombre}</b>"
            if p.vuelta_desde:
                txt += f" — entre las vueltas {p.vuelta_desde} y {p.vuelta_hasta}"
            if p.vuelta_ideal:
                txt += f" (ideal: {p.vuelta_ideal})"
            if p.litros:
                txt += f", echar {p.litros:.1f} L"
            self.recom.setText(txt)
        self.tabla.setRowCount(len(e.opciones))
        base = min((o.coste_s for o in e.opciones if o.viable), default=0)
        for fila, o in enumerate(e.opciones):
            valores = [o.nombre, "sí" if o.viable else "no",
                       f"{o.vuelta_desde} – {o.vuelta_hasta}" if o.vuelta_desde else "",
                       str(o.vuelta_ideal or ""), f"{o.litros:.1f}" if o.litros else "", "sí" if o.neumaticos else "",
                       f"+{o.coste_s - base:.1f} s" if o.viable else "", o.motivo]
            for col, txt in enumerate(valores):
                it = QTableWidgetItem(txt)
                it.setTextAlignment(int(Qt.AlignCenter if col < 7 else Qt.AlignLeft | Qt.AlignVCenter))
                if o is p:
                    it.setBackground(QColor(53, 208, 127, 50))
                if not o.viable:
                    it.setForeground(QColor(TENUE))
                self.tabla.setItem(fila, col, it)

        rec = e.recomendacion_presiones()
        self.tabla_pres.setRowCount(len(rec))
        for fila, (eje, (caliente, objetivo, subida, frio)) in enumerate(rec.items()):
            valores = [eje.capitalize(), fmt(caliente, "{:.1f} psi"), f"{objetivo:.1f} psi",
                       fmt(subida, "+{:.1f} psi"), fmt(frio, "{:.1f} psi")]
            for col, txt in enumerate(valores):
                it = QTableWidgetItem(txt)
                it.setTextAlignment(int(Qt.AlignCenter))
                if col == 4 and frio is not None:
                    it.setForeground(QColor("#35d07f"))
                self.tabla_pres.setItem(fila, col, it)
        pr = e.presiones
        self.nota_pres.setText(
            ("Presiones en frío medidas al salir: " + ", ".join(f"{x:.1f}" for x in pr.frio) + " psi. " if all(pr.frio) else
             "No he podido medir este juego en frío (sal de boxes con neumáticos fríos). ") +
            f"Objetivo según el perfil «{a.perfil.nombre}»: {a.perfil.psi_min}–{a.perfil.psi_max} psi en caliente.")

        if len(a.vueltas) != self._n_vueltas:
            self._n_vueltas = len(a.vueltas)
            self._grafica()

    def _grafica(self):
        a = self.app.analizador
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=TENUE, labelsize=8)
        for lado in ax.spines.values():
            lado.set_color(REJILLA)
        ax.grid(True, color=REJILLA, linewidth=0.6)
        limpias = [v for v in a.vueltas if v.valida and not v.boxes and v.tiempo_ms > 0]
        if not limpias:
            ax.text(0.5, 0.5, "Sin vueltas limpias todavía", color=TENUE, ha="center", va="center", transform=ax.transAxes)
            self.lienzo.draw_idle()
            return
        xs = [v.numero for v in limpias]
        ax.plot(xs, [v.tiempo_ms / 1000 for v in limpias], "o-", color="#3ec1ff", markersize=4, linewidth=1.2,
                label="Tiempo por vuelta")
        corregido = [v.tiempo_ms / 1000 - K_COMBUSTIBLE * (v.combustible_fin + v.combustible - limpias[-1].combustible_fin)
                     for v in limpias]
        ax.plot(xs, corregido, "s--", color="#ff9f43", markersize=3, linewidth=1.0,
                label="Corregido por combustible (efecto neumático)")
        for v in a.vueltas:
            if v.boxes:
                ax.axvline(v.numero, color="#ffc940", linewidth=1, linestyle=":")
        ax.set_xlabel("Vuelta", color=TENUE, fontsize=8)
        ax.set_ylabel("s", color=TENUE, fontsize=8)
        ley = ax.legend(fontsize=8, facecolor=PANEL, edgecolor=REJILLA)
        for t in ley.get_texts():
            t.set_color(TEXTO)
        self.fig.tight_layout()
        self.lienzo.draw_idle()
