"""Panel web para móvil/tablet e ingeniero remoto (misma red local, protegido con PIN).

  GET  /                 página (una sola, sin dependencias externas)
  GET  /api/estado       datos en vivo (JSON)
  POST /api/preguntar    {"pin", "intencion"}  -> el ingeniero responde por radio
  POST /api/mensaje      {"pin", "texto"}      -> un ingeniero humano le habla al piloto por la radio
"""
import hmac
import json
import logging
import queue
import random
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import memoria_ac as mac
from .app import ACCIONES
from .ingeniero import apellido, fmt_delta, fmt_tiempo, nombre_coche

log = logging.getLogger(__name__)
MAX_CUERPO = 4096


def ips_locales():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips) or ["127.0.0.1"]


class ExtWeb:
    def __init__(self, app):
        self.app = app
        cfg = app.config
        if not cfg.web_pin:
            cfg.web_pin = f"{random.SystemRandom().randint(0, 9999):04d}"
            from . import ajustes
            ajustes.guardar(cfg)
        self.pin = cfg.web_pin
        self.puerto = cfg.web_puerto
        self.estado = {"conectado": False}
        self.entrantes = queue.Queue()
        self._t = 0.0
        self.error = None
        app.web = self
        extension = self

        class Manejador(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
                datos = cuerpo.encode("utf-8") if isinstance(cuerpo, str) else cuerpo
                self.send_response(codigo)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(datos)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(datos)

            def _pin_ok(self, pin):
                return hmac.compare_digest(str(pin or ""), extension.pin)

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/":
                    self._responder(200, PAGINA, "text/html; charset=utf-8")
                elif url.path == "/api/estado":
                    pin = parse_qs(url.query).get("pin", [""])[0]
                    if not self._pin_ok(pin):
                        self._responder(403, '{"error": "pin"}')
                        return
                    self._responder(200, json.dumps(extension.estado, ensure_ascii=False))
                else:
                    self._responder(404, '{"error": "no encontrado"}')

            def do_POST(self):
                largo = int(self.headers.get("Content-Length") or 0)
                if largo > MAX_CUERPO:
                    self._responder(413, '{"error": "demasiado grande"}')
                    return
                try:
                    datos = json.loads(self.rfile.read(largo) or b"{}")
                except ValueError:
                    self._responder(400, '{"error": "json"}')
                    return
                if not self._pin_ok(datos.get("pin")):
                    self._responder(403, '{"error": "pin"}')
                    return
                ruta = urlparse(self.path).path
                if ruta == "/api/preguntar" and datos.get("intencion") in ACCIONES:
                    extension.entrantes.put(("pregunta", datos["intencion"]))
                elif ruta == "/api/mensaje" and str(datos.get("texto", "")).strip():
                    extension.entrantes.put(("mensaje", str(datos["texto"]).strip()[:300]))
                else:
                    self._responder(400, '{"error": "petición"}')
                    return
                self._responder(200, '{"ok": true}')

        try:
            self.servidor = ThreadingHTTPServer(("0.0.0.0", self.puerto), Manejador)
            self.servidor.daemon_threads = True
            threading.Thread(target=self.servidor.serve_forever, name="web", daemon=True).start()
            log.info("Panel web en %s (PIN %s)", ", ".join(self.urls()), self.pin)
        except OSError as e:
            self.servidor = None
            self.error = f"No se pudo abrir el puerto {self.puerto}: {e}"
            log.warning(self.error)

    def urls(self):
        return [f"http://{ip}:{self.puerto}" for ip in ips_locales()]

    # ------------------------------------------------------------- ciclo
    def tick(self):
        while True:
            try:
                tipo, valor = self.entrantes.get_nowait()
            except queue.Empty:
                break
            if tipo == "pregunta":
                self.app.accion(valor)
            else:
                self.app.ingeniero.mensaje_remoto(valor)
        ahora = time.monotonic()
        if ahora - self._t >= 0.25:
            self._t = ahora
            try:
                self.estado = self._construir_estado()  # se reemplaza entero: seguro entre hilos
            except Exception:
                log.exception("Estado web")

    def _construir_estado(self):
        app = self.app
        a, c = app.analizador, app.clasificacion
        s = a.snap
        log_ing = [{"hora": m.hora, "texto": m.texto, "origen": m.origen, "prioridad": m.prioridad}
                   for m in list(app.ingeniero.log)[-25:]]
        if s is None:
            return {"conectado": False, "log": log_ing}
        ph, g, st = s.physics, s.graphics, s.static
        delta = app.delta_actual()
        est = {
            "conectado": True, "demo": s.fuente == "demo", "coche": nombre_coche(st.carModel),
            "pista": nombre_coche(st.track), "sesion": mac.SESIONES.get(g.session, "?"),
            "bandera": mac.BANDERAS.get(g.flag, ""),
            "pos": c.jugador.pos if c.activa and c.jugador else g.position,
            "total": len(c.orden) if c.activa else st.numCars,
            "vuelta": g.completedLaps + 1, "vueltas_total": g.numberOfLaps,
            "t_actual": fmt_tiempo(g.iCurrentTime), "ultima": fmt_tiempo(g.iLastTime),
            "mejor": fmt_tiempo(a.mejor.tiempo_ms) if a.mejor else "--:--.---",
            "delta": None if delta is None else round(delta / 1000, 2), "delta_txt": fmt_delta(delta),
            "velocidad": round(ph.speedKmh), "marcha": {0: "R", 1: "N"}.get(ph.gear, str(ph.gear - 1)),
            "rpm": ph.rpms, "gas": round(ph.gas, 2), "freno": round(ph.brake, 2),
            "combustible": round(ph.fuel, 1),
            "consumo": None if a.combustible_por_vuelta is None else round(a.combustible_por_vuelta, 2),
            "autonomia": None if a.vueltas_con_combustible is None else round(a.vueltas_con_combustible, 1),
            "sobra": None if a.combustible_sobra is None else round(a.combustible_sobra, 1),
            "restantes": None if a.vueltas_restantes is None else round(a.vueltas_restantes, 1),
            "neumaticos": [{"rueda": mac.RUEDAS[w], "nucleo": round(ph.tyreCoreTemperature[w]),
                            "psi": round(ph.wheelsPressure[w], 1), "vida": round(ph.tyreWear[w], 1),
                            "freno": round(ph.brakeTemp[w]) if a.hay_temp_frenos else None} for w in range(4)],
            "perfil": {"tmin": a.perfil.temp_neum_min, "tmax": a.perfil.temp_neum_max,
                       "pmin": a.perfil.psi_min, "pmax": a.perfil.psi_max},
            "log": log_ing,
        }
        est_ext = getattr(app, "estrategia", None)
        if est_ext is not None and est_ext.plan is not None:
            p = est_ext.plan
            est["plan"] = "Sin parar" if p.nombre == "Sin parar" else \
                f"{p.nombre}: vueltas {p.vuelta_desde}-{p.vuelta_hasta}" + (f", {p.litros:.0f} L" if p.litros else "")
        if c.activa and c.jugador:
            delante, detras = c.cercanos()
            for clave, r in (("delante", delante), ("detras", detras)):
                if r is not None:
                    gg = c.gap_con(r)
                    est[clave] = {"nombre": apellido(r.nombre), "gap": None if gg is None else round(abs(gg), 2),
                                  "tendencia": None if r.tendencia is None else round(r.tendencia, 2)}
            est["clasificacion"] = [{"pos": r.pos, "nombre": r.nombre, "yo": r is c.jugador,
                                     "int": None if r.intervalo is None else round(r.intervalo, 2),
                                     "ultima": fmt_tiempo(r.ultima), "box": r.pitlane} for r in c.orden[:24]]
        return est

    def cerrar(self):
        if self.servidor:
            self.servidor.shutdown()
            self.servidor.server_close()


PAGINA = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Ingeniero de carrera</title>
<style>
:root { --fondo:#0d0f13; --panel:#161920; --borde:#252a35; --texto:#e8eaf0; --tenue:#8a91a0;
  --verde:#35d07f; --rojo:#ff4d5e; --amarillo:#ffc940; --cian:#3ec1ff; --morado:#b36bff; }
* { box-sizing:border-box; }
body { margin:0; background:var(--fondo); color:var(--texto); font:15px/1.35 "Segoe UI",system-ui,sans-serif;
  padding:12px 16px 24px; }
.cab { display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; }
.cab .t { color:var(--tenue); font-size:13px; }
.estado { font-weight:700; }
.rej { display:grid; gap:10px; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); margin-top:10px; }
.p { background:var(--panel); border:1px solid var(--borde); border-radius:10px; padding:10px 12px; }
.p h3 { margin:0 0 6px; font-size:11px; letter-spacing:.06em; color:var(--tenue); text-transform:uppercase; }
.num { font-family:Bahnschrift,"DIN Alternate","Roboto Condensed",sans-serif; font-variant-numeric:tabular-nums; }
.grande { font-size:44px; font-weight:700; line-height:1; }
.fila { display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid #1e222b; }
.fila:last-child { border-bottom:0; }
.fila span:first-child { color:var(--tenue); }
.ruedas { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.rueda { border-radius:8px; padding:8px; text-align:center; background:#1c2029; }
.rueda b { font-size:22px; display:block; }
.botones { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:6px; }
button { background:#1f2430; color:var(--texto); border:1px solid var(--borde); border-radius:8px; padding:10px 6px;
  font:inherit; cursor:pointer; }
button:active { background:var(--cian); color:#000; }
.log { max-height:260px; overflow:auto; font-size:14px; }
.log div { padding:3px 0; border-bottom:1px solid #1e222b; }
.log .h { color:#4a505c; margin-right:6px; }
.remoto { display:flex; gap:6px; margin-top:8px; }
.remoto input { flex:1; min-width:0; background:#11141a; color:var(--texto); border:1px solid var(--borde);
  border-radius:8px; padding:10px; font:inherit; }
table { width:100%; border-collapse:collapse; font-size:13px; }
td { padding:3px 4px; border-bottom:1px solid #1e222b; }
tr.yo td { background:rgba(62,193,255,.18); font-weight:700; }
.bandera { padding:3px 10px; border-radius:6px; font-weight:700; color:#000; }
</style></head><body>
<div class="cab">
  <div><span class="estado" id="estado">Conectando…</span> <span class="t" id="info"></span></div>
  <div class="num" style="font-size:22px;font-weight:700" id="pos"></div>
</div>
<div class="rej">
  <div class="p"><h3>Tiempos</h3>
    <div style="display:flex;justify-content:space-between;align-items:flex-end">
      <div class="num grande" id="delta">--.--</div>
      <div class="num" style="text-align:right"><div style="font-size:26px" id="tact">--</div>
        <div class="t" id="vuelta"></div></div></div>
    <div class="fila"><span>Última</span><span class="num" id="ultima"></span></div>
    <div class="fila"><span>Mejor</span><span class="num" id="mejor" style="color:var(--morado)"></span></div>
    <div class="fila"><span>Coche</span><span class="num" id="coche"></span></div>
  </div>
  <div class="p"><h3>Rivales</h3>
    <div class="fila"><span>Delante</span><span class="num" id="delante">—</span></div>
    <div class="fila"><span>Detrás</span><span class="num" id="detras">—</span></div>
    <table id="clasif"></table>
  </div>
  <div class="p"><h3>Combustible y estrategia</h3>
    <div class="num grande" id="comb">--</div>
    <div class="fila"><span>Consumo / vuelta</span><span class="num" id="cons"></span></div>
    <div class="fila"><span>Autonomía</span><span class="num" id="auto"></span></div>
    <div class="fila"><span>Vueltas restantes</span><span class="num" id="rest"></span></div>
    <div class="fila"><span>Margen al final</span><span class="num" id="sobra"></span></div>
    <div class="fila"><span>Plan</span><span id="plan" style="color:var(--cian)"></span></div>
  </div>
  <div class="p"><h3>Neumáticos</h3><div class="ruedas" id="ruedas"></div></div>
  <div class="p" style="grid-column:1/-1"><h3>Radio</h3>
    <div class="botones" id="botones"></div>
    <div class="log" id="log" style="margin-top:8px"></div>
    <div class="remoto"><input id="msg" maxlength="300" placeholder="Ingeniero remoto: escribe y el piloto lo oirá por la radio">
      <button onclick="enviar()">Enviar</button></div>
  </div>
</div>
<script>
const PREGUNTAS = [["Combustible","combustible"],["Neumáticos","neumaticos"],["Tiempos","tiempos"],
  ["Rivales","rivales"],["Estrategia","estrategia"],["Curvas","curvas"],["Presiones","presiones"],
  ["Resumen","resumen"],["Repite","repite"],["Silencio","silencio"]];
let pin = new URLSearchParams(location.search).get("pin") || localStorage.getItem("pin_ing") || "";
localStorage.setItem("pin_ing", pin);
function pedirPin(){ pin = prompt("PIN del ingeniero (lo ves en Ajustes del programa):") || ""; localStorage.setItem("pin_ing", pin); }
if (!pin) pedirPin();
const $ = id => document.getElementById(id);
const b = $("botones");
PREGUNTAS.forEach(([t,i]) => { const e = document.createElement("button"); e.textContent = t;
  e.onclick = () => post("/api/preguntar", {intencion:i}); b.appendChild(e); });
function post(ruta, datos){ datos.pin = pin; return fetch(ruta, {method:"POST", headers:{"Content-Type":"application/json"},
  body: JSON.stringify(datos)}).then(r => { if (r.status === 403) pedirPin(); }); }
function enviar(){ const m = $("msg"); if (m.value.trim()) { post("/api/mensaje", {texto:m.value}); m.value = ""; } }
$("msg").addEventListener("keydown", e => { if (e.key === "Enter") enviar(); });
function colorVentana(v, a, b){ return v < a ? "#3b6cff" : v > b ? "#ff4d5e" : "#35d07f"; }
function esc(t){ return String(t).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
let firmaLog = "";
async function actualizar(){
  try {
    const r = await fetch("/api/estado?pin=" + encodeURIComponent(pin), {cache:"no-store"});
    if (r.status === 403) { $("estado").textContent = "PIN incorrecto"; pedirPin(); return; }
    const d = await r.json();
    if (!d.conectado) { $("estado").textContent = "Esperando a Assetto Corsa…"; $("estado").style.color = "var(--amarillo)"; }
    else {
      $("estado").textContent = d.demo ? "DEMO" : "EN DIRECTO"; $("estado").style.color = d.demo ? "var(--morado)" : "var(--verde)";
      $("info").innerHTML = esc(d.coche + " · " + d.pista + " · " + d.sesion) +
        (d.bandera ? ' <span class="bandera" style="background:var(--amarillo)">' + esc(d.bandera) + "</span>" : "");
      $("pos").textContent = "P" + d.pos + (d.total > 1 ? "/" + d.total : "");
      $("delta").textContent = d.delta_txt; $("delta").style.color = d.delta === null ? "var(--tenue)" : d.delta < 0 ? "var(--verde)" : "var(--rojo)";
      $("tact").textContent = d.t_actual; $("vuelta").textContent = "Vuelta " + d.vuelta + (d.vueltas_total ? "/" + d.vueltas_total : "");
      $("ultima").textContent = d.ultima; $("mejor").textContent = d.mejor;
      $("coche").textContent = d.velocidad + " km/h · " + d.marcha + " · " + d.rpm + " rpm";
      $("comb").textContent = d.combustible + " L";
      $("cons").textContent = d.consumo === null ? "—" : d.consumo + " L";
      $("auto").textContent = d.autonomia === null ? "—" : d.autonomia + " vueltas";
      $("rest").textContent = d.restantes === null ? "—" : d.restantes;
      $("sobra").textContent = d.sobra === null ? "—" : (d.sobra >= 0 ? "+" : "") + d.sobra + " L";
      $("sobra").style.color = d.sobra !== null && d.sobra < 0 ? "var(--rojo)" : "var(--verde)";
      $("plan").textContent = d.plan || "—";
      const g = (x, s) => x ? esc(x.nombre) + "  " + s + x.gap.toFixed(2) + (x.tendencia !== null ? " (" + (x.tendencia > 0 ? "+" : "") + x.tendencia.toFixed(1) + ")" : "") : "—";
      $("delante").textContent = g(d.delante, "+"); $("detras").textContent = g(d.detras, "-");
      $("clasif").innerHTML = (d.clasificacion || []).map(r => '<tr class="' + (r.yo ? "yo" : "") + '"><td>' + r.pos + "</td><td>" +
        esc(r.nombre) + '</td><td class="num">' + (r.int === null ? "" : "+" + r.int.toFixed(2)) + '</td><td class="num">' + r.ultima +
        "</td><td>" + (r.box ? "BOX" : "") + "</td></tr>").join("");
      $("ruedas").innerHTML = d.neumaticos.map(n => '<div class="rueda" style="border:2px solid ' + colorVentana(n.nucleo, d.perfil.tmin, d.perfil.tmax) +
        '"><div class="t">' + n.rueda + '</div><b class="num">' + n.nucleo + '°</b><div class="num" style="color:' +
        colorVentana(n.psi, d.perfil.pmin, d.perfil.pmax) + '">' + n.psi + ' psi</div><div class="num t">' + n.vida + "% vida" +
        (n.freno !== null ? " · freno " + n.freno + "°" : "") + "</div></div>").join("");
    }
    const firma = (d.log || []).map(m => m.hora + m.texto).join("|");
    if (firma !== firmaLog) {
      firmaLog = firma;
      const col = m => m.origen === "piloto" ? "var(--cian)" : m.origen === "remoto" ? "var(--morado)" : m.prioridad === 0 ? "var(--rojo)" : m.prioridad === 1 ? "var(--amarillo)" : "var(--texto)";
      const quien = m => m.origen === "piloto" ? "PILOTO" : m.origen === "remoto" ? "REMOTO" : "ING.";
      $("log").innerHTML = (d.log || []).slice().reverse().map(m => '<div><span class="h">' + m.hora + '</span><b style="color:' + col(m) + '">' +
        quien(m) + '</b> <span style="color:' + col(m) + '">' + esc(m.texto) + "</span></div>").join("");
    }
  } catch (e) { $("estado").textContent = "Sin conexión con el ordenador"; $("estado").style.color = "var(--rojo)"; }
}
setInterval(actualizar, 400); actualizar();
</script></body></html>"""
