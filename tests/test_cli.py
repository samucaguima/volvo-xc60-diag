from volvodiag.cli import main
from volvodiag.storage import Store


def test_cli_end_to_end_with_simulator(tmp_path, capsys):
    db = tmp_path / "h.sqlite"
    base = ["--simulador", "--db", str(db)]

    assert main([*base, "info"]) == 0
    out = capsys.readouterr().out
    assert "MODO SIMULADOR" in out and "YV1DZ40SIMULADO01" in out and "ACESA" in out
    assert "ELM327 v1.4b" in out and ">" not in out

    assert main([*base, "dtc"]) == 0
    out = capsys.readouterr().out
    assert "P0420" in out and "catalisador" in out and "CEM-A12B" in out
    assert "DIM" not in out or "sem resposta" in out

    assert main([*base, "modulos"]) == 0
    out = capsys.readouterr().out
    assert "ECM" in out and "sim" in out

    assert main([*base, "ao-vivo", "--duracao", "0.5", "--intervalo", "0.1", "--volvo"]) == 0
    out = capsys.readouterr().out
    assert "Rotação do motor" in out and "Estado de carga da bateria (CEM)" in out

    assert main([*base, "saude"]) == 0
    out = capsys.readouterr().out
    assert "Luz de injeção" in out

    assert main([*base, "manutencao", "adicionar", "--km", "98000", "--item", "Troca de óleo"]) == 0
    capsys.readouterr()

    store = Store(db)
    live = [r for r in store.sessions() if r["kind"] == "ao-vivo"][0]
    store.close()
    report = tmp_path / "r.html"
    assert main([*base, "relatorio", "--sessao", str(live["id"]), "--saida", str(report)]) == 0
    html = report.read_text(encoding="utf-8")
    assert "Dados simulados" in html and "<svg" in html and "Troca de óleo" in html
    assert "Luz de injeção (1 = acesa)" in html and "luz_injecao<" not in html
    assert "adaptador simulador · ELM327 v1.4b" in html


def test_cli_varrer_dids(tmp_path, capsys):
    assert main(["--simulador", "--db", str(tmp_path / "h.sqlite"), "varrer-dids",
                 "--modulo", "CEM", "--inicio", "4000", "--fim", "4030", "--atraso", "0"]) == 0
    out = capsys.readouterr().out
    assert "4028: 53" in out and "2 identificador(es)" in out


def test_cli_apagar_cancelado(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "nao")
    assert main(["--simulador", "--db", str(tmp_path / "h.sqlite"), "apagar-dtc", "--modulo", "todos"]) == 0
    assert "Cancelado" in capsys.readouterr().out
