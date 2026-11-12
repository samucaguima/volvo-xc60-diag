import pytest

from volvodiag import modules
from volvodiag.dtc import UdsDtc, decode_sae, describe
from volvodiag.elm327 import Elm327
from volvodiag.health import ALERTA, ATENCAO, OK, evaluate
from volvodiag.isotp import IsoTpError, reassemble, split_frames
from volvodiag.obd import ObdClient
from volvodiag.safety import BlockedRequest, SafetyGuard
from volvodiag.simulator import SIM_VIN, SimulatedTransport
from volvodiag.uds import NegativeResponse, NoResponse, UdsClient


@pytest.fixture
def elm():
    e = Elm327(SimulatedTransport())
    e.initialize()
    return e


# ---------------------------------------------------------------- segurança
@pytest.mark.parametrize("sid", [0x2E, 0x31, 0x27, 0x34, 0x11, 0x10, 0x3D, 0x85, 0x2F])
def test_guard_blocks_write_services(sid):
    with pytest.raises(BlockedRequest):
        SafetyGuard().check(bytes([sid, 0x00]))


def test_guard_clear_needs_explicit_permission():
    with pytest.raises(BlockedRequest):
        SafetyGuard().check(b"\x14\xff\xff\xff")
    SafetyGuard(allow_clear=True).check(b"\x14\xff\xff\xff")
    SafetyGuard().check(b"\x22\xf1\x90")


def test_blocked_request_never_reaches_adapter(elm):
    sent = []
    orig = elm.transport.write
    elm.transport.write = lambda data: (sent.append(data), orig(data))
    with pytest.raises(BlockedRequest):
        elm.request(b"\x2e\x40\x28\x00")
    assert sent == []


# ------------------------------------------------------------------ ISO-TP
def test_isotp_roundtrip_long_message():
    payload = bytes(range(40))
    frames = [(0x7E8, f) for f in split_frames(payload)]
    assert reassemble(frames) == {0x7E8: payload}


def test_isotp_detects_missing_frame():
    frames = [(0x7E8, f) for f in split_frames(bytes(30))]
    with pytest.raises(IsoTpError):
        reassemble(frames[:-1])


def test_single_frame_strips_padding():
    assert reassemble([(0x7E8, bytes.fromhex("0341054F55555555"))]) == {0x7E8: bytes.fromhex("41054F")}


# --------------------------------------------------------------------- OBD
def test_vin_multiframe(elm):
    assert ObdClient(elm).read_vin() == SIM_VIN


def test_supported_and_multi_pid(elm):
    obd = ObdClient(elm)
    sup = obd.supported_pids()
    assert {0x0C, 0x05, 0x42}.issubset(sup)
    assert 0x5C not in sup  # o simulador não oferece a temperatura de óleo padrão
    readings = {r.key: r.value for r in obd.read_pids([0x0C, 0x05, 0x42, 0x33, 0x0B, 0x07, 0x0F])}
    assert readings["temp_arrefecimento"] == 88
    assert readings["tensao_modulo"] == 14.1
    assert readings["pressao_barometrica"] == 93
    assert 700 < readings["rpm"] < 3100
    assert readings["ltft_b1"] == pytest.approx(3.12, abs=0.01)


def test_dtcs_and_monitor(elm):
    obd = ObdClient(elm)
    assert obd.read_dtcs(0x03)[0x7E8] == ["P0420"]
    assert obd.read_dtcs(0x07)[0x7E8] == ["P0171"]
    st = obd.monitor_status()
    assert st.mil_on and st.dtc_count == 1


def test_clear_requires_permission(elm):
    with pytest.raises(BlockedRequest):
        ObdClient(elm).clear_dtcs()
    elm.guard.allow_clear = True
    ObdClient(elm).clear_dtcs()
    assert ObdClient(elm).read_dtcs(0x03).get(0x7E8, []) == []


# --------------------------------------------------------------------- DTC
def test_decode_sae():
    assert decode_sae(0x04, 0x20) == "P0420"
    assert decode_sae(0xC1, 0x00) == "U0100"
    assert decode_sae(0x41, 0x23) == "C0123"
    assert decode_sae(0x9A, 0x40) == "B1A40"


def test_describe_generic():
    assert "Catalyst" in describe("P0420")


def test_uds_dtc_fields():
    d = UdsDtc("CEM", bytes([0xA1, 0x2B, 0x15, 0x09]))
    assert d.volvo_code == "CEM-A12B"
    assert d.failure_type == 0x15
    assert d.active and d.confirmed


# --------------------------------------------------------------------- UDS
def test_uds_read_did_and_negative(elm):
    uds = UdsClient(elm)
    cem = modules.get("CEM")
    assert uds.read_did(cem, 0x4028) == bytes([83])
    assert uds.read_did(cem, 0xF190).decode() == SIM_VIN
    with pytest.raises(NegativeResponse) as exc:
        uds.read_did(cem, 0x1234)
    assert exc.value.code == 0x31


def test_uds_missing_module(elm):
    uds = UdsClient(elm)
    assert uds.ping(modules.get("ECM"))
    assert not uds.ping(modules.get("DIM"))
    with pytest.raises(NoResponse):
        uds.read_dtcs(modules.get("DIM"))


def test_uds_dtcs(elm):
    items = UdsClient(elm).read_dtcs(modules.get("ECM"))
    assert [d.sae_code for d in items] == ["P0420"]


def test_scan_finds_only_existing(elm):
    found = dict(UdsClient(elm).scan_dids(modules.get("CEM"), 0x4000, 0x4030, delay=0))
    assert set(found) == {0x4005, 0x4028}


# ------------------------------------------------------------------- saúde
def _levels(values):
    return {f.item: f.level for f in evaluate(values)}


def test_health_battery_engine_off():
    assert _levels({"rpm": 0, "tensao_adaptador": 12.0})["Bateria"] == ATENCAO
    assert _levels({"rpm": 0, "tensao_adaptador": 11.5})["Bateria"] == ALERTA
    assert _levels({"rpm": 0, "tensao_adaptador": 12.6})["Bateria"] == OK


def test_health_charging_and_trims():
    lv = _levels({"rpm": 800, "tensao_modulo": 12.2, "ltft_b1": 14, "stft_b1": 2})
    assert lv["Carga"] == ALERTA
    assert lv["Mistura"] == ATENCAO
    assert _levels({"rpm": 800, "ltft_b1": 3, "stft_b1": -1})["Mistura"] == OK


def test_health_overheat_and_mil():
    lv = _levels({"temp_arrefecimento": 112, "luz_injecao": 1, "qtd_codigos": 1})
    assert lv["Arrefecimento"] == ALERTA
    assert lv["Luz de injeção"] == ALERTA
