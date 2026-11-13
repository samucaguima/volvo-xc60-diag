import pytest

from volvodiag import adapter_check
from volvodiag.cli import SIM_BAD_CLONE, main
from volvodiag.simulator import SimulatedTransport
from volvodiag.transport import TransportError


def test_good_adapter_is_approved_and_reaches_car():
    rep = adapter_check.run(SimulatedTransport())
    assert rep.approved
    assert all(r.ok for r in rep.results)
    assert rep.identification == "ELM327 v1.4b"
    assert rep.car_link.startswith("ok")


def test_ignition_off_still_approves_adapter():
    rep = adapter_check.run(SimulatedTransport(ignition_on=False))
    assert rep.approved
    assert "ignição desligada" in rep.car_link


def test_bad_clone_is_rejected_with_missing_commands():
    rep = adapter_check.run(SimulatedTransport(unsupported=SIM_BAD_CLONE))
    assert not rep.approved
    missing = {r.check.cmd for r in rep.missing_required}
    assert {"ATS0", "ATAT1", "ATCRA7E8", "ATFCSH7E0"} <= missing
    # opcionais ausentes não contam como falha obrigatória
    assert "ATPPS" not in missing and "ATSPB" not in missing
    # a falha é atribuída ao adaptador, não à ignição
    assert rep.car_link.startswith("não testada: o próprio adaptador")


class _Dead:
    def write(self, data):
        pass

    def read_until_prompt(self, timeout):
        raise TransportError("timeout")

    def close(self):
        pass


def test_unpowered_adapter_gives_clear_message():
    with pytest.raises(TransportError, match="tomada OBD"):
        adapter_check.run(_Dead())


def test_check_never_sends_write_services():
    sent = []
    t = SimulatedTransport()
    orig = t.write
    t.write = lambda data: (sent.append(data.decode().strip()), orig(data))
    adapter_check.run(t)
    car_requests = [c for c in sent if not c.startswith(("AT", "ST"))]
    assert car_requests == ["0100"]


def test_cli_approved(capsys, tmp_path):
    assert main(["--simulador", "--db", str(tmp_path / "h.sqlite"), "testar-adaptador"]) == 0
    out = capsys.readouterr().out
    assert "APROVADO" in out and "ATFCSH7E0" in out


def test_cli_bad_clone(capsys, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["--simulador", "--db", str(tmp_path / "h.sqlite"), "testar-adaptador", "--simular-clone-ruim"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "REPROVADO" in out and "ATCRA7E8" in out and "devolução" in out
