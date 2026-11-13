"""Testes de regressão dos achados da revisão de código."""

import json
import socket
import time
import urllib.request
from datetime import date

import pytest

from volvodiag import modules
from volvodiag.cli import Session, build_parser, main
from volvodiag.elm327 import Elm327, ElmError
from volvodiag.live import LivePoller
from volvodiag.obd import ObdClient
from volvodiag.simulator import SimulatedCar, SimulatedTransport
from volvodiag.storage import Store, parse_date
from volvodiag.trends import due_list
from volvodiag.uds import UdsClient
from volvodiag.web import PAGE, Dashboard


def _recording(transport):
    sent = []
    orig = transport.write

    def write(data, keep_input=False):
        sent.append(data.decode().strip())
        orig(data, keep_input)

    transport.write = write
    return sent


def _elm(**kw):
    e = Elm327(SimulatedTransport(**kw))
    e.initialize()
    return e


# 1 ---------------------------------------------------- leitura do painel
class _FlakyPoller:
    def __init__(self, inner):
        self.inner, self.calls = inner, 0
        self.missing, self.cycle = inner.missing, 0

    def poll(self):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("falha qualquer")
        out = self.inner.poll()
        self.cycle = self.inner.cycle
        return out


def test_dashboard_reader_survives_unexpected_error():
    e = _elm()
    poller = _FlakyPoller(LivePoller(e, ObdClient(e), UdsClient(e), False))
    dash = Dashboard(poller, None, None, {"adaptador": "x", "simulado": True}, interval=0.05, port=0)
    dash.start()
    seen_error = False
    try:
        deadline = time.time() + 5
        while time.time() < deadline and poller.calls < 6:
            d = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{dash.port}/dados", timeout=5).read())
            seen_error |= bool(d["error"] and "falha inesperada" in d["error"])
            time.sleep(0.02)
    finally:
        assert dash.stop()
    assert poller.calls >= 6  # a leitura continuou depois do erro
    assert seen_error or dash.data()["error"] is None


def test_serial_errors_become_transport_errors():
    import serial

    from volvodiag.transport import SerialTransport, TransportError

    class Broken:
        in_waiting = 0

        def reset_input_buffer(self):
            pass

        def write(self, data):
            raise serial.SerialException("dispositivo removido")

        def read(self, n):
            raise OSError("dispositivo removido")

    t = SerialTransport.__new__(SerialTransport)
    t._ser, t._serial_error = Broken(), serial.SerialException
    with pytest.raises(TransportError):
        t.write(b"ATZ\r")
    with pytest.raises(TransportError):
        t.read_until_prompt(0.2)


# 2 ------------------------------------------------- segurança da rede MS
def _args(*extra):
    return build_parser().parse_args(["--simulador", "--rede", "ms", *extra, "modulos"])


def test_ms_refused_when_switch_on_hs():
    with pytest.raises(SystemExit, match="não confirmada"):
        Session(_args("--simular-chave", "HS"))


def test_ms_bus_check_sends_only_at_commands():
    t = SimulatedTransport(chave="HS")
    sent = _recording(t)
    e = Elm327(t)
    e.initialize("ms")
    ok, detail = e.verify_ms_bus(seconds=0.01)
    assert not ok and "HS" in detail
    assert all(c.startswith("AT") or c == "" or c == "STI" for c in sent)


def test_ms_bus_confirmed_with_switch_on_ms():
    e = Elm327(SimulatedTransport(chave="MS"))
    e.initialize("ms")
    ok, detail = e.verify_ms_bus(seconds=0.01)
    assert ok and "125 kbps" in detail


def test_ms_refused_on_stn_adapter():
    with pytest.raises(ElmError, match="OBDLink"):
        Elm327(SimulatedTransport(stn=True)).initialize("ms")


# 3, 4, 7, 11 ------------------------------------------------ manutenção
def test_dates_accept_brazilian_format_and_reject_invalid(tmp_path):
    assert parse_date("13/11/2026") == "2026-11-13"
    assert parse_date("2026-11-13") == "2026-11-13"
    with pytest.raises(ValueError):
        parse_date("31/02/2026")
    store = Store(tmp_path / "h.sqlite")
    store.add_maintenance("05/01/2026", 90000, "Velas")
    assert store.last_maintenance("velas")["date"] == "2026-01-05"
    store.close()


def test_cli_rejects_bad_date(tmp_path):
    with pytest.raises(SystemExit, match="data inválida"):
        main(["--db", str(tmp_path / "h.sqlite"), "manutencao", "adicionar", "--item", "Velas", "--data", "13-2026"])


def test_unknown_km_is_not_reported_as_ok(tmp_path):
    store = Store(tmp_path / "h.sqlite")
    store.set_interval("Velas", 60000, None)
    store.add_maintenance("2026-01-01", 10000, "Velas")
    store.set_interval("Filtro de ar", 30000, None)
    store.add_maintenance("2026-01-01", None, "Filtro de ar")
    due = {d.item: d for d in due_list(store, km_now=None, today=date(2026, 11, 13))}
    assert due["Velas"].status == "indefinida" and "--km-atual" in due["Velas"].detail
    assert due["Filtro de ar"].status == "indefinida" and "não tem km" in due["Filtro de ar"].detail
    due = {d.item: d for d in due_list(store, km_now=100000, today=date(2026, 11, 13))}
    assert due["Velas"].status == "vencida"
    store.close()


def test_item_names_ignore_case_of_accented_letters(tmp_path):
    store = Store(tmp_path / "h.sqlite")
    store.set_interval("Troca de Óleo", 10000, 12)
    store.add_maintenance("2026-01-10", 90000, "troca de óleo")
    assert store.last_maintenance("TROCA DE ÓLEO") is not None
    store.set_interval("troca de óleo", 15000, None)  # mesmo item, não cria outro
    ivs = store.intervals()
    assert len(ivs) == 1 and ivs[0]["item"] == "Troca de Óleo"
    store.close()


def test_partial_interval_update_keeps_other_limit(tmp_path):
    store = Store(tmp_path / "h.sqlite")
    store.set_interval("Óleo", 10000, 12)
    iv = store.set_interval("Óleo", 15000, None)
    assert (iv["km"], iv["meses"]) == (15000, 12)
    iv = store.set_interval("Óleo", None, 0)  # 0 apaga
    assert (iv["km"], iv["meses"]) == (15000, None)
    store.close()


# 5, 9, 12 ------------------------------------------------------- painel
def test_busy_port_is_detected_and_no_empty_session(tmp_path):
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    port = busy.getsockname()[1]
    db = tmp_path / "h.sqlite"
    try:
        with pytest.raises(SystemExit, match="Não foi possível abrir o painel"):
            main(["--simulador", "--db", str(db), "painel", "--nao-abrir", "--porta-painel", str(port), "--duracao", "1"])
    finally:
        busy.close()
    store = Store(db)
    assert store.sessions() == []
    store.close()


def test_stop_reports_reader_finished():
    e = _elm()
    dash = Dashboard(LivePoller(e, ObdClient(e), UdsClient(e), False), None, None,
                     {"adaptador": "x", "simulado": True}, interval=0.05, port=0)
    dash.start()
    time.sleep(0.2)
    assert dash.stop() is True


def test_page_marks_tiles_without_reading():
    assert "velho" in PAGE and "sem leitura" in PAGE


# 6, 15 ------------------------------------------------- varredura de módulos
class _CarWithPickyModule(SimulatedCar):
    def physical(self, tx, req, network="hs"):
        if tx == 0x7A0:
            return b"\x7f\x3e\x11"  # existe, mas recusa o 3E
        return super().physical(tx, req, network)


def test_scan_counts_negative_replies_and_uses_few_commands():
    t = SimulatedTransport(car=_CarWithPickyModule())
    e = Elm327(t)
    e.initialize()
    sent = _recording(t)
    found = list(UdsClient(e).scan_addresses(0x79E, 0x7A2))
    assert found == [0x7A0]
    at = [c for c in sent if c.startswith("AT")]
    assert len(at) <= 2 * 5  # só ATSH + ATCRA por endereço


def test_flow_control_configured_once_per_mode():
    t = SimulatedTransport()
    e = Elm327(t)
    e.initialize()
    sent = _recording(t)
    uds = UdsClient(e)
    uds.read_did(modules.get("CEM"), 0x4028)
    uds.read_did(modules.get("ECM"), 0xF190)
    assert sent.count("ATFCSM1") == 1 and sent.count("ATFCSD300000") == 1


# 8 ------------------------------------------------------ valores lentos
def test_slow_values_are_stored_only_when_read():
    e = _elm()
    poller = LivePoller(e, ObdClient(e), UdsClient(e), False, slow_every=3)
    shown0, stored0 = poller.poll()
    shown1, stored1 = poller.poll()
    assert "tensao_adaptador" in stored0 and "tensao_adaptador" not in stored1
    assert "tensao_adaptador" in shown1  # ainda exibido entre leituras
    e.adapter_voltage = lambda: None  # deixou de responder
    poller.poll()
    shown3, stored3 = poller.poll()  # ciclo 3: nova leitura lenta
    assert "tensao_adaptador" not in shown3 and "tensao_adaptador" not in stored3


# 13 ---------------------------------------------- restrições da rede MS
def test_functional_requests_refused_on_ms():
    e = Elm327(SimulatedTransport(chave="MS"))
    e.initialize("ms")
    with pytest.raises(ElmError, match="rede principal"):
        ObdClient(e).read_vin()


def test_did_commands_check_module_network(tmp_path):
    with pytest.raises(SystemExit, match="rede HS-CAN"):
        main(["--simulador", "--rede", "ms", "--db", str(tmp_path / "h.sqlite"), "ler-did", "--modulo", "ECM", "--did", "F190"])
    with pytest.raises(SystemExit, match="rede MS-CAN"):
        main(["--simulador", "--db", str(tmp_path / "h.sqlite"), "varrer-dids", "--modulo", "DIM"])
