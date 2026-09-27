"""Exportación a MoTeC i2 (.ld + .ldx con las balizas de vuelta).

El formato .ld no es público: esta implementación sigue la estructura
documentada por la comunidad (ldparser): cabecera de 0x6E2 bytes, evento,
circuito y vehículo, lista enlazada de metadatos de canal (124 bytes cada uno)
y a continuación los datos de cada canal en float32.
"""
import os
import struct
from datetime import datetime

import numpy as np

CABECERA = "<" + "I4x" "II" "20x" "I" "24x" "HHH" "I" "8s" "H" "H" "I" "4x" "16s" "16x" "16s" "16x" \
           "64s" "64s" "64x" "64s" "64x" "1024x" "I" "66x" "64s" "126x"
EVENTO = "<64s64s1024sH"
CIRCUITO = "<64s1034xH"
VEHICULO = "<64s128xI32s32s"
CANAL = "<" + "IIII" "H" "HHH" "hhhh" "32s" "8s" "12s" "40x"

PTR_EVENTO = struct.calcsize(CABECERA)  # 1762
PTR_CIRCUITO = PTR_EVENTO + struct.calcsize(EVENTO)
PTR_VEHICULO = PTR_CIRCUITO + struct.calcsize(CIRCUITO)
PTR_META = 0x3448  # donde MoTeC suele empezar los metadatos de canal
TAM_CANAL = struct.calcsize(CANAL)

RUEDAS_MOTEC = {"DI": "FL", "DD": "FR", "TI": "RL", "TD": "RR"}

# (columna, nombre, abreviatura, unidad, función de conversión)
CANALES = [
    ("velocidad_kmh", "Ground Speed", "Speed", "km/h", None),
    ("rpm", "Engine RPM", "RPM", "rpm", None),
    ("marcha", "Gear", "Gear", "", None),
    ("acelerador", "Throttle Pos", "Thr", "%", lambda x: x * 100),
    ("freno", "Brake Pos", "Brk", "%", lambda x: x * 100),
    ("embrague", "Clutch Pos", "Clu", "%", lambda x: (1 - x) * 100),
    ("volante", "Steering Angle", "Steer", "", None),
    ("g_lateral", "G Force Lat", "GLat", "G", None),
    ("g_longitudinal", "G Force Long", "GLong", "G", None),
    ("combustible", "Fuel Level", "Fuel", "l", None),
    ("vuelta", "Lap Number", "Lap", "", None),
    ("tiempo_vuelta_ms", "Lap Time Running", "LapT", "s", lambda x: x / 1000),
    ("delta_mejor_ms", "Delta Best", "Delta", "s", lambda x: x / 1000),
    ("posicion_pista", "Lap Distance Pct", "LapPct", "%", lambda x: x * 100),
    ("posicion", "Race Position", "Pos", "", None),
    ("ruedas_fuera", "Tyres Out", "TyOut", "", None),
    ("en_boxes", "In Pits", "Pit", "", None),
    ("x", "Car Coord X", "PosX", "m", None),
    ("z", "Car Coord Z", "PosZ", "m", None),
]
for _r, _m in RUEDAS_MOTEC.items():
    CANALES += [
        (f"temp_nucleo_{_r}", f"Tyre Temp Core {_m}", f"TTC{_m}", "C", None),
        (f"temp_int_{_r}", f"Tyre Temp Inner {_m}", f"TTI{_m}", "C", None),
        (f"temp_med_{_r}", f"Tyre Temp Centre {_m}", f"TTM{_m}", "C", None),
        (f"temp_ext_{_r}", f"Tyre Temp Outer {_m}", f"TTO{_m}", "C", None),
        (f"presion_{_r}", f"Tyre Pressure {_m}", f"TP{_m}", "psi", None),
        (f"desgaste_{_r}", f"Tyre Wear {_m}", f"TW{_m}", "%", None),
        (f"freno_temp_{_r}", f"Brake Temp {_m}", f"BT{_m}", "C", None),
        (f"carga_{_r}", f"Tyre Load {_m}", f"TL{_m}", "N", None),
        (f"suspension_{_r}", f"Susp Pos {_m}", f"SP{_m}", "mm", None),
    ]


def _b(texto, n):
    return (texto or "").encode("latin-1", "replace")[:n - 1]


def exportar(df, meta, ruta_ld, hz=20):
    """Escribe ruta_ld (.ld) y su .ldx. Devuelve las rutas."""
    df = df.sort_values("t").drop_duplicates("t")
    t = df["t"].to_numpy(dtype=float)
    if len(t) < 10:
        raise ValueError("Muy pocos datos para exportar")
    malla = np.arange(t[0], t[-1], 1.0 / hz)  # frecuencia constante, como exige MoTeC
    canales = []
    longitud = float(meta.get("longitud_pista") or 0)
    for col, nombre, corto, unidad, conv in CANALES:
        if col not in df:
            continue
        serie = df[col].astype(float).to_numpy()
        if conv:
            serie = conv(serie)
        valida = ~np.isnan(serie)
        if not valida.any():
            continue
        datos = np.interp(malla, t[valida], serie[valida])
        if col in ("marcha", "vuelta", "posicion", "ruedas_fuera", "en_boxes"):
            # Valores discretos: el más cercano, sin interpolar
            idx = np.clip(np.searchsorted(t, malla), 0, len(t) - 1)
            datos = np.nan_to_num(serie[idx])
        canales.append((nombre, corto, unidad, datos.astype(np.float32)))
    if longitud > 0 and "posicion_pista" in df:
        dist = np.interp(malla, t, df["posicion_pista"].to_numpy(dtype=float)) * longitud
        canales.append(("Lap Distance", "LapDist", "m", dist.astype(np.float32)))

    n = len(canales)
    ptr_datos = PTR_META + n * TAM_CANAL
    inicio = meta.get("inicio")
    fecha = datetime.fromisoformat(inicio) if inicio else datetime.now()
    with open(ruta_ld, "wb") as f:
        f.write(struct.pack(
            CABECERA, 0x40, PTR_META, ptr_datos, PTR_EVENTO, 1, 0x4240, 0xF, 0x1F44, b"ADL", 420, 0xADB0, n,
            fecha.strftime("%d/%m/%Y").encode(), fecha.strftime("%H:%M:%S").encode(),
            _b(meta.get("piloto", ""), 64), _b(meta.get("coche", ""), 64), _b(meta.get("pista", ""), 64),
            0xC81A4, _b("Ingeniero de carrera", 64)))
        f.seek(PTR_EVENTO)
        f.write(struct.pack(EVENTO, _b(meta.get("pista", ""), 64), _b("Sesion", 64),
                            _b(meta.get("configuracion", ""), 1024), PTR_CIRCUITO))
        f.seek(PTR_CIRCUITO)
        f.write(struct.pack(CIRCUITO, _b(meta.get("pista", ""), 64), PTR_VEHICULO))
        f.seek(PTR_VEHICULO)
        f.write(struct.pack(VEHICULO, _b(meta.get("coche", ""), 64), 0, b"Car", b""))
        # Metadatos de canal (lista doblemente enlazada)
        ptr = ptr_datos
        f.seek(PTR_META)
        for i, (nombre, corto, unidad, datos) in enumerate(canales):
            meta_ptr = PTR_META + i * TAM_CANAL
            anterior = meta_ptr - TAM_CANAL if i > 0 else 0
            siguiente = meta_ptr + TAM_CANAL if i < n - 1 else 0
            f.write(struct.pack(CANAL, anterior, siguiente, ptr, len(datos), 0x2EE1 + i, 0x07, 4, hz,
                                0, 1, 1, 0, _b(nombre, 32), _b(corto, 8), _b(unidad, 12)))
            ptr += datos.nbytes
        for _, _, _, datos in canales:
            f.write(datos.tobytes())

    ruta_ldx = os.path.splitext(ruta_ld)[0] + ".ldx"
    _escribir_ldx(ruta_ldx, df, meta)
    return ruta_ld, ruta_ldx


def _escribir_ldx(ruta, df, meta):
    """Balizas de vuelta (en microsegundos desde el inicio) para que i2 separe las vueltas."""
    t0 = float(df["t"].iloc[0])
    cambios = df.index[df["vuelta"].diff().fillna(0) > 0]
    balizas = [(float(df.loc[i, "t"]) - t0) * 1e6 for i in cambios]
    vueltas = meta.get("vueltas", [])
    validas = [v for v in vueltas if v.get("valida") and not v.get("boxes")]
    mejor = min(validas, key=lambda v: v["tiempo_ms"]) if validas else None
    lineas = ['<?xml version="1.0"?>',
              '<LDXFile Locale="English_United Kingdom.1252" DefaultLocale="C" Version="1.6">',
              ' <Layers>', '  <Layer>', '   <MarkerBlock>', '    <MarkerGroup Name="Beacons" Index="3">']
    for i, us in enumerate(balizas, 1):
        lineas.append(f'     <Marker Version="100" ClassName="BCN" Name="Manual.{i}" Flags="77" Time="{us:.3f}"/>')
    lineas += ['    </MarkerGroup>', '   </MarkerBlock>', '   <RangeBlock/>', '  </Layer>', '  <Details>',
               f'   <String Id="Total Laps" Value="{len(vueltas)}"/>']
    if mejor:
        ms = mejor["tiempo_ms"]
        lineas.append(f'   <String Id="Fastest Time" Value="{ms // 60000}:{(ms / 1000) % 60:06.3f}"/>')
        lineas.append(f'   <String Id="Fastest Lap" Value="{mejor["vuelta"]}"/>')
    lineas += ['  </Details>', ' </Layers>', '</LDXFile>']
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))


def leer(ruta_ld):
    """Lector mínimo (para verificar lo exportado): {nombre: (unidad, frecuencia, datos)} y cabecera."""
    with open(ruta_ld, "rb") as f:
        crudo = f.read()
    cab = struct.unpack_from(CABECERA, crudo, 0)
    ptr_meta, n = cab[1], cab[11]
    canales = {}
    ptr = ptr_meta
    while ptr:
        (ant, sig, pdatos, largo, _, dt_a, dt, freq, shift, mul, escala, dec,
         nombre, corto, unidad) = struct.unpack_from(CANAL, crudo, ptr)
        datos = np.frombuffer(crudo, dtype=np.float32, count=largo, offset=pdatos)
        valores = (datos / escala * 10.0 ** -dec + shift) * mul
        canales[nombre.rstrip(b"\0").decode("latin-1")] = (unidad.rstrip(b"\0").decode("latin-1"), freq, valores)
        ptr = sig
    return {"n_canales": n, "piloto": cab[14].rstrip(b"\0").decode(), "coche": cab[15].rstrip(b"\0").decode(),
            "pista": cab[16].rstrip(b"\0").decode(), "fecha": cab[12].rstrip(b"\0").decode()}, canales
