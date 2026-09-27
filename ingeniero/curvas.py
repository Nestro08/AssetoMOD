"""Análisis curva a curva.

1. Detecta las curvas en una traza (mínimos de velocidad con frenada o
   levantada, y curvas rápidas por G lateral).
2. Mide cada curva en cada vuelta: punto de frenada, velocidad de entrada,
   mínima y de salida, dónde se acelera a fondo, marcha y tiempo del tramo.
3. Compara con la referencia y genera consejos concretos.
"""
import statistics
from dataclasses import dataclass

from .analisis import N_BINS


@dataclass
class Curva:
    numero: int
    apice: int  # índice de la traza (punto más lento)
    inicio: int  # tramo de la curva: de la velocidad máxima de la recta anterior...
    fin: int  # ...a la de la recta siguiente. Los tramos cubren la vuelta entera sin solaparse.
    salida: int  # donde se vuelve a acelerar a fondo con el coche recto
    tipo: str  # "frenada" | "levantada" | "rapida"


def metros_por_punto(traza, longitud):
    if longitud and longitud > 100:
        return longitud / N_BINS
    # Sin longitud: la estimamos integrando la velocidad
    t, v = traza["t"], traza["v"]
    total = sum((v[i] + v[i + 1]) / 2 / 3.6 * (t[i + 1] - t[i]) / 1000 for i in range(N_BINS))
    return max(1.0, total / N_BINS)


def _suavizar(serie, n=2):
    out = []
    largo = len(serie)
    for i in range(largo):
        ventana = [serie[min(largo - 1, max(0, i + k))] for k in range(-n, n + 1)]
        out.append(sum(ventana) / len(ventana))
    return out


def _argmax(serie, a, b):
    return max(range(a, b + 1), key=lambda i: serie[i])


def detectar_curvas(traza, longitud):
    m = metros_por_punto(traza, longitud)
    v = _suavizar(traza["v"])
    freno, gas, glat = traza["freno"], traza["gas"], traza["glat"]
    w = max(3, int(40 / m))  # vecindario de un mínimo
    d = max(10, int(300 / m))  # distancia de frenada / aceleración que miramos

    apices = []
    for i in range(1, N_BINS):
        ventana = v[max(0, i - w):min(N_BINS, i + w + 1)]
        if v[i] > min(ventana) or (apices and i - apices[-1] <= w):
            continue
        caida = max(v[max(0, i - d):i + 1]) - v[i]
        subida = max(v[i:min(N_BINS + 1, i + d)]) - v[i]
        if caida > 10 and subida > 8:
            apices.append(i)
    # Curvas rápidas: G lateral alto sin mínimo de velocidad claro
    for i in range(w, N_BINS - w):
        g = abs(glat[i])
        if g > 1.3 and g >= max(abs(x) for x in glat[i - w:i + w + 1]) and all(abs(i - a) > 2 * w for a in apices):
            apices.append(i)
    apices.sort()

    # Curvas enlazadas (eses, chicanes): si entre dos vértices no se gana velocidad, son la misma curva
    fusionados = []
    for a in apices:
        if fusionados:
            b = fusionados[-1]
            pico = max(v[b:a + 1])
            if pico - max(v[a], v[b]) < 8:
                if v[a] < v[b]:
                    fusionados[-1] = a
                continue
        fusionados.append(a)
    apices = fusionados

    # Límites de los tramos: punto más rápido entre vértices consecutivos
    limites = [0] + [_argmax(v, a, b) for a, b in zip(apices, apices[1:])] + [N_BINS]
    curvas = []
    for n, a in enumerate(apices, 1):
        ini, fin = limites[n - 1], limites[n]
        tipo = "rapida"
        if any(freno[j] > 0.1 for j in range(max(ini, a - d), a + 1)):
            tipo = "frenada"
        elif any(gas[j] < 0.9 for j in range(max(ini, a - d), a + 1)):
            tipo = "levantada"
        salida = a
        while salida < fin - 1 and not (gas[salida] >= 0.95 and abs(glat[salida]) < 0.6):
            salida += 1
        curvas.append(Curva(n, a, ini, fin, salida, tipo))
    return curvas


def medir(traza, c: Curva, m):
    """Métricas de una curva en una vuelta."""
    t, v, freno, gas, marcha = traza["t"], traza["v"], traza["freno"], traza["gas"], traza["marcha"]
    # Punto de frenada: primer punto del tramo con freno antes del vértice
    frenada = next((j for j in range(c.inicio, c.apice + 1) if freno[j] > 0.1), None)
    # El punto más lento de esta vuelta puede no coincidir con el de la referencia: lo buscamos cerca
    zona = range(max(c.inicio, c.apice - int(80 / m)), min(c.fin, c.apice + int(80 / m)) + 1)
    i_min = min(zona, key=lambda i: v[i])
    gas_pleno = next((j for j in range(i_min, c.fin + 1) if gas[j] >= 0.9), None)
    fin_salida = min(c.fin, c.salida + max(1, int(30 / m)))
    marchas = [marcha[i] for i in zona if marcha[i] >= 0.5]  # el punto muerto al cambiar no cuenta
    return {
        "tiempo_ms": t[c.fin] - t[c.inicio],
        "frenada_m": None if frenada is None else (c.apice - frenada) * m,  # metros antes del vértice
        "freno_max": max(freno[i] for i in range(c.inicio, c.apice + 1)),
        "v_entrada": v[frenada] if frenada is not None else v[c.inicio],
        "v_min": v[i_min],
        "v_salida": v[fin_salida],
        "gas_m": None if gas_pleno is None else (gas_pleno - c.apice) * m,  # metros después del vértice
        "marcha_min": int(round(min(marchas))) if marchas else 0,
    }


def consejos_curva(mv, mr):
    """Consejos (texto) comparando la vuelta (mv) con la referencia (mr), de más a menos importante."""
    c = []
    antes = None
    if mv["frenada_m"] is not None and mr["frenada_m"] is not None:
        df = mv["frenada_m"] - mr["frenada_m"]  # + = frenas antes
        if df > 8 and mv["v_min"] <= mr["v_min"] + 1:
            antes = f"frenas {df:.0f} metros antes"
        elif df < -8 and mv["v_min"] < mr["v_min"] - 2:
            c.append(f"frenas {-df:.0f} metros más tarde y te pasas")
    elif mv["frenada_m"] is not None and mr["frenada_m"] is None:
        c.append("frenas donde en tu referencia solo levantabas")
    dv = mv["v_min"] - mr["v_min"]
    if dv < -3:
        c.append(f"pasas {-dv:.0f} kilómetros por hora más lento por el vértice")
    ds = mv["v_salida"] - mr["v_salida"]
    if dv > 3 and ds < -3:
        c.append("entras demasiado rápido y estropeas la salida")
    elif ds < -4:
        c.append(f"sales {-ds:.0f} kilómetros por hora más lento")
    if mv["gas_m"] is not None and mr["gas_m"] is not None and mv["gas_m"] - mr["gas_m"] > 12:
        c.append(f"aceleras a fondo {mv['gas_m'] - mr['gas_m']:.0f} metros más tarde")
    if antes:
        c.append(antes)
    # La marcha solo se menciona si no hay otra explicación (con datos reales es un dato ruidoso)
    if not c and 0 < mv["marcha_min"] < mr["marcha_min"]:
        c.append("reduces una marcha de más")
    elif not c and mv["marcha_min"] > mr["marcha_min"] > 0:
        c.append("vas una marcha más larga que en tu referencia")
    return c


def comparar(traza, ref, curvas, longitud):
    """Resultados por curva ordenados por tiempo perdido (mayor primero)."""
    m = metros_por_punto(ref, longitud)
    out = []
    for c in curvas:
        mv, mr = medir(traza, c, m), medir(ref, c, m)
        perdida = mv["tiempo_ms"] - mr["tiempo_ms"]
        consejos = consejos_curva(mv, mr)
        if perdida > 1500:  # tanto tiempo no es técnica: salida de pista, trompo o tráfico
            consejos = ["error grande o tráfico: no es de técnica"] + consejos[:1]
        out.append({"curva": c.numero, "tipo": c.tipo, "perdida_ms": perdida,
                    "vuelta": mv, "ref": mr, "consejos": consejos, "frac": c.apice / N_BINS})
    return sorted(out, key=lambda r: -r["perdida_ms"])


class ExtCurvas:
    """Extensión: analiza cada vuelta curva a curva contra la referencia."""

    def __init__(self, app):
        self.app = app
        self.curvas = []
        self._traza_curvas = None  # traza con la que se detectaron las curvas
        self.ultimo = None  # (número de vuelta, resultados)
        self.historial = {}  # curva -> [pérdidas ms]
        app.curvas = self
        app.ingeniero.curvas = self

    def tick(self):
        pass

    def cerrar(self):
        pass

    def _guia(self):
        a = self.app.analizador
        if a.referencia:
            return a.referencia["traza"], "referencia"
        if a.mejor and a.mejor.traza:
            return a.mejor.traza, "mejor de la sesión"
        return None, None

    def _actualizar_curvas(self):
        guia, _ = self._guia()
        if guia is not None and guia is not self._traza_curvas:
            self.curvas = detectar_curvas(guia, self.app.analizador.longitud_pista)
            self._traza_curvas = guia
        return guia

    def eventos(self, eventos):
        for ev in eventos:
            if ev.tipo == "sesion":
                self.curvas, self._traza_curvas, self.ultimo, self.historial = [], None, None, {}
            elif ev.tipo == "vuelta":
                v = ev.datos["vuelta"]
                guia = self._actualizar_curvas()
                if guia is None or v.traza is None or v.boxes or v.traza is guia or not self.curvas:
                    # Si esta vuelta es la nueva referencia, se analiza contra la anterior la próxima vez
                    self._actualizar_curvas()
                    continue
                res = comparar(v.traza, guia, self.curvas, self.app.analizador.longitud_pista)
                self.ultimo = (v.numero, res)
                for r in res:
                    self.historial.setdefault(r["curva"], []).append(r["perdida_ms"])
                ev.datos["curvas"] = res
                self._actualizar_curvas()  # por si la vuelta ha pasado a ser la referencia

    def puntos_debiles(self, n=3):
        """Curvas donde más tiempo pierdes de media en la sesión."""
        medias = [(c, statistics.mean(p), len(p)) for c, p in self.historial.items() if p]
        return sorted([x for x in medias if x[1] > 50], key=lambda x: -x[1])[:n]
