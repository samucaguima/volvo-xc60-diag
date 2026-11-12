"""Relatório HTML de uma sessão gravada (abre no navegador, sem internet)."""

from __future__ import annotations

from html import escape
from statistics import mean

from .health import evaluate
from .labels import name as label
from .storage import Store


CSS = """
:root{--bg:#fff;--fg:#1d2330;--mut:#5b6474;--line:#d9dee7;--card:#f6f8fb;--acc:#1f5fbf;
--ok:#1f7a3f;--warn:#a86400;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--fg:#e6e9ef;--mut:#9aa3b2;--line:#2b313c;
--card:#1a1f27;--acc:#7aa7ff;--ok:#5cc38a;--warn:#f0b35a;--bad:#ff8a80}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;}
main{max-width:980px;margin:auto}h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.15rem;margin:28px 0 8px}
.mut{color:var(--mut)}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);
padding:6px 8px;text-align:left;vertical-align:top}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.card h3{font-size:.95rem;margin:0 0 4px}.ok{color:var(--ok)}.atenção{color:var(--warn)}.alerta{color:var(--bad)}
svg{width:100%;height:70px}polyline{fill:none;stroke:var(--acc);stroke-width:2}.sim{border:2px solid var(--warn);
padding:8px 12px;border-radius:8px;margin:12px 0}
"""


def _spark(points: list[tuple[float, float, str]]) -> str:
    if len(points) < 2:
        return ""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1 = min(xs), max(xs) or 1
    y0, y1 = min(ys), max(ys)
    if y1 == y0:
        y1 = y0 + 1
    coords = " ".join(
        f"{(x - x0) / ((x1 - x0) or 1) * 300:.1f},{66 - (y - y0) / (y1 - y0) * 62:.1f}"
        for x, y in zip(xs, ys)
    )
    return f'<svg viewBox="0 0 300 70" preserveAspectRatio="none"><polyline points="{coords}"/></svg>'


def build(store: Store, session_id: int) -> str:
    s = store.session(session_id)
    if s is None:
        raise SystemExit(f"Sessão {session_id} não encontrada.")
    series = store.series(session_id)
    last = {k: pts[-1][1] for k, pts in series.items()}
    findings = evaluate(last)

    parts = [
        "<!doctype html><html lang=pt-BR><head><meta charset=utf-8>",
        "<meta name=viewport content='width=device-width,initial-scale=1'>",
        f"<title>Relatório XC60 · sessão {session_id}</title><style>{CSS}</style></head><body><main>",
        f"<h1>Relatório do XC60 · sessão {session_id}</h1>",
        f"<p class=mut>{escape(s['started_at'])} · {escape(s['kind'])} · VIN {escape(s['vin'] or '?')} · "
        f"adaptador {escape(s['adapter'] or '?')}</p>",
    ]
    if s["simulated"]:
        parts.append("<p class=sim><strong>Dados simulados.</strong> Esta sessão veio do simulador, não do carro.</p>")

    parts.append("<h2>Avaliação</h2><table><tr><th>Item</th><th>Situação</th><th>Detalhe</th></tr>")
    for f in findings:
        parts.append(f"<tr><td>{escape(f.item)}</td><td class='{escape(f.level)}'>{escape(f.level)}</td>"
                     f"<td>{escape(f.message)}</td></tr>")
    parts.append("</table><p class=mut>Limites gerais de mecânica, não especificações da Volvo.</p>")

    dtcs = store.dtcs(session_id)
    parts.append("<h2>Códigos de erro</h2>")
    if dtcs:
        parts.append("<table><tr><th>Origem</th><th>Código</th><th>Detalhe</th></tr>")
        for d in dtcs:
            parts.append(f"<tr><td>{escape(d['source'])}</td><td>{escape(d['code'])}</td>"
                         f"<td>{escape(d['detail'] or '')}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<p>Nenhum código registrado nesta sessão.</p>")

    parts.append("<h2>Leituras</h2><div class=grid>")
    for key, pts in sorted(series.items()):
        vals = [p[1] for p in pts]
        unit = pts[-1][2]
        parts.append(
            f"<div class=card><h3>{escape(label(key))}</h3>"
            f"<div class=mut>mín {min(vals):.1f} · média {mean(vals):.1f} · máx {max(vals):.1f} {escape(unit)}"
            f" · {len(vals)} leituras</div>{_spark(pts)}</div>"
        )
    parts.append("</div>")

    maint = store.maintenance()
    if maint:
        parts.append("<h2>Manutenção registrada</h2><table><tr><th>Data</th><th>km</th><th>Item</th><th>Notas</th></tr>")
        for m in maint:
            parts.append(f"<tr><td>{escape(m['date'])}</td><td>{m['km'] or ''}</td><td>{escape(m['item'])}</td>"
                         f"<td>{escape(m['notes'] or '')}</td></tr>")
        parts.append("</table>")
    parts.append("</main></body></html>")
    return "".join(parts)
