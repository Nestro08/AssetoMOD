"""Memoria del ingeniero entre sesiones (SQLite en datos/ingeniero.db).

- Vuelta de referencia por coche + pista (con su traza completa): delta contra
  tu récord desde la primera vuelta y base del análisis curva a curva.
- Historial de todas las vueltas, consumo medio, pérdida en boxes por pista y
  cuánto sube la presión de cada coche en caliente.
"""
import json
import logging
import sqlite3
import threading
import zlib
from datetime import datetime

from . import rutas

log = logging.getLogger(__name__)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS referencias (
    coche TEXT, pista TEXT, config TEXT, tiempo_ms INTEGER, fecha TEXT, sectores TEXT, traza BLOB, fuente TEXT,
    PRIMARY KEY (coche, pista, config));
CREATE TABLE IF NOT EXISTS vueltas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, coche TEXT, pista TEXT, config TEXT, fecha TEXT, sesion TEXT,
    numero INTEGER, tiempo_ms INTEGER, valida INTEGER, boxes INTEGER, combustible REAL, sectores TEXT);
CREATE INDEX IF NOT EXISTS vueltas_cp ON vueltas (coche, pista, config);
CREATE TABLE IF NOT EXISTS consumos (
    coche TEXT, pista TEXT, config TEXT, litros_vuelta REAL, n INTEGER, fecha TEXT,
    PRIMARY KEY (coche, pista, config));
CREATE TABLE IF NOT EXISTS perdidas_boxes (
    pista TEXT, config TEXT, segundos REAL, n INTEGER, PRIMARY KEY (pista, config));
CREATE TABLE IF NOT EXISTS presiones (
    coche TEXT, eje TEXT, subida_psi REAL, n INTEGER, PRIMARY KEY (coche, eje));
"""


def comprimir_traza(traza):
    redondeada = {k: [round(x, 3) for x in v] for k, v in traza.items()}
    return zlib.compress(json.dumps(redondeada, separators=(",", ":")).encode("utf-8"))


def descomprimir_traza(blob):
    return json.loads(zlib.decompress(blob).decode("utf-8"))


class BaseDatos:
    def __init__(self, ruta=None):
        rutas.asegurar()
        self.ruta = ruta or rutas.BASE_DATOS
        self._cx = sqlite3.connect(self.ruta, check_same_thread=False)
        self._cx.executescript(ESQUEMA)
        self._cerrojo = threading.Lock()

    def _ejecutar(self, sql, params=()):
        with self._cerrojo, self._cx:
            return self._cx.execute(sql, params).fetchall()

    # ------------------------------------------------------------ referencias
    def referencia(self, coche, pista, config):
        filas = self._ejecutar("SELECT tiempo_ms, fecha, sectores, traza, fuente FROM referencias "
                               "WHERE coche=? AND pista=? AND config=?", (coche, pista, config))
        if not filas:
            return None
        t, fecha, sectores, traza, fuente = filas[0]
        return {"tiempo_ms": t, "fecha": fecha, "sectores": json.loads(sectores or "[]"),
                "traza": descomprimir_traza(traza), "fuente": fuente}

    def guardar_referencia(self, coche, pista, config, tiempo_ms, sectores, traza, fuente="sesion"):
        self._ejecutar("INSERT OR REPLACE INTO referencias VALUES (?,?,?,?,?,?,?,?)",
                       (coche, pista, config, tiempo_ms, datetime.now().isoformat(timespec="seconds"),
                        json.dumps(sectores), comprimir_traza(traza), fuente))

    def borrar_referencia(self, coche, pista, config):
        self._ejecutar("DELETE FROM referencias WHERE coche=? AND pista=? AND config=?", (coche, pista, config))

    def referencias(self):
        return self._ejecutar("SELECT coche, pista, config, tiempo_ms, fecha FROM referencias ORDER BY fecha DESC")

    # ---------------------------------------------------------------- vueltas
    def registrar_vuelta(self, coche, pista, config, sesion, v):
        self._ejecutar("INSERT INTO vueltas (coche, pista, config, fecha, sesion, numero, tiempo_ms, valida, boxes, "
                       "combustible, sectores) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (coche, pista, config, datetime.now().isoformat(timespec="seconds"), sesion, v.numero,
                        v.tiempo_ms, int(v.valida), int(v.boxes), v.combustible, json.dumps(v.sectores)))

    def estadisticas(self, coche, pista, config):
        filas = self._ejecutar("SELECT COUNT(*), MIN(CASE WHEN valida=1 AND boxes=0 THEN tiempo_ms END), "
                               "COUNT(DISTINCT sesion) FROM vueltas WHERE coche=? AND pista=? AND config=?",
                               (coche, pista, config))
        n, mejor, sesiones = filas[0]
        return {"vueltas": n or 0, "mejor_ms": mejor, "sesiones": sesiones or 0}

    # ------------------------------------------------ medias que se aprenden
    def _media(self, tabla, claves, columna, valor, n_max=20):
        where = " AND ".join(f"{k}=?" for k in claves)
        filas = self._ejecutar(f"SELECT {columna}, n FROM {tabla} WHERE {where}", tuple(claves.values()))
        if filas:
            anterior, n = filas[0]
            n = min(n, n_max)
            valor = (anterior * n + valor) / (n + 1)
            n += 1
        else:
            n = 1
        cols = list(claves) + [columna, "n"]
        valores = list(claves.values()) + [valor, n]
        if tabla == "consumos":
            cols.append("fecha")
            valores.append(datetime.now().isoformat(timespec="seconds"))
        self._ejecutar(f"INSERT OR REPLACE INTO {tabla} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                       tuple(valores))
        return valor

    def _leer(self, tabla, claves, columna):
        where = " AND ".join(f"{k}=?" for k in claves)
        filas = self._ejecutar(f"SELECT {columna}, n FROM {tabla} WHERE {where}", tuple(claves.values()))
        return filas[0] if filas else (None, 0)

    def consumo(self, coche, pista, config):
        return self._leer("consumos", {"coche": coche, "pista": pista, "config": config}, "litros_vuelta")[0]

    def aprender_consumo(self, coche, pista, config, litros):
        return self._media("consumos", {"coche": coche, "pista": pista, "config": config}, "litros_vuelta", litros)

    def perdida_boxes(self, pista, config):
        return self._leer("perdidas_boxes", {"pista": pista, "config": config}, "segundos")[0]

    def aprender_perdida_boxes(self, pista, config, segundos):
        return self._media("perdidas_boxes", {"pista": pista, "config": config}, "segundos", segundos, n_max=5)

    def subida_presion(self, coche, eje):
        return self._leer("presiones", {"coche": coche, "eje": eje}, "subida_psi")

    def aprender_subida_presion(self, coche, eje, psi):
        return self._media("presiones", {"coche": coche, "eje": eje}, "subida_psi", psi, n_max=10)

    def cerrar(self):
        with self._cerrojo:
            self._cx.close()


class ExtBaseDatos:
    """Extensión: carga la referencia al empezar y guarda récords, consumos y vueltas."""

    def __init__(self, app, bd=None):
        self.app = app
        self.bd = bd or BaseDatos()
        self.clave = None  # (coche, pista, config)
        self.sesion_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.estadisticas = None
        app.base_datos = self

    def tick(self):
        pass

    def eventos(self, eventos):
        a = self.app.analizador
        for ev in eventos:
            if ev.tipo == "sesion":
                self.clave = (ev.datos["coche"], ev.datos["pista"], ev.datos.get("config", ""))
                a.referencia = self.bd.referencia(*self.clave)
                self.estadisticas = self.bd.estadisticas(*self.clave)
                ev.datos["referencia"] = a.referencia
                ev.datos["estadisticas"] = self.estadisticas
                aprendido = self.bd.consumo(*self.clave)
                if aprendido and a.combustible_por_vuelta is None:
                    a.combustible_por_vuelta = aprendido  # hasta que midamos el de hoy
            elif ev.tipo == "vuelta" and self.clave:
                v = ev.datos["vuelta"]
                self.bd.registrar_vuelta(*self.clave, self.sesion_id, v)
                if v.valida and not v.boxes and 0.05 < v.combustible < 60 and v.numero > 1:
                    self.bd.aprender_consumo(*self.clave, v.combustible)
                ref = a.referencia
                if v.valida and not v.boxes and v.traza and (ref is None or v.tiempo_ms < ref["tiempo_ms"]):
                    ev.datos["record_personal"] = True
                    ev.datos["record_anterior"] = ref["tiempo_ms"] if ref else None
                    self.bd.guardar_referencia(*self.clave, v.tiempo_ms, v.sectores, v.traza, self.app.analizador.fuente)
                    a.referencia = {"tiempo_ms": v.tiempo_ms, "traza": v.traza, "sectores": v.sectores,
                                    "fecha": datetime.now().isoformat(timespec="seconds"), "fuente": "sesion"}

    def cerrar(self):
        self.bd.cerrar()
