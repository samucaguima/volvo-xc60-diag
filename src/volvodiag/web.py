"""Painel ao vivo no navegador: servidor local, só no próprio computador.

Usa apenas a biblioteca padrão do Python e uma página sem recursos externos,
para funcionar sem internet no carro. A leitura do adaptador acontece numa
única linha de execução; o navegador só consulta o último instantâneo.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .elm327 import ElmError
from .health import evaluate
from .labels import name as label
from .live import LivePoller
from .storage import Store
from .transport import TransportError

HISTORY = 120  # pontos guardados por indicador para os gráficos


class Dashboard:
    def __init__(
        self,
        poller: LivePoller,
        store: Store | None,
        session_id: int | None,
        meta: dict[str, Any],
        interval: float = 1.0,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self.poller, self.store, self.session_id = poller, store, session_id
        self.meta, self.interval = meta, interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._state: dict[str, Any] = {"values": {}, "findings": [], "cycle": 0, "error": None, "ts": None}
        self._history: dict[str, list[tuple[float, float]]] = {}
        self.server = ThreadingHTTPServer((host, port), self._handler())
        self.port = self.server.server_address[1]
        self._threads: list[threading.Thread] = []

    # ---------------------------------------------------------- leitura
    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                values = self.poller.poll()
                now = time.time()
                if self.store and self.session_id:
                    self.store.add_samples(self.session_id, now, values)
                findings = evaluate({k: v for k, (v, _) in values.items()})
                with self._lock:
                    for k, (v, _) in values.items():
                        h = self._history.setdefault(k, [])
                        h.append((now, v))
                        del h[:-HISTORY]
                    self._state = {
                        "values": {k: {"valor": v, "unidade": u, "nome": label(k)} for k, (v, u) in values.items()},
                        "findings": [{"nivel": f.level, "item": f.item, "mensagem": f.message} for f in findings],
                        "cycle": self.poller.cycle,
                        "error": None,
                        "ts": now,
                    }
            except (ElmError, TransportError) as exc:
                with self._lock:
                    self._state["error"] = str(exc)
            self._stop.wait(max(0.0, self.interval - (time.monotonic() - t0)))

    def data(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._state,
                "historico": {k: [v for _, v in h] for k, h in self._history.items()},
                "meta": {**self.meta, "sessao": self.session_id, "ausentes": self.poller.missing},
            }

    # ---------------------------------------------------------- servidor
    def _handler(self) -> type[BaseHTTPRequestHandler]:
        dash = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code: int, body: bytes, ctype: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/":
                    self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                elif self.path == "/dados":
                    self._send(200, json.dumps(dash.data()).encode("utf-8"), "application/json")
                else:
                    self._send(404, b"nao encontrado", "text/plain")

            def log_message(self, *args: Any) -> None:
                pass  # sem registro de cada pedido no terminal

        return Handler

    def start(self) -> None:
        for target in (self._loop, self.server.serve_forever):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self.server.shutdown()
        self.server.server_close()
        for t in self._threads:
            t.join(timeout=5)


PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XC60 ao vivo</title>
<style>
:root{--bg:#f4f6f9;--card:#fff;--fg:#1d2330;--mut:#5b6474;--line:#dde2ea;--acc:#1f5fbf;
--ok:#1f7a3f;--warn:#a86400;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#0f1217;--card:#181d25;--fg:#e6e9ef;--mut:#9aa3b2;
--line:#2b313c;--acc:#7aa7ff;--ok:#5cc38a;--warn:#f0b35a;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:14px 16px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline}
h1{font-size:1.15rem;margin:0}.mut{color:var(--mut);font-size:.88rem}
main{padding:16px;max-width:1200px;margin:auto}
.sim{border:2px solid var(--warn);border-radius:8px;padding:8px 12px;margin-bottom:12px}
.err{border:2px solid var(--bad);border-radius:8px;padding:8px 12px;margin-bottom:12px;display:none}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tile .n{font-size:.8rem;color:var(--mut);min-height:2.2em}
.tile .v{font-size:1.7rem;font-weight:600;font-variant-numeric:tabular-nums}
.tile .u{font-size:.85rem;color:var(--mut);margin-left:4px}
canvas{width:100%;height:36px;display:block;margin-top:4px}
h2{font-size:1rem;margin:22px 0 8px}
.f{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--ok);
border-radius:8px;padding:8px 12px;margin-bottom:6px}
.f.atencao{border-left-color:var(--warn)}.f.alerta{border-left-color:var(--bad)}
.f b{margin-right:6px}
</style></head><body>
<header><h1>XC60 ao vivo</h1><span class="mut" id="meta">conectando...</span></header>
<main>
<div class="sim" id="sim" hidden><strong>Dados simulados.</strong> Nenhum carro conectado.</div>
<div class="err" id="err"></div>
<div class="grid" id="tiles"></div>
<h2>Avaliação</h2><div id="findings"></div>
<p class="mut">Limites gerais de mecânica, não especificações da Volvo. Encerre com Ctrl+C no terminal.</p>
<p class="mut" id="ausentes"></p>
</main>
<script>
const ORDER=["rpm","velocidade","temp_arrefecimento","pressao_turbo","tensao_modulo","tensao_adaptador",
"carga_bateria","temp_oleo","temp_oleo_volvo","carga_motor","temp_ar_admissao","borboleta","stft_b1","ltft_b1",
"maf","map","avanco_ignicao","nivel_combustivel","temp_ambiente","pressao_barometrica","tempo_motor_ligado",
"luz_injecao","qtd_codigos"];
const tiles={};
function tile(k,nome){const d=document.createElement("div");d.className="tile";
d.innerHTML='<div class="n"></div><div><span class="v">-</span><span class="u"></span></div><canvas></canvas>';
d.querySelector(".n").textContent=nome;document.getElementById("tiles").appendChild(d);tiles[k]=d;return d}
function spark(c,pts){const r=window.devicePixelRatio||1,w=c.clientWidth,h=c.clientHeight;
c.width=w*r;c.height=h*r;const x=c.getContext("2d");x.scale(r,r);if(pts.length<2)return;
let lo=Math.min(...pts),hi=Math.max(...pts);if(hi===lo){hi+=1;lo-=1}
x.strokeStyle=getComputedStyle(document.documentElement).getPropertyValue("--acc");x.lineWidth=1.6;x.beginPath();
pts.forEach((v,i)=>{const px=i/(pts.length-1)*w,py=h-2-(v-lo)/(hi-lo)*(h-4);i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke()}
const INTEIROS=new Set(["qtd_codigos","rpm","tempo_motor_ligado","velocidade"]);
function fmt(k,v){if(k==="luz_injecao")return v?"ACESA":"apagada";
if(INTEIROS.has(k)||Math.abs(v)>=100)return v.toFixed(0);return v.toFixed(1)}
async function tick(){try{const r=await fetch("/dados");const d=await r.json();
const m=d.meta;document.getElementById("sim").hidden=!m.simulado;
document.getElementById("meta").textContent=`${m.adaptador} · ${m.sessao?"gravando sessão "+m.sessao:"sem gravar"} · ciclo ${d.cycle}`;
const e=document.getElementById("err");e.style.display=d.error?"block":"none";e.textContent=d.error?"Falha de comunicação: "+d.error:"";
const keys=Object.keys(d.values).sort((a,b)=>{const ia=ORDER.indexOf(a),ib=ORDER.indexOf(b);return(ia<0?99:ia)-(ib<0?99:ib)});
for(const k of keys){const it=d.values[k];const t=tiles[k]||tile(k,it.nome);
t.querySelector(".v").textContent=fmt(k,it.valor);t.querySelector(".u").textContent=it.unidade;
spark(t.querySelector("canvas"),d.historico[k]||[])}
const f=document.getElementById("findings");f.replaceChildren(...d.findings.map(x=>{const el=document.createElement("div");
el.className="f "+x.nivel.normalize("NFD").replace(/[\\u0300-\\u036f]/g,"");
const b=document.createElement("b");b.textContent=x.item+":";el.append(b,x.mensagem);return el}));
document.getElementById("ausentes").textContent=m.ausentes.length?"Não oferecidos pelo carro: "+m.ausentes.join("; "):""
}catch(err){const e=document.getElementById("err");e.style.display="block";
e.textContent="Painel desconectado do volvodiag (o programa foi encerrado?)"}}
tick();setInterval(tick,1000);
</script></body></html>
"""
