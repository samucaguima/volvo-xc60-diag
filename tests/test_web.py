import json
import time
import urllib.request

from volvodiag.cli import main
from volvodiag.elm327 import Elm327
from volvodiag.live import LivePoller
from volvodiag.obd import ObdClient
from volvodiag.simulator import SimulatedTransport
from volvodiag.storage import Store
from volvodiag.uds import UdsClient
from volvodiag.web import Dashboard


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def _poller(volvo=True):
    elm = Elm327(SimulatedTransport())
    elm.initialize()
    return LivePoller(elm, ObdClient(elm), UdsClient(elm), volvo)


def test_dashboard_serves_page_and_data(tmp_path):
    store = Store(tmp_path / "h.sqlite", check_same_thread=False)
    sid = store.new_session("painel", None, "simulador", True)
    dash = Dashboard(_poller(), store, sid, {"adaptador": "simulador", "simulado": True}, interval=0.2, port=0)
    dash.start()
    try:
        deadline = time.time() + 5
        data = {}
        while time.time() < deadline:
            data = json.loads(_get(f"http://127.0.0.1:{dash.port}/dados")[2])
            if data["cycle"] >= 3:
                break
            time.sleep(0.1)
        status, ctype, html = _get(f"http://127.0.0.1:{dash.port}/")
    finally:
        dash.stop()

    assert status == 200 and ctype.startswith("text/html")
    assert b"XC60 ao vivo" in html and b"https://" not in html  # sem recursos externos
    assert data["cycle"] >= 3 and data["error"] is None
    assert data["values"]["rpm"]["nome"] == "Rotação do motor"
    assert data["values"]["carga_bateria"]["valor"] == 83
    assert len(data["historico"]["rpm"]) >= 3
    assert data["meta"]["simulado"] is True and data["meta"]["sessao"] == sid
    assert any(f["item"] == "Luz de injeção" for f in data["findings"])
    assert len(store.series(sid)["rpm"]) >= 3  # gravou no histórico pela linha de execução do painel
    store.close()


def test_dashboard_404(tmp_path):
    dash = Dashboard(_poller(False), None, None, {"adaptador": "x", "simulado": True}, interval=0.5, port=0)
    dash.start()
    try:
        try:
            _get(f"http://127.0.0.1:{dash.port}/outra")
            raise AssertionError("deveria ser 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        dash.stop()


def test_cli_painel(capsys, tmp_path):
    db = tmp_path / "h.sqlite"
    assert main(["--simulador", "--db", str(db), "painel", "--duracao", "1.5", "--intervalo", "0.2",
                 "--nao-abrir", "--porta-painel", "0", "--volvo"]) == 0
    out = capsys.readouterr().out
    assert "Painel aberto em http://127.0.0.1:" in out and "Sessão" in out and "Luz de injeção" in out
    store = Store(db)
    assert [r["kind"] for r in store.sessions()] == ["painel"]
    store.close()
