"""Graba la sesión y la exporta: Parquet (telemetría completa), JSON (datos de
la sesión y vueltas) y Excel (hoja de vueltas + telemetría a 5 Hz).

Se autoguarda cada minuto en segundo plano y todas las escrituras son atómicas,
así que un cierre brusco nunca deja archivos corruptos.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime

from . import rutas
from .analisis import Analizador
from .memoria_ac import RUEDAS

log = logging.getLogger(__name__)
AUTOGUARDADO_S = 60.0
HZ_EXCEL = 5


class Grabador:
    def __init__(self, analizador: Analizador, hz=20):
        self.a = analizador
        self.hz = hz
        self.periodo = 1.0 / hz
        self.filas = []
        self.meta = {}
        self._t0 = None
        self._t_ultima = 0.0
        self._t_autoguardado = time.monotonic()
        self._guardando = threading.Lock()
        self.inicio = datetime.now()
        self.base = None

    def registrar(self, snap):
        if snap.graphics.status != 2:  # solo en directo
            return
        if snap.t - self._t_ultima < self.periodo:
            return
        self._t_ultima = snap.t
        if self._t0 is None:
            self._t0 = snap.t
            st = snap.static
            self.meta = {
                "coche": st.carModel, "pista": st.track, "configuracion": st.trackConfiguration,
                "longitud_pista": st.trackSPlineLength, "piloto": f"{st.playerName} {st.playerSurname}".strip(),
                "sectores": st.sectorCount, "inicio": self.inicio.isoformat(timespec="seconds"),
                "fuente": snap.fuente, "hz": self.hz,
            }
        ph, gr = snap.physics, snap.graphics
        fila = {
            "t": round(snap.t - self._t0, 3),
            "hora": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "vuelta": gr.completedLaps + 1,
            "posicion_pista": round(gr.normalizedCarPosition, 5),
            "tiempo_vuelta_ms": gr.iCurrentTime,
            "delta_mejor_ms": None if self.a.delta_ms is None else round(self.a.delta_ms),
            "sector": gr.currentSectorIndex + 1,
            "posicion": gr.position,
            "velocidad_kmh": round(ph.speedKmh, 2),
            "rpm": ph.rpms,
            "marcha": ph.gear - 1,
            "acelerador": round(ph.gas, 3),
            "freno": round(ph.brake, 3),
            "embrague": round(ph.clutch, 3),
            "volante": round(ph.steerAngle, 3),
            "g_lateral": round(ph.accG[0], 3),
            "g_longitudinal": round(ph.accG[2], 3),
            "combustible": round(ph.fuel, 3),
            "ruedas_fuera": ph.numberOfTyresOut,
            "bandera": gr.flag,
            "en_boxes": int(bool(gr.isInPitLane or gr.isInPit)),
            "x": round(gr.carCoordinates[0], 2),
            "z": round(gr.carCoordinates[2], 2),
        }
        for i, r in enumerate(RUEDAS):
            fila[f"temp_nucleo_{r}"] = round(ph.tyreCoreTemperature[i], 1)
            fila[f"temp_int_{r}"] = round(ph.tyreTempI[i], 1)
            fila[f"temp_med_{r}"] = round(ph.tyreTempM[i], 1)
            fila[f"temp_ext_{r}"] = round(ph.tyreTempO[i], 1)
            fila[f"presion_{r}"] = round(ph.wheelsPressure[i], 2)
            fila[f"desgaste_{r}"] = round(ph.tyreWear[i], 2)
            fila[f"freno_temp_{r}"] = round(ph.brakeTemp[i], 1)
            fila[f"carga_{r}"] = round(ph.wheelLoad[i], 0)
            fila[f"suspension_{r}"] = round(ph.suspensionTravel[i] * 1000, 1)  # mm
        self.filas.append(fila)

        if time.monotonic() - self._t_autoguardado > AUTOGUARDADO_S:
            self._t_autoguardado = time.monotonic()
            filas, meta = list(self.filas), self._meta_completa()
            threading.Thread(target=self._guardar_rapido, args=(filas, meta), daemon=True).start()

    def _meta_completa(self):
        meta = dict(self.meta)
        meta["vueltas"] = self._tabla_vueltas()
        meta["fin"] = datetime.now().isoformat(timespec="seconds")
        return meta

    def _tabla_vueltas(self):
        filas = []
        for v in self.a.vueltas:
            f = {
                "vuelta": v.numero,
                "tiempo": _fmt(v.tiempo_ms),
                "tiempo_ms": v.tiempo_ms,
                "valida": v.valida,
                "boxes": v.boxes,
                "posicion": v.posicion,
                "combustible_usado": round(v.combustible, 3),
                "combustible_fin": round(v.combustible_fin, 2),
                "edad_neumaticos": v.edad_neumaticos,
                "vel_max": round(v.vel_max, 1),
                "salidas_pista": v.salidas,
            }
            for i, s in enumerate(v.sectores):
                f[f"sector_{i + 1}"] = _fmt(s) if s else None
            for i, r in enumerate(RUEDAS):
                f[f"temp_media_{r}"] = round((v.temp_i[i] + v.temp_m[i] + v.temp_o[i]) / 3, 1)
                f[f"presion_media_{r}"] = round(v.presion[i], 2)
                f[f"desgaste_{r}"] = round(v.desgaste[i], 2)
                f[f"freno_max_{r}"] = round(v.temp_freno_max[i], 0)
                f[f"bloqueos_{r}"] = v.bloqueos[i]
                f[f"patinadas_{r}"] = v.patinadas[i]
            filas.append(f)
        return filas

    def _rutas(self):
        if self.base is None:
            rutas.asegurar()
            self.base = os.path.join(rutas.SESIONES, "sesion_" + self.inicio.strftime("%Y%m%d_%H%M%S"))
        return self.base

    def _guardar_rapido(self, filas, meta):
        """Parquet + JSON (rápido; es lo que usa el autoguardado)."""
        import pandas as pd
        with self._guardando:
            base = self._rutas()
            creados, df = [], None
            try:
                df = pd.DataFrame(filas)
                rutas.escribir_atomico(base + ".parquet", lambda p: df.to_parquet(p, index=False))
                creados.append(base + ".parquet")
            except Exception:
                log.exception("No se pudo guardar el parquet")
            try:
                def escribir(p):
                    with open(p, "w", encoding="utf-8") as f:
                        json.dump(meta, f, ensure_ascii=False, indent=1)
                rutas.escribir_atomico(base + ".json", escribir)
                creados.append(base + ".json")
            except Exception:
                log.exception("No se pudo guardar el JSON")
            return creados, df

    def guardar(self):
        """Guardado final. Devuelve la lista de archivos creados."""
        if not self.filas:
            return []
        import pandas as pd
        creados, tele = self._guardar_rapido(list(self.filas), self._meta_completa())
        base = self._rutas()
        if tele is None:
            return creados
        try:
            vueltas = pd.DataFrame(self._tabla_vueltas())
            paso = max(1, self.hz // HZ_EXCEL)

            def escribir(p):
                with pd.ExcelWriter(p, engine="openpyxl") as xl:
                    vueltas.to_excel(xl, sheet_name="Vueltas", index=False)
                    tele.iloc[::paso].to_excel(xl, sheet_name=f"Telemetria {HZ_EXCEL}Hz", index=False)
            with self._guardando:
                rutas.escribir_atomico(base + ".xlsx", escribir)
            creados.append(base + ".xlsx")
        except Exception:
            log.exception("No se pudo guardar el Excel")
        return creados


def _fmt(ms):
    if not ms:
        return None
    ms = int(ms)
    return f"{ms // 60000}:{(ms // 1000) % 60:02d}.{ms % 1000:03d}"
