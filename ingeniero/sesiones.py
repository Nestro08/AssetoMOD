"""Sesiones grabadas: listar, abrir y reconstruir las trazas de cada vuelta."""
import glob
import json
import os
from dataclasses import dataclass, field

from . import rutas
from .analisis import N_BINS, completar_traza

# columna del parquet -> canal de la traza
CANALES_PARQUET = {
    "t": "tiempo_vuelta_ms", "v": "velocidad_kmh", "gas": "acelerador", "freno": "freno", "volante": "volante",
    "marcha": "marcha", "glat": "g_lateral", "glon": "g_longitudinal", "x": "x", "z": "z", "rpm": "rpm",
}


@dataclass
class VueltaGuardada:
    numero: int
    tiempo_ms: int
    valida: bool
    boxes: bool
    traza: dict
    sectores: list = field(default_factory=list)


@dataclass
class SesionGuardada:
    ruta: str
    meta: dict
    vueltas: list
    datos: object  # DataFrame completo

    @property
    def titulo(self):
        m = self.meta
        return f"{m.get('inicio', '')[:16].replace('T', ' ')}  ·  {m.get('coche', '?')}  ·  {m.get('pista', '?')}"


def listar():
    """Sesiones guardadas, la más reciente primero: [(ruta_parquet, meta)]."""
    out = []
    for p in sorted(glob.glob(os.path.join(rutas.SESIONES, "sesion_*.parquet")), reverse=True):
        if ".tmp" in p:
            continue
        meta = {}
        j = p[:-len(".parquet")] + ".json"
        if os.path.isfile(j):
            try:
                with open(j, encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                pass
        out.append((p, meta))
    return out


def trazas_por_vuelta(df, meta=None):
    """Reconstruye la traza por distancia de cada vuelta completa."""
    import pandas as pd
    info = {v["vuelta"]: v for v in (meta or {}).get("vueltas", [])}
    vueltas = []
    for numero, grupo in df.groupby("vuelta"):
        if numero not in info:  # vuelta sin terminar
            continue
        datos = grupo.sort_values("t")
        bins = (datos["posicion_pista"].clip(0, 0.99999) * N_BINS).astype(int)
        # Evita que los últimos metros de la vuelta anterior (posición ≈ 1) cuenten como inicio
        datos = datos[~((datos["tiempo_vuelta_ms"] < 3000) & (datos["posicion_pista"] > 0.9))]
        bins = bins.loc[datos.index]
        primeros = datos.groupby(bins).head(1)
        bruta = {canal: [None] * N_BINS for canal in CANALES_PARQUET}
        for b, fila in zip(bins.loc[primeros.index], primeros.itertuples(index=False)):
            fila = fila._asdict()
            for canal, col in CANALES_PARQUET.items():
                if col in fila and pd.notna(fila[col]):
                    bruta[canal][b] = float(fila[col])
        if sum(x is not None for x in bruta["t"]) < N_BINS * 0.15:
            continue
        v = info[numero]
        traza = completar_traza(bruta, v["tiempo_ms"])
        sectores = [None] * 8
        for k in range(1, 9):
            s = v.get(f"sector_{k}")
            if s:
                mm, resto = s.split(":")
                sectores[k - 1] = int(round((int(mm) * 60 + float(resto)) * 1000))
        vueltas.append(VueltaGuardada(int(numero), int(v["tiempo_ms"]), bool(v.get("valida", True)),
                                      bool(v.get("boxes", False)), traza, [s for s in sectores if s]))
    return vueltas


def abrir(ruta_parquet):
    import pandas as pd
    df = pd.read_parquet(ruta_parquet)
    meta = {}
    j = ruta_parquet[:-len(".parquet")] + ".json"
    if os.path.isfile(j):
        with open(j, encoding="utf-8") as f:
            meta = json.load(f)
    elif "vuelta" in df:
        # Sesiones antiguas sin JSON: deducimos las vueltas completas del propio crono
        meta = {"vueltas": []}
        maximos = df.groupby("vuelta")["tiempo_vuelta_ms"].max()
        for n in list(maximos.index)[:-1]:
            meta["vueltas"].append({"vuelta": int(n), "tiempo_ms": int(maximos[n]), "valida": True,
                                    "boxes": bool(df[df.vuelta == n]["en_boxes"].max())})
    return SesionGuardada(ruta_parquet, meta, trazas_por_vuelta(df, meta), df)
