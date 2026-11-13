from datetime import date

from volvodiag.cli import main
from volvodiag.storage import Store
from volvodiag.trends import _add_months, alerts, collect, due_list


def _session(store, off_volt, ltft, simulated=False):
    sid = store.new_session("ao-vivo", None, "teste", simulated)
    for i in range(5):  # motor desligado
        store.add_samples(sid, 1000 + i, {"rpm": (0, "rpm"), "tensao_adaptador": (off_volt, "V")})
    for i in range(5):  # motor ligado
        store.add_samples(sid, 2000 + i, {"rpm": (800, "rpm"), "tensao_modulo": (14.1, "V"),
                                          "ltft_b1": (ltft, "%"), "temp_arrefecimento": (90, "°C")})
    return sid


def test_trends_detect_battery_drop_and_trim_shift(tmp_path):
    store = Store(tmp_path / "h.sqlite")
    _session(store, 12.7, 1.0)
    _session(store, 12.6, 2.0)
    _session(store, 12.2, 9.0)
    stats = collect(store)
    store.close()
    assert [s.bateria_desligado for s in stats] == [12.7, 12.6, 12.2]
    assert stats[-1].carga_ligado == 14.1 and stats[-1].arrefecimento_max == 90
    found = alerts(stats)
    assert any("Bateria com motor desligado caiu" in a for a in found)
    assert any("mais pobre" in a for a in found)


def test_trends_quiet_when_stable(tmp_path):
    store = Store(tmp_path / "h.sqlite")
    _session(store, 12.6, 2.0)
    _session(store, 12.6, 2.5)
    stats = collect(store)
    store.close()
    assert alerts(stats) == []


def test_trends_ignore_simulated_by_default(tmp_path):
    store = Store(tmp_path / "h.sqlite")
    _session(store, 12.6, 2.0, simulated=True)
    assert collect(store) == []
    assert len(collect(store, include_simulated=True)) == 1
    store.close()


def test_add_months_end_of_month():
    assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert _add_months(date(2026, 11, 13), 12) == date(2027, 11, 13)


def test_due_list(tmp_path):
    store = Store(tmp_path / "h.sqlite")
    store.set_interval("Troca de óleo e filtro", 10000, 12)
    store.set_interval("Fluido de freio", None, 24)
    store.set_interval("Velas", 60000, None)
    store.add_maintenance("2026-01-10", 90000, "troca de óleo e filtro")  # nome em minúsculas
    store.add_maintenance("2024-10-01", 70000, "Fluido de freio")
    due = {d.item: d for d in due_list(store, km_now=99500, today=date(2026, 11, 13))}
    store.close()
    assert due["Troca de óleo e filtro"].status == "próxima"  # faltam 500 km
    assert "faltam 500 km" in due["Troca de óleo e filtro"].detail
    assert due["Fluido de freio"].status == "vencida"  # venceu em 2026-10-01
    assert due["Velas"].status == "sem registro"


def test_cli_maintenance_and_trends(tmp_path, capsys):
    db = str(tmp_path / "h.sqlite")
    assert main(["--db", db, "manutencao", "intervalo", "--item", "Troca de óleo e filtro", "--km", "10000", "--meses", "12"]) == 0
    assert main(["--db", db, "manutencao", "adicionar", "--item", "Troca de óleo e filtro", "--km", "90000",
                 "--data", "2026-01-10"]) == 0
    assert main(["--db", db, "manutencao", "proximas", "--km-atual", "101000"]) == 0
    out = capsys.readouterr().out
    assert "10000 km ou 12 meses" in out and "[!!!] Troca de óleo e filtro: vencida" in out

    store = Store(db)
    _session(store, 12.7, 1.0)
    _session(store, 12.1, 1.0)
    store.close()
    assert main(["--db", db, "tendencias"]) == 0
    out = capsys.readouterr().out
    assert "Bateria com motor desligado caiu" in out
