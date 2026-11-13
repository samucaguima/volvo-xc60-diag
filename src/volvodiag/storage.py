"""Histórico local em SQLite: sessões, leituras, códigos de erro e manutenção."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    vin TEXT,
    adapter TEXT,
    simulated INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS samples (
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ts REAL NOT NULL,
    key TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT
);
CREATE INDEX IF NOT EXISTS samples_session ON samples(session_id, key);
CREATE TABLE IF NOT EXISTS dtc_events (
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ts REAL NOT NULL,
    source TEXT NOT NULL,
    code TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS maintenance (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    km INTEGER,
    item TEXT NOT NULL,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS maintenance_intervals (
    item TEXT PRIMARY KEY COLLATE NOCASE,
    km INTEGER,
    meses INTEGER
);
CREATE TABLE IF NOT EXISTS discovered_dids (
    module TEXT NOT NULL,
    did INTEGER NOT NULL,
    data_hex TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (module, did)
);
"""


def default_db() -> Path:
    return Path.home() / ".volvodiag" / "historico.sqlite"


class Store:
    def __init__(self, path: Path | str | None = None, check_same_thread: bool = True) -> None:
        self.path = Path(path) if path else default_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: o painel grava a partir da linha de execução de leitura
        self.db = sqlite3.connect(self.path, check_same_thread=check_same_thread)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------ sessões
    def new_session(self, kind: str, vin: str | None, adapter: str, simulated: bool) -> int:
        cur = self.db.execute(
            "INSERT INTO sessions (started_at, kind, vin, adapter, simulated) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), kind, vin, adapter, int(simulated)),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def add_samples(self, session_id: int, ts: float, values: dict[str, tuple[float, str]]) -> None:
        self.db.executemany(
            "INSERT INTO samples VALUES (?,?,?,?,?)",
            [(session_id, ts, k, v, u) for k, (v, u) in values.items()],
        )
        self.db.commit()

    def add_dtc(self, session_id: int, ts: float, source: str, code: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO dtc_events VALUES (?,?,?,?,?)", (session_id, ts, source, code, detail))
        self.db.commit()

    def sessions(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM samples WHERE session_id=s.id) AS n "
            "FROM sessions s ORDER BY s.id DESC"
        ).fetchall()

    def session(self, session_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()

    def series(self, session_id: int) -> dict[str, list[tuple[float, float, str]]]:
        out: dict[str, list[tuple[float, float, str]]] = {}
        for r in self.db.execute(
            "SELECT ts, key, value, unit FROM samples WHERE session_id=? ORDER BY ts", (session_id,)
        ):
            out.setdefault(r["key"], []).append((r["ts"], r["value"], r["unit"] or ""))
        return out

    def dtcs(self, session_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM dtc_events WHERE session_id=? ORDER BY ts", (session_id,)
        ).fetchall()

    # --------------------------------------------------------- manutenção
    def add_maintenance(self, date: str, km: int | None, item: str, notes: str = "") -> int:
        cur = self.db.execute(
            "INSERT INTO maintenance (date, km, item, notes) VALUES (?,?,?,?)", (date, km, item, notes)
        )
        self.db.commit()
        return int(cur.lastrowid)

    def maintenance(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM maintenance ORDER BY date DESC, id DESC").fetchall()

    def last_maintenance(self, item: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM maintenance WHERE item = ? COLLATE NOCASE ORDER BY date DESC, id DESC LIMIT 1",
            (item,),
        ).fetchone()

    def set_interval(self, item: str, km: int | None, meses: int | None) -> None:
        self.db.execute("INSERT OR REPLACE INTO maintenance_intervals VALUES (?,?,?)", (item, km, meses))
        self.db.commit()

    def intervals(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM maintenance_intervals ORDER BY item").fetchall()

    # ------------------------------------------------- DIDs descobertos
    def save_did(self, module: str, did: int, data: bytes) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO discovered_dids VALUES (?,?,?,?)",
            (module, did, data.hex(), datetime.now().isoformat(timespec="seconds")),
        )
        self.db.commit()
