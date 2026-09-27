"""Widgets del panel de telemetría (dibujados con QPainter)."""
import logging
import time

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QWidget

from . import memoria_ac as mac
from .analisis import N_BINS
from .ingeniero import fmt_delta, fmt_tiempo, nombre_coche

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ tema
C = {
    "fondo": QColor("#0d0f13"),
    "panel": QColor("#161920"),
    "borde": QColor("#252a35"),
    "texto": QColor("#e8eaf0"),
    "tenue": QColor("#8a91a0"),
    "muy_tenue": QColor("#4a505c"),
    "cian": QColor("#3ec1ff"),
    "verde": QColor("#35d07f"),
    "rojo": QColor("#ff4d5e"),
    "amarillo": QColor("#ffc940"),
    "morado": QColor("#b36bff"),
    "naranja": QColor("#ff9f43"),
    "azul": QColor("#4d8dff"),
    "frio": QColor("#3b6cff"),
}
FUENTE_NUM = "Bahnschrift"
FUENTE_TXT = "Segoe UI"


def mezclar(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


def color_ventana(valor, minimo, maximo, margen=None):
    """Azul si está por debajo de la ventana, verde dentro y rojo por encima."""
    margen = margen or max(1e-6, (maximo - minimo) * 0.6)
    if valor < minimo:
        return mezclar(C["verde"], C["frio"], (minimo - valor) / margen)
    if valor > maximo:
        return mezclar(C["amarillo"], C["rojo"], (valor - maximo) / margen) if valor - maximo > margen * 0.25 \
            else mezclar(C["verde"], C["amarillo"], (valor - maximo) / (margen * 0.25))
    return C["verde"]


def fuente(tam, negrita=False, num=True):
    f = QFont(FUENTE_NUM if num else FUENTE_TXT)
    f.setPixelSize(max(6, int(tam)))
    f.setBold(negrita)
    return f


class Panel(QWidget):
    """Panel con fondo, borde y título. Las subclases implementan `pintar(p, rect)`."""
    titulo = ""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app  # acceso a analizador, ingeniero, config
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    @property
    def a(self):
        return self.app.analizador

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(self.rect(), C["fondo"])
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.setPen(QPen(C["borde"], 1))
        p.setBrush(C["panel"])
        p.drawRoundedRect(r, 8, 8)
        if self.titulo:
            p.setFont(fuente(11, True, num=False))
            p.setPen(C["tenue"])
            p.drawText(r.adjusted(12, 6, -12, 0), Qt.AlignLeft | Qt.AlignTop, self.titulo.upper())
            r = r.adjusted(10, 24, -10, -8)
        else:
            r = r.adjusted(10, 8, -10, -8)
        try:
            self.pintar(p, r)
        except Exception:
            # Un fallo al dibujar un panel nunca debe tumbar la aplicación en plena carrera
            ahora = time.monotonic()
            if ahora - getattr(self, "_t_error", 0) > 10:
                self._t_error = ahora
                log.exception("Error dibujando %s", type(self).__name__)
        finally:
            p.end()

    def pintar(self, p, r):
        pass

    def texto(self, p, rect, txt, tam, color=None, align=Qt.AlignCenter, negrita=False, num=True):
        p.setFont(fuente(tam, negrita, num))
        p.setPen(color or C["texto"])
        p.drawText(rect, int(align), txt)

    def sin_datos(self, p, r, txt="Sin datos"):
        self.texto(p, r, txt, 14, C["muy_tenue"], num=False)


# ================================================================ cabecera
class Cabecera(Panel):
    def pintar(self, p, r):
        s = self.a.snap
        conectado = s is not None
        if not conectado:
            estado, color = "ESPERANDO A ASSETTO CORSA…", C["amarillo"]
        elif s.fuente == "demo":
            estado, color = "DEMO", C["morado"]
        elif s.graphics.status == mac.STATUS_PAUSE:
            estado, color = "PAUSA", C["amarillo"]
        elif s.graphics.status == mac.STATUS_REPLAY:
            estado, color = "REPETICIÓN", C["azul"]
        else:
            estado, color = "EN DIRECTO", C["verde"]
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(r.left() + 8, r.center().y()), 6, 6)
        self.texto(p, QRectF(r.left() + 22, r.top(), 260, r.height()), estado, 17, color, Qt.AlignLeft | Qt.AlignVCenter, True)
        if not conectado:
            self.texto(p, QRectF(r.left() + 300, r.top(), 900, r.height()),
                       "Arranca una sesión en AC (o ejecuta con --demo para probar)", 14, C["tenue"],
                       Qt.AlignLeft | Qt.AlignVCenter, num=False)
            return
        g, st = s.graphics, s.static
        info = f"{nombre_coche(st.carModel)}   ·   {nombre_coche(st.track)}" + \
               (f" ({st.trackConfiguration})" if st.trackConfiguration else "") + \
               f"   ·   {mac.SESIONES.get(g.session, '?')}   ·   perfil {self.a.perfil.nombre}"
        self.texto(p, QRectF(r.left() + 190, r.top(), r.width() * 0.5, r.height()), info, 14, C["tenue"],
                   Qt.AlignLeft | Qt.AlignVCenter, num=False)

        # Derecha: bandera, posición, vuelta, tiempo de sesión
        x = r.right()
        bandera = mac.BANDERAS.get(g.flag, "")
        if bandera:
            colores = {mac.FLAG_YELLOW: C["amarillo"], mac.FLAG_BLUE: C["azul"], mac.FLAG_BLACK: QColor("#000"),
                       mac.FLAG_WHITE: QColor("#fff"), mac.FLAG_CHECKERED: QColor("#fff"), mac.FLAG_PENALTY: C["rojo"]}
            cf = colores.get(g.flag, C["texto"])
            ancho = 170
            caja = QRectF(x - ancho, r.top() + 2, ancho, r.height() - 4)
            p.setPen(QPen(C["texto"], 1) if g.flag == mac.FLAG_BLACK else Qt.NoPen)
            p.setBrush(cf)
            p.drawRoundedRect(caja, 6, 6)
            self.texto(p, caja, "BANDERA " + bandera, 15,
                       QColor("#000") if cf.lightness() > 150 else QColor("#fff"), negrita=True)
            x -= ancho + 20
        bloques = []
        if g.position > 0:
            bloques.append(("POS", f"P{g.position}" + (f"/{st.numCars}" if st.numCars > 1 else "")))
        vuelta = f"{g.completedLaps + 1}" + (f"/{g.numberOfLaps}" if g.numberOfLaps > 0 else "")
        bloques.append(("VUELTA", vuelta))
        if g.sessionTimeLeft > 0 and not (g.session == mac.SESION_CARRERA and g.numberOfLaps > 0):
            seg = int(g.sessionTimeLeft / 1000)
            bloques.append(("QUEDA", f"{seg // 3600}:{(seg // 60) % 60:02d}:{seg % 60:02d}" if seg >= 3600
                            else f"{seg // 60}:{seg % 60:02d}"))
        if g.penaltyTime > 0:
            bloques.append(("PENAL.", f"{g.penaltyTime:.0f}s"))
        for etiqueta, valor in bloques:
            w = 120
            self.texto(p, QRectF(x - w, r.top() - 2, w, 14), etiqueta, 10, C["tenue"], Qt.AlignRight, num=False)
            self.texto(p, QRectF(x - w, r.top() + 10, w, r.height() - 10), valor, 24, C["texto"],
                       Qt.AlignRight | Qt.AlignVCenter, True)
            x -= w + 14


# =================================================================== motor
class Motor(Panel):
    titulo = "Motor"

    def pintar(self, p, r):
        s = self.a.snap
        if not s:
            return self.sin_datos(p, r)
        ph, st = s.physics, s.static
        max_rpm = st.maxRpm or 8000
        frac = ph.rpms / max_rpm

        # Luces de cambio
        n = 15
        esp = 4
        ancho = (r.width() - esp * (n - 1)) / n
        destello = frac > 0.97 and int(s.t * 8) % 2 == 0
        for i in range(n):
            umbral = 0.70 + 0.27 * i / (n - 1)
            if i < 5:
                col = C["verde"]
            elif i < 10:
                col = C["amarillo"]
            else:
                col = C["rojo"]
            if destello:
                col = C["azul"]
            encendida = frac >= umbral or destello
            p.setPen(Qt.NoPen)
            p.setBrush(col if encendida else mezclar(col, C["panel"], 0.85))
            p.drawRoundedRect(QRectF(r.left() + i * (ancho + esp), r.top(), ancho, 14), 3, 3)

        # Barra de RPM
        barra = QRectF(r.left(), r.top() + 22, r.width(), 8)
        p.setBrush(C["borde"])
        p.drawRoundedRect(barra, 4, 4)
        p.setBrush(C["rojo"] if frac > 0.95 else C["cian"])
        p.drawRoundedRect(QRectF(barra.left(), barra.top(), barra.width() * min(1, frac), barra.height()), 4, 4)

        # Marcha, velocidad, RPM
        cuerpo = QRectF(r.left(), barra.bottom() + 6, r.width(), r.bottom() - barra.bottom() - 6)
        marcha = {0: "R", 1: "N"}.get(ph.gear, str(ph.gear - 1))
        izq = QRectF(cuerpo.left(), cuerpo.top(), cuerpo.width() * 0.42, cuerpo.height())
        self.texto(p, izq, marcha, min(izq.height() * 0.95, 120), C["amarillo"] if frac > 0.95 else C["texto"], negrita=True)
        der = QRectF(izq.right(), cuerpo.top(), cuerpo.width() - izq.width(), cuerpo.height())
        h = der.height()
        self.texto(p, QRectF(der.left(), der.top(), der.width(), h * 0.5), f"{ph.speedKmh:.0f}", h * 0.42, C["texto"],
                   Qt.AlignRight | Qt.AlignBottom, True)
        self.texto(p, QRectF(der.left(), der.top() + h * 0.5, der.width(), 16), "km/h", 12, C["tenue"], Qt.AlignRight)
        self.texto(p, QRectF(der.left(), der.top() + h * 0.5 + 18, der.width(), h * 0.22), f"{ph.rpms:,} rpm".replace(",", "."),
                   h * 0.15, C["cian"], Qt.AlignRight)
        # Indicadores
        chips = []
        if ph.pitLimiterOn:
            chips.append(("LIMITADOR", C["amarillo"]))
        if s.static.hasDRS:
            chips.append(("DRS", C["verde"] if ph.drsEnabled else (C["amarillo"] if ph.drsAvailable else C["muy_tenue"])))
        if ph.turboBoost > 0.01:
            chips.append((f"TURBO {ph.turboBoost:.2f}", C["tenue"]))
        x = der.left()
        for txt, col in chips:
            w = 12 + len(txt) * 8
            caja = QRectF(x, cuerpo.bottom() - 20, w, 18)
            p.setPen(QPen(col, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(caja, 4, 4)
            self.texto(p, caja, txt, 11, col, negrita=True)
            x += w + 6


# ================================================================ pedales
class Pedales(Panel):
    titulo = "Mandos"

    def pintar(self, p, r):
        s = self.a.snap
        if not s:
            return self.sin_datos(p, r)
        ph = s.physics
        # En AC 'clutch' vale 1 con el embrague suelto; mostramos cuánto está pisado el pedal
        barras = [("EMB", 1 - ph.clutch, C["azul"]), ("FRENO", ph.brake, C["rojo"]), ("GAS", ph.gas, C["verde"])]
        alto = r.height() - 52
        ancho = min(34, r.width() * 0.11)
        for i, (etq, val, col) in enumerate(barras):
            x = r.left() + i * (ancho + 12)
            caja = QRectF(x, r.top() + 16, ancho, alto)
            p.setPen(Qt.NoPen)
            p.setBrush(C["borde"])
            p.drawRoundedRect(caja, 5, 5)
            v = max(0.0, min(1.0, val))
            p.setBrush(col)
            p.drawRoundedRect(QRectF(caja.left(), caja.bottom() - caja.height() * v, caja.width(), caja.height() * v), 5, 5)
            self.texto(p, QRectF(x - 10, r.top(), ancho + 20, 14), f"{v * 100:.0f}", 13, C["texto"], negrita=True)
            self.texto(p, QRectF(x - 10, caja.bottom() + 2, ancho + 20, 14), etq, 10, C["tenue"], num=False)

        # Volante
        vol = QRectF(r.left(), r.bottom() - 16, 3 * (ancho + 12) - 12, 10)
        p.setBrush(C["borde"])
        p.drawRoundedRect(vol, 5, 5)
        cx = vol.center().x()
        dx = max(-1, min(1, ph.steerAngle)) * vol.width() / 2
        p.setBrush(C["cian"])
        p.drawRoundedRect(QRectF(min(cx, cx + dx), vol.top(), abs(dx), vol.height()), 5, 5)
        p.setBrush(C["texto"])
        p.drawRect(QRectF(cx - 1, vol.top() - 2, 2, vol.height() + 4))

        # Ayudas y reglajes en vivo
        info = QRectF(r.left() + 3 * (ancho + 12) + 8, r.top(), r.width() - 3 * (ancho + 12) - 8, r.height())
        filas = []
        if ph.brakeBias > 0:
            filas.append(("Reparto freno", f"{ph.brakeBias * 100:.1f}% del."))
        filas.append(("TC", f"{ph.tc:.2f}" if ph.tc > 0 else "off"))
        filas.append(("ABS", f"{ph.abs:.2f}" if ph.abs > 0 else "off"))
        if ph.engineBrake:
            filas.append(("Freno motor", str(ph.engineBrake)))
        if s.static.hasERS or s.static.hasKERS:
            filas.append(("ERS", f"{ph.kersCharge * 100:.0f}%"))
        filas.append(("Ruedas fuera", str(ph.numberOfTyresOut)))
        filas.append(("Vel. máx vuelta", f"{self.a._vel_max:.0f} km/h"))
        h = min(22, info.height() / max(1, len(filas)))
        for i, (k, v) in enumerate(filas):
            y = info.top() + i * h
            self.texto(p, QRectF(info.left(), y, info.width(), h), k, 12, C["tenue"], Qt.AlignLeft | Qt.AlignVCenter, num=False)
            col = C["rojo"] if k == "Ruedas fuera" and ph.numberOfTyresOut >= 3 else C["texto"]
            self.texto(p, QRectF(info.left(), y, info.width(), h), v, 13, col, Qt.AlignRight | Qt.AlignVCenter, True)


# ================================================================ G-metro
class GMetro(Panel):
    titulo = "Fuerzas G"

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self.max_lat = 0.0
        self.max_lon = 0.0

    def pintar(self, p, r):
        s = self.a.snap
        if not s:
            return self.sin_datos(p, r)
        ph = s.physics
        lado = min(r.width() * 0.62, r.height())
        c = QPointF(r.left() + lado / 2, r.center().y())
        escala = lado / 2 / 2.5  # 2,5 g al borde
        p.setBrush(Qt.NoBrush)
        for g in (1, 2):
            p.setPen(QPen(C["borde"], 1, Qt.DashLine if g == 1 else Qt.SolidLine))
            p.drawEllipse(c, g * escala, g * escala)
        p.setPen(QPen(C["borde"], 1))
        p.drawLine(QPointF(c.x() - lado / 2, c.y()), QPointF(c.x() + lado / 2, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - lado / 2), QPointF(c.x(), c.y() + lado / 2))
        estela = list(self.a.g_estela)
        for i, (lat, lon) in enumerate(estela):
            alfa = (i + 1) / max(1, len(estela))
            col = QColor(C["cian"])
            col.setAlphaF(alfa * 0.5)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(c.x() + lat * escala, c.y() - lon * escala), 2.5, 2.5)
        lat, lon = ph.accG[0], ph.accG[2]
        p.setBrush(C["amarillo"])
        p.drawEllipse(QPointF(c.x() + lat * escala, c.y() - lon * escala), 6, 6)
        self.max_lat = max(self.max_lat, abs(lat))
        self.max_lon = max(self.max_lon, abs(lon))
        info = QRectF(c.x() + lado / 2 + 10, r.top(), r.right() - c.x() - lado / 2 - 10, r.height())
        filas = [("Lateral", f"{abs(lat):.2f} g"), ("Longit.", f"{lon:+.2f} g"),
                 ("Máx lat.", f"{self.max_lat:.2f} g"), ("Máx long.", f"{self.max_lon:.2f} g")]
        h = info.height() / 4
        for i, (k, v) in enumerate(filas):
            y = info.top() + i * h
            self.texto(p, QRectF(info.left(), y, info.width(), h * 0.45), k, 11, C["tenue"], Qt.AlignLeft | Qt.AlignBottom, num=False)
            self.texto(p, QRectF(info.left(), y + h * 0.45, info.width(), h * 0.55), v, 16, C["texto"], Qt.AlignLeft | Qt.AlignTop, True)


# ================================================================ tiempos
class Tiempos(Panel):
    titulo = "Cronometraje"

    def pintar(self, p, r):
        s, a = self.a.snap, self.a
        if not s:
            return self.sin_datos(p, r)
        g = s.graphics
        h = r.height()
        fila1 = QRectF(r.left(), r.top(), r.width(), h * 0.36)
        # Tiempo actual
        izq = QRectF(fila1.left(), fila1.top(), fila1.width() * 0.5, fila1.height())
        self.texto(p, QRectF(izq.left(), izq.top(), izq.width(), 14), "VUELTA ACTUAL", 10, C["tenue"], Qt.AlignLeft, num=False)
        col = C["texto"] if a.vuelta_valida else C["rojo"]
        self.texto(p, izq.adjusted(0, 14, 0, 0), fmt_tiempo(g.iCurrentTime), fila1.height() * 0.5, col,
                   Qt.AlignLeft | Qt.AlignVCenter, True)
        if not a.vuelta_valida:
            self.texto(p, QRectF(izq.left() + 110, izq.top(), 120, 14), "NO VÁLIDA", 10, C["rojo"], Qt.AlignLeft, True, num=False)
        # Delta
        der = QRectF(izq.right(), fila1.top(), fila1.width() * 0.5, fila1.height())
        d = a.delta_ms
        col = C["tenue"] if d is None else (C["verde"] if d < 0 else C["rojo"])
        self.texto(p, QRectF(der.left(), der.top(), der.width(), 14), "DELTA VS MEJOR", 10, C["tenue"], Qt.AlignRight, num=False)
        self.texto(p, der.adjusted(0, 14, 0, -14), fmt_delta(d), fila1.height() * 0.55, col, Qt.AlignRight | Qt.AlignVCenter, True)
        # Barra de delta ±1 s
        barra = QRectF(r.left(), fila1.bottom() + 2, r.width(), 8)
        p.setPen(Qt.NoPen)
        p.setBrush(C["borde"])
        p.drawRoundedRect(barra, 4, 4)
        if d is not None:
            v = max(-1.0, min(1.0, d / 1000))
            cx = barra.center().x()
            w = -v * barra.width() / 2  # a la derecha = más rápido
            p.setBrush(col)
            p.drawRoundedRect(QRectF(min(cx, cx + w), barra.top(), abs(w), barra.height()), 4, 4)
        p.setBrush(C["texto"])
        p.drawRect(QRectF(barra.center().x() - 1, barra.top() - 3, 2, barra.height() + 6))

        # Última / mejor / prevista / ideal
        fila2 = QRectF(r.left(), barra.bottom() + 8, r.width(), h * 0.2)
        ideal = sum(a.mejores_sectores) if all(a.mejores_sectores) else None
        datos = [("ÚLTIMA", fmt_tiempo(g.iLastTime), C["texto"]),
                 ("MEJOR", fmt_tiempo(a.mejor.tiempo_ms) if a.mejor else "--:--.---", C["morado"]),
                 ("PREVISTA", fmt_tiempo(a.tiempo_previsto) if a.tiempo_previsto else "--:--.---", C["cian"]),
                 ("IDEAL", fmt_tiempo(ideal), C["tenue"])]
        w = fila2.width() / len(datos)
        for i, (k, v, col) in enumerate(datos):
            caja = QRectF(fila2.left() + i * w, fila2.top(), w, fila2.height())
            self.texto(p, QRectF(caja.left(), caja.top(), caja.width(), 13), k, 10, C["tenue"], num=False)
            self.texto(p, caja.adjusted(0, 13, 0, 0), v, min(22, fila2.height() * 0.5), col, negrita=True)

        # Sectores
        fila3 = QRectF(r.left(), fila2.bottom() + 6, r.width(), r.bottom() - fila2.bottom() - 6)
        n = a.n_sectores
        w = (fila3.width() - (n - 1) * 8) / n
        ultima = a.vueltas[-1] if a.vueltas else None
        for i in range(n):
            caja = QRectF(fila3.left() + i * (w + 8), fila3.top(), w, fila3.height())
            actual = a.sectores_actuales[i]
            en_curso = i == g.currentSectorIndex
            mostrado = actual if actual else (ultima.sectores[i] if ultima and i < len(ultima.sectores) else None)
            mejor = a.mejores_sectores[i]
            if mostrado and mejor and mostrado <= mejor:
                fondo = C["morado"]
            elif mostrado and mejor and mostrado - mejor < 150:
                fondo = C["verde"]
            elif mostrado:
                fondo = C["amarillo"]
            else:
                fondo = C["borde"]
            if not actual:
                fondo = mezclar(fondo, C["panel"], 0.65)  # dato de la vuelta anterior
            p.setPen(QPen(C["texto"], 2) if en_curso else Qt.NoPen)
            p.setBrush(fondo)
            p.drawRoundedRect(caja, 6, 6)
            oscuro = fondo.lightness() > 140
            tc = QColor("#101010") if oscuro else C["texto"]
            self.texto(p, QRectF(caja.left() + 8, caja.top() + 3, caja.width(), 14), f"S{i + 1}", 11, tc, Qt.AlignLeft, True)
            self.texto(p, caja.adjusted(0, 6, 0, -12), fmt_tiempo(mostrado)[2:] if mostrado else "--.---",
                       min(22, caja.height() * 0.4), tc, negrita=True)
            self.texto(p, QRectF(caja.left(), caja.bottom() - 17, caja.width(), 14),
                       f"mejor {fmt_tiempo(mejor)[2:]}" if mejor else "", 10, tc, num=False)


# ================================================================= trazas
class Trazas(Panel):
    titulo = "Velocidad · Gas · Freno (últimos 20 s)"
    VENTANA = 20.0

    def pintar(self, p, r):
        datos = list(self.a.trazas)
        if len(datos) < 2:
            return self.sin_datos(p, r)
        t_fin = datos[-1][0]
        datos = [d for d in datos if d[0] >= t_fin - self.VENTANA]
        vmax = max(120.0, max(d[1] for d in datos) * 1.1)
        arriba = QRectF(r.left() + 30, r.top(), r.width() - 30, r.height() * 0.62)
        abajo = QRectF(r.left() + 30, arriba.bottom() + 6, r.width() - 30, r.height() - arriba.height() - 6)

        def x_de(t):
            return arriba.left() + (1 - (t_fin - t) / self.VENTANA) * arriba.width()

        p.setPen(QPen(C["borde"], 1))
        for frac in (0.25, 0.5, 0.75):
            y = arriba.bottom() - arriba.height() * frac
            p.drawLine(QPointF(arriba.left(), y), QPointF(arriba.right(), y))
            self.texto(p, QRectF(r.left(), y - 8, 26, 16), f"{vmax * frac:.0f}", 10, C["muy_tenue"], Qt.AlignRight)
        p.drawLine(QPointF(abajo.left(), abajo.bottom()), QPointF(abajo.right(), abajo.bottom()))

        def linea(valores, caja, maximo, color, relleno=False):
            camino = QPainterPath()
            for i, (t, v) in enumerate(valores):
                pt = QPointF(x_de(t), caja.bottom() - caja.height() * min(1, v / maximo))
                camino.moveTo(pt) if i == 0 else camino.lineTo(pt)
            if relleno:
                area = QPainterPath(camino)
                area.lineTo(QPointF(x_de(valores[-1][0]), caja.bottom()))
                area.lineTo(QPointF(x_de(valores[0][0]), caja.bottom()))
                col = QColor(color)
                col.setAlphaF(0.18)
                p.fillPath(area, col)
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(camino)

        linea([(d[0], d[1]) for d in datos], arriba, vmax, C["cian"], relleno=True)
        linea([(d[0], d[2]) for d in datos], abajo, 1.0, C["verde"])
        linea([(d[0], d[3]) for d in datos], abajo, 1.0, C["rojo"])


# ============================================================= neumáticos
class Neumaticos(Panel):
    titulo = "Neumáticos y frenos"

    def pintar(self, p, r):
        s, a = self.a.snap, self.a
        if not s:
            return self.sin_datos(p, r)
        ph, g, st, perf = s.physics, s.graphics, s.static, a.perfil
        cab = QRectF(r.left(), r.top() - 20, r.width(), 16)
        extra = g.tyreCompound
        if a.vueltas_neumatico is not None:
            extra += f"   ·   ~{a.vueltas_neumatico:.0f} vueltas de vida"
        self.texto(p, cab, extra, 11, C["tenue"], Qt.AlignRight, num=False)

        celda_w, celda_h = r.width() / 2, r.height() / 2
        v = ph.speedKmh / 3.6
        for w in range(4):
            col, fila = w % 2, w // 2
            celda = QRectF(r.left() + col * celda_w, r.top() + fila * celda_h, celda_w, celda_h).adjusted(4, 4, -4, -4)
            izquierda = col == 0
            rueda_w = min(62, celda.width() * 0.32)
            rueda = QRectF(celda.left() if izquierda else celda.right() - rueda_w, celda.top() + 4,
                           rueda_w, celda.height() - 8)

            # Estado de agarre: bloqueo / patinada en directo
            ratio = 0.0
            if v > 8:
                ratio = (ph.wheelAngularSpeed[w] * (st.tyreRadius[w] or 0.33) - v) / v
            borde = None
            if ratio < self.app.config.umbral_bloqueo and ph.brake > 0.1:
                borde = C["rojo"]
            elif ratio > self.app.config.umbral_patinada and ph.gas > 0.1:
                borde = C["naranja"]

            # Tres franjas: interior / medio / exterior (vistas desde arriba)
            temps = [ph.tyreTempO[w], ph.tyreTempM[w], ph.tyreTempI[w]] if izquierda else \
                    [ph.tyreTempI[w], ph.tyreTempM[w], ph.tyreTempO[w]]
            franja = rueda.width() / 3
            camino = QPainterPath()
            camino.addRoundedRect(rueda, 10, 10)
            p.save()
            p.setClipPath(camino)
            for i, t in enumerate(temps):
                p.fillRect(QRectF(rueda.left() + i * franja, rueda.top(), franja + 0.5, rueda.height()),
                           color_ventana(t, perf.temp_neum_min, perf.temp_neum_max, 25))
            p.restore()
            p.setPen(QPen(borde, 4) if borde else QPen(C["borde"], 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rueda, 10, 10)
            # Núcleo
            nucleo = ph.tyreCoreTemperature[w]
            caja_n = QRectF(rueda.left(), rueda.center().y() - 16, rueda.width(), 32)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 140))
            p.drawRoundedRect(caja_n.adjusted(4, 0, -4, 0), 5, 5)
            self.texto(p, caja_n, f"{nucleo:.0f}°", 18, C["texto"], negrita=True)
            for i, t in enumerate(temps):
                self.texto(p, QRectF(rueda.left() + i * franja, rueda.top() + 4, franja, 14), f"{t:.0f}", 10,
                           QColor("#101010"), negrita=True)

            # Datos a un lado
            info = QRectF(rueda.right() + 10, celda.top(), celda.width() - rueda_w - 10, celda.height()) if izquierda \
                else QRectF(celda.left(), celda.top(), celda.width() - rueda_w - 10, celda.height())
            al = Qt.AlignLeft if izquierda else Qt.AlignRight
            self.texto(p, QRectF(info.left(), info.top(), info.width(), 18), mac.RUEDAS[w], 13, C["tenue"], al, True)
            psi = ph.wheelsPressure[w]
            desgaste = ph.tyreWear[w]
            freno = ph.brakeTemp[w]
            filas = [
                (f"{psi:.1f} psi", color_ventana(psi, perf.psi_min, perf.psi_max, 2.5)),
                (f"{desgaste:.1f}% vida", C["verde"] if desgaste > self.app.config.desgaste_aviso
                 else (C["amarillo"] if desgaste > self.app.config.desgaste_critico else C["rojo"])),
                (f"freno {freno:.0f}°", color_ventana(freno, perf.temp_freno_min, perf.temp_freno_max, 250))
                if a.hay_temp_frenos else ("freno: no simulado", C["muy_tenue"]),
                (f"carga {ph.wheelLoad[w]:.0f} N", C["tenue"]),
            ]
            if a.snap.physics.tyreDirtyLevel[w] > 0.5:
                filas.append((f"sucio {ph.tyreDirtyLevel[w]:.1f}", C["naranja"]))
            h = min(20, (info.height() - 22) / len(filas))
            for i, (txt, c) in enumerate(filas):
                self.texto(p, QRectF(info.left(), info.top() + 22 + i * h, info.width(), h), txt, 13, c, al | Qt.AlignVCenter, i < 3)
            if not a.hay_temp_frenos:
                continue
            # Barra de temperatura de freno
            barra = QRectF(info.left(), info.bottom() - 8, info.width(), 5)
            p.setPen(Qt.NoPen)
            p.setBrush(C["borde"])
            p.drawRoundedRect(barra, 2, 2)
            p.setBrush(color_ventana(freno, perf.temp_freno_min, perf.temp_freno_max, 250))
            fw = barra.width() * min(1.0, freno / (perf.temp_freno_max * 1.3))
            p.drawRoundedRect(QRectF(barra.left() if izquierda else barra.right() - fw, barra.top(), fw, barra.height()), 2, 2)


# ============================================================ combustible
class Combustible(Panel):
    titulo = "Combustible y estrategia"

    def pintar(self, p, r):
        s, a = self.a.snap, self.a
        if not s:
            return self.sin_datos(p, r)
        ph, st = s.physics, s.static
        izq = QRectF(r.left(), r.top(), r.width() * 0.38, r.height())
        self.texto(p, QRectF(izq.left(), izq.top(), izq.width(), izq.height() * 0.55), f"{ph.fuel:.1f}",
                   izq.height() * 0.38, C["texto"], Qt.AlignLeft | Qt.AlignBottom, True)
        self.texto(p, QRectF(izq.left(), izq.top() + izq.height() * 0.55, izq.width(), 16), "litros", 12, C["tenue"],
                   Qt.AlignLeft, num=False)
        maximo = st.maxFuel or 100
        barra = QRectF(izq.left(), izq.bottom() - 12, izq.width() - 10, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(C["borde"])
        p.drawRoundedRect(barra, 4, 4)
        vc = a.vueltas_con_combustible
        col = C["verde"] if vc is None or vc > 5 else (C["amarillo"] if vc > 2 else C["rojo"])
        p.setBrush(col)
        p.drawRoundedRect(QRectF(barra.left(), barra.top(), barra.width() * min(1, ph.fuel / maximo), barra.height()), 4, 4)

        der = QRectF(izq.right(), r.top(), r.width() - izq.width(), r.height())
        filas = [
            ("Consumo / vuelta", f"{a.combustible_por_vuelta:.2f} L" if a.combustible_por_vuelta else "—", C["texto"]),
            ("Autonomía", f"{vc:.1f} vueltas" if vc is not None else "—", col),
            ("Vueltas restantes", f"{a.vueltas_restantes:.1f}" if a.vueltas_restantes is not None else "—", C["texto"]),
            ("Necesario (+margen)", f"{a.combustible_necesario:.1f} L" if a.combustible_necesario is not None else "—", C["texto"]),
        ]
        if a.combustible_sobra is not None:
            sobra = a.combustible_sobra
            filas.append(("Sobra" if sobra >= 0 else "FALTAN", f"{abs(sobra):.1f} L", C["verde"] if sobra >= 0 else C["rojo"]))
        est = getattr(self.app, "estrategia", None)
        if est is not None and est.plan is not None:
            plan = est.plan
            if plan.nombre == "Sin parar":
                txt = "sin parar"
            else:
                txt = f"V{plan.vuelta_desde}–{plan.vuelta_hasta}" + (f" +{plan.litros:.0f} L" if plan.litros else "") + \
                      (" + ruedas" if plan.neumaticos else "")
            filas.append(("Plan", txt, C["cian"]))
        h = der.height() / max(5, len(filas))
        for i, (k, v, c) in enumerate(filas):
            y = der.top() + i * h
            self.texto(p, QRectF(der.left(), y, der.width(), h), k, 12, C["tenue"], Qt.AlignLeft | Qt.AlignVCenter, num=False)
            self.texto(p, QRectF(der.left(), y, der.width(), h), v, 14, c, Qt.AlignRight | Qt.AlignVCenter, True)


# ======================================================== coche y entorno
class Coche(Panel):
    titulo = "Daños y entorno"

    def pintar(self, p, r):
        s = self.a.snap
        if not s:
            return self.sin_datos(p, r)
        ph, g = s.physics, s.graphics
        # Silueta con 5 zonas de daño
        alto = r.height()
        ancho = min(alto * 0.5, r.width() * 0.3)
        coche = QRectF(r.left() + 6, r.top(), ancho, alto)
        d = list(ph.carDamage)

        def col(v):
            if v < 0.5:
                return mezclar(C["verde"], C["panel"], 0.6)
            return mezclar(C["amarillo"], C["rojo"], v / 40)

        p.setPen(Qt.NoPen)
        tercio = coche.height() / 3
        zonas = [
            (QRectF(coche.left() + ancho * 0.1, coche.top(), ancho * 0.8, tercio), d[0]),
            (QRectF(coche.left() + ancho * 0.1, coche.bottom() - tercio, ancho * 0.8, tercio), d[1]),
            (QRectF(coche.left(), coche.top() + tercio, ancho * 0.28, tercio), d[2]),
            (QRectF(coche.right() - ancho * 0.28, coche.top() + tercio, ancho * 0.28, tercio), d[3]),
            (QRectF(coche.left() + ancho * 0.3, coche.top() + tercio, ancho * 0.4, tercio), d[4]),
        ]
        for rect, v in zonas:
            p.setBrush(col(v))
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 5, 5)
            if v >= 0.5:
                self.texto(p, rect, f"{v:.0f}", 11, QColor("#101010"), negrita=True)

        info = QRectF(coche.right() + 14, r.top(), r.right() - coche.right() - 14, r.height())
        filas = [("Aire", f"{ph.airTemp:.1f} °C"), ("Asfalto", f"{ph.roadTemp:.1f} °C"),
                 ("Agarre pista", f"{g.surfaceGrip * 100:.1f}%" if g.surfaceGrip > 0 else "—"),
                 ("Viento", f"{g.windSpeed:.0f} km/h" if g.windSpeed > 0 else "—")]
        h = info.height() / len(filas)
        for i, (k, v) in enumerate(filas):
            y = info.top() + i * h
            self.texto(p, QRectF(info.left(), y, info.width(), h), k, 12, C["tenue"], Qt.AlignLeft | Qt.AlignVCenter, num=False)
            self.texto(p, QRectF(info.left(), y, info.width(), h), v, 14, C["texto"], Qt.AlignRight | Qt.AlignVCenter, True)


# ================================================================== mapa
class Mapa(Panel):
    titulo = "Mapa  ·  ● bloqueo  ● patinada  ● salida"

    def pintar(self, p, r):
        s, a = self.a.snap, self.a
        puntos = [(i, q) for i, q in enumerate(a.mapa) if q is not None]
        if not s or len(puntos) < 10:
            return self.sin_datos(p, r, "El mapa se dibuja durante la primera vuelta")
        xs = [q[0] for _, q in puntos]
        zs = [q[1] for _, q in puntos]
        minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
        esc = min((r.width() - 20) / max(1e-3, maxx - minx), (r.height() - 20) / max(1e-3, maxz - minz))
        ox = r.left() + (r.width() - (maxx - minx) * esc) / 2
        oz = r.top() + (r.height() - (maxz - minz) * esc) / 2

        def pt(x, z):
            return QPointF(ox + (x - minx) * esc, oz + (z - minz) * esc)

        camino = QPainterPath()
        anterior = None
        for i, (x, z) in puntos:
            if anterior is None or i - anterior > 5:
                camino.moveTo(pt(x, z))
            else:
                camino.lineTo(pt(x, z))
            anterior = i
        if len(puntos) > N_BINS * 0.95:
            camino.lineTo(pt(*puntos[0][1]))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(C["borde"], 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(camino)
        p.setPen(QPen(C["muy_tenue"], 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(camino)

        # Límites de sector y meta
        for k in range(a.n_sectores):
            b = int(k / a.n_sectores * N_BINS)
            q = a.mapa[b]
            if q:
                p.setPen(Qt.NoPen)
                p.setBrush(C["texto"] if k == 0 else C["tenue"])
                c = pt(*q)
                p.drawEllipse(c, 4, 4)
                self.texto(p, QRectF(c.x() + 5, c.y() - 16, 40, 14), "META" if k == 0 else f"S{k + 1}", 10,
                           C["tenue"], Qt.AlignLeft, True, num=False)

        # Marcas de las dos últimas vueltas
        vuelta_actual = len(a.vueltas) + 1
        colores = {"bloqueo": C["rojo"], "patinada": C["naranja"], "salida": C["amarillo"]}
        for frac, tipo, rueda, n in list(a.marcas):
            if n < vuelta_actual - 1:
                continue
            q = a.mapa[min(N_BINS - 1, int(frac * N_BINS))]
            if q:
                col = QColor(colores[tipo])
                col.setAlphaF(1.0 if n == vuelta_actual else 0.45)
                p.setBrush(col)
                p.setPen(Qt.NoPen)
                p.drawEllipse(pt(*q), 5, 5)

        # Rivales
        clas = self.app.clasificacion
        if clas.activa:
            delante, detras = clas.cercanos()
            for r in clas.rivales.values():
                if r is clas.jugador or r.pitlane:
                    continue
                col = C["amarillo"] if r is delante else C["rojo"] if r is detras else C["tenue"]
                q = pt(r.x, r.z)
                p.setPen(QPen(C["fondo"], 1.5))
                p.setBrush(col)
                p.drawEllipse(q, 5.5, 5.5)
                self.texto(p, QRectF(q.x() + 6, q.y() - 7, 30, 14), str(r.pos), 10, col, Qt.AlignLeft, True)

        # Coche
        c = pt(s.graphics.carCoordinates[0], s.graphics.carCoordinates[2])
        p.setBrush(C["cian"])
        p.setPen(QPen(C["fondo"], 2))
        p.drawEllipse(c, 7, 7)
