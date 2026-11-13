import pytest

from volvodiag import modules
from volvodiag.cli import main
from volvodiag.elm327 import Elm327
from volvodiag.simulator import SimulatedTransport
from volvodiag.uds import UdsClient


def _elm(network):
    t = SimulatedTransport()
    sent = []
    orig = t.write
    t.write = lambda data: (sent.append(data.decode().strip()), orig(data))
    e = Elm327(t)
    e.initialize(network)
    return e, sent


def test_ms_network_uses_protocol_b_125k():
    e, sent = _elm("ms")
    assert "ATPB8104" in sent and "ATSPB" in sent and "ATSP6" not in sent
    assert e.network == "ms"


def test_modules_split_by_network():
    assert [m.name for m in modules.on_network("ms")] == ["DIM", "CCM"]
    assert "ECM" in [m.name for m in modules.on_network("hs")]


def test_ms_modules_only_answer_on_ms():
    e_hs, _ = _elm("hs")
    e_ms, _ = _elm("ms")
    dim = modules.get("DIM")
    assert not UdsClient(e_hs).ping(dim)
    assert UdsClient(e_ms).ping(dim)
    assert not UdsClient(e_ms).ping(modules.get("ECM"))


def test_scan_addresses_per_network():
    e_hs, _ = _elm("hs")
    e_ms, _ = _elm("ms")
    assert list(UdsClient(e_hs).scan_addresses()) == [0x726, 0x760, 0x772, 0x7E0, 0x7E1]
    assert list(UdsClient(e_ms).scan_addresses()) == [0x720, 0x733]


def test_cli_dtc_on_ms(capsys, tmp_path):
    assert main(["--simulador", "--rede", "ms", "--db", str(tmp_path / "h.sqlite"), "dtc"]) == 0
    out = capsys.readouterr().out
    assert "CCM-9C10" in out and "DIM: nenhum código" in out
    assert "OBD-II" not in out and "P0420" not in out


def test_cli_modulos_and_scan_on_ms(capsys, tmp_path):
    base = ["--simulador", "--rede", "ms", "--db", str(tmp_path / "h.sqlite")]
    assert main([*base, "modulos"]) == 0
    out = capsys.readouterr().out
    assert "DIM" in out and "ECM" not in out.split("Na outra rede")[0]
    assert main([*base, "varrer-modulos"]) == 0
    out = capsys.readouterr().out
    assert "0x720 responde (DIM)" in out and "0x733 responde (CCM)" in out


def test_cli_rejects_live_on_ms(tmp_path):
    with pytest.raises(SystemExit, match="rede principal"):
        main(["--simulador", "--rede", "ms", "--db", str(tmp_path / "h.sqlite"), "ao-vivo"])


def test_cli_apagar_motor_obd_not_on_ms(tmp_path):
    with pytest.raises(SystemExit, match="MS-CAN"):
        main(["--simulador", "--rede", "ms", "--db", str(tmp_path / "h.sqlite"), "apagar-dtc", "--modulo", "motor-obd"])
