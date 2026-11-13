"""Tendências entre sessões gravadas e vencimento de manutenções.

As tendências comparam a sessão mais recente com a média das anteriores.
Os limites para chamar atenção são referências gerais, não especificações
da Volvo. Os intervalos de manutenção são cadastrados pelo usuário a partir
do manual do carro ou da concessionária.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import mean, median

from .storage import Store

RUNNING_RPM = 400


@dataclass
class SessionStats:
    session_id: int
    started_at: str
    simulated: bool
    bateria_desligado: float | None  # V, mediana com motor desligado
    carga_ligado: float | None  # V, mediana com motor ligado
    ltft: float | None  # %, mediana com motor ligado
    arrefecimento_max: float | None  # °C
    soc_cem: float | None  # %, mediana


# chave -> (coluna curta, descrição, unidade)
METRICS = {
    "bateria_desligado": ("Bat.desl", "bateria com motor desligado (mediana)", "V"),
    "carga_ligado": ("Carga", "tensão de carga com motor ligado (mediana)", "V"),
    "ltft": ("Mist.LP", "correção de mistura de longo prazo (mediana)", "%"),
    "arrefecimento_max": ("Arref.máx", "temperatura máxima do arrefecimento", "°C"),
    "soc_cem": ("SoC CEM", "estado de carga da bateria pela CEM (mediana)", "%"),
}


def _med(values: list[float]) -> float | None:
    return round(median(values), 2) if values else None


def session_stats(store: Store, session_id: int) -> SessionStats:
    s = store.session(session_id)
    rows: dict[float, dict[str, float]] = {}
    for r in store.db.execute("SELECT ts, key, value FROM samples WHERE session_id=?", (session_id,)):
        rows.setdefault(r["ts"], {})[r["key"]] = r["value"]
    off_v, on_v, ltft, ect, soc = [], [], [], [], []
    for row in rows.values():
        rpm = row.get("rpm")
        volt = row.get("tensao_modulo", row.get("tensao_adaptador"))
        if rpm is not None and rpm > RUNNING_RPM:
            if volt is not None:
                on_v.append(volt)
            if "ltft_b1" in row:
                ltft.append(row["ltft_b1"])
        elif rpm is not None and volt is not None:
            off_v.append(volt)
        if "temp_arrefecimento" in row:
            ect.append(row["temp_arrefecimento"])
        if "carga_bateria" in row:
            soc.append(row["carga_bateria"])
    return SessionStats(
        session_id, s["started_at"], bool(s["simulated"]),
        _med(off_v), _med(on_v), _med(ltft), max(ect) if ect else None, _med(soc),
    )


def collect(store: Store, last: int = 10, include_simulated: bool = False) -> list[SessionStats]:
    ids = [
        r["id"] for r in store.sessions()
        if r["kind"] in ("ao-vivo", "painel") and r["n"] and (include_simulated or not r["simulated"])
    ][:last]
    return [session_stats(store, i) for i in reversed(ids)]  # mais antiga primeiro


def alerts(stats: list[SessionStats]) -> list[str]:
    """Compara a última sessão com a média das anteriores."""
    if len(stats) < 2:
        return []
    last, prev = stats[-1], stats[:-1]
    out: list[str] = []

    def avg(attr: str) -> float | None:
        vals = [getattr(p, attr) for p in prev if getattr(p, attr) is not None]
        return mean(vals) if vals else None

    b_prev, b_last = avg("bateria_desligado"), last.bateria_desligado
    if b_prev is not None and b_last is not None and b_prev - b_last >= 0.3:
        out.append(f"Bateria com motor desligado caiu de {b_prev:.2f} V (média anterior) para {b_last:.2f} V: "
                   "possível bateria envelhecendo ou consumo com o carro parado.")
    l_prev, l_last = avg("ltft"), last.ltft
    if l_prev is not None and l_last is not None and abs(l_last - l_prev) >= 5:
        direcao = "mais pobre" if l_last > l_prev else "mais rica"
        out.append(f"Mistura de longo prazo mudou de {l_prev:+.1f} % para {l_last:+.1f} % ({direcao}): "
                   "vale investigar entrada de ar, combustível ou sensores.")
    c_prev, c_last = avg("carga_ligado"), last.carga_ligado
    if c_prev is not None and c_last is not None and c_prev - c_last >= 0.5:
        out.append(f"Tensão de carga com motor ligado caiu de {c_prev:.2f} V para {c_last:.2f} V: verifique o alternador.")
    e_prev, e_last = avg("arrefecimento_max"), last.arrefecimento_max
    if e_prev is not None and e_last is not None and e_last - e_prev >= 8:
        out.append(f"Temperatura máxima do arrefecimento subiu de {e_prev:.0f} °C para {e_last:.0f} °C.")
    return out


# ----------------------------------------------------------- manutenção
@dataclass
class Due:
    item: str
    status: str  # "vencida", "próxima", "em dia", "indefinida", "sem registro"
    detail: str


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    days = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(d.day, days))


def due_list(store: Store, km_now: int | None, today: date | None = None,
             warn_km: int = 1000, warn_days: int = 30) -> list[Due]:
    """Situação de cada intervalo cadastrado. "indefinida" quando não há
    dados para conferir (km atual ou do serviço desconhecido) e nada mais
    indica vencimento."""
    today = today or date.today()
    out: list[Due] = []
    for iv in store.intervals():
        last = store.last_maintenance(iv["item"])
        if last is None:
            out.append(Due(iv["item"], "sem registro", "registre a última vez que foi feita"))
            continue
        parts, status, unknown = [], "em dia", []
        if iv["km"]:
            if last["km"] is None:
                unknown.append("o registro não tem km; registre o serviço com --km")
            else:
                due_km = last["km"] + iv["km"]
                if km_now is None:
                    parts.append(f"vence aos {due_km} km")
                    unknown.append("informe --km-atual para comparar o km")
                else:
                    left = due_km - km_now
                    parts.append(f"vence aos {due_km} km ({'faltam ' + str(left) if left >= 0 else 'passou ' + str(-left)} km)")
                    if left < 0:
                        status = "vencida"
                    elif left <= warn_km:
                        status = "próxima"
        if iv["meses"]:
            try:
                last_date = date.fromisoformat(last["date"])
            except ValueError:
                unknown.append(f"data do registro inválida ({last['date']})")
            else:
                due_date = _add_months(last_date, iv["meses"])
                days_left = (due_date - today).days
                parts.append(f"vence em {due_date.isoformat()} ({'faltam ' + str(days_left) if days_left >= 0 else 'passou ' + str(-days_left)} dias)")
                if days_left < 0:
                    status = "vencida"
                elif days_left <= warn_days and status != "vencida":
                    status = "próxima"
        if status == "em dia" and unknown:
            status = "indefinida"
        detail = f"última em {last['date']}" + (f" aos {last['km']} km" if last["km"] is not None else "")
        out.append(Due(iv["item"], status, "; ".join([detail, *parts, *unknown])))
    return out
