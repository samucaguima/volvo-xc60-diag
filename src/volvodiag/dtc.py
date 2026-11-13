"""Códigos de erro (DTC): decodificação e descrições.

As descrições genéricas (padrão SAE J2012, em inglês) vêm do projeto
Wal33D/dtc-database (licença MIT, ver data/LICENSE-dtc-database.txt).
Os códigos mais comuns têm tradução livre para o português em
data/dtc_pt.csv (não oficial). Códigos específicos da Volvo não têm
descrição pública nessa base.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

_LETTERS = "PCBU"

# Bits do byte de estado UDS (ISO 14229-1, DTCStatusMask)
STATUS_BITS = {
    0: "falha no teste atual",
    1: "falha neste ciclo de operação",
    2: "pendente",
    3: "confirmado",
    4: "teste não concluído desde que os códigos foram apagados",
    5: "falhou desde que os códigos foram apagados",
    6: "teste não concluído neste ciclo",
    7: "pede luz de aviso",
}


def decode_sae(b0: int, b1: int) -> str:
    """Converte dois bytes no formato SAE (ex.: 0x04 0x20 -> P0420)."""
    letter = _LETTERS[b0 >> 6]
    return f"{letter}{(b0 >> 4) & 0x3}{b0 & 0x0F:X}{b1 >> 4:X}{b1 & 0x0F:X}"


@lru_cache(maxsize=1)
def _generic_table() -> dict[str, str]:
    table: dict[str, str] = {}
    path = resources.files("volvodiag") / "data" / "dtc_generic.csv"
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            table[row["code"]] = row["description_en"]
    return table


@lru_cache(maxsize=1)
def _pt_table() -> dict[str, str]:
    path = resources.files("volvodiag") / "data" / "dtc_pt.csv"
    with path.open(encoding="utf-8") as f:
        return {row["code"]: row["descricao_pt"] for row in csv.DictReader(f)}


def describe(code: str) -> str | None:
    """Descrição genérica de um código SAE: em português quando houver
    tradução, senão em inglês com a indicação "(em inglês)"."""
    code = code.upper()
    pt = _pt_table().get(code)
    if pt:
        return pt
    en = _generic_table().get(code)
    return f"{en} (em inglês)" if en else None


@dataclass
class UdsDtc:
    module: str
    raw: bytes  # 3 bytes do código + 1 byte de estado
    sae_code: str = field(init=False)
    volvo_code: str = field(init=False)
    failure_type: int = field(init=False)
    status: int = field(init=False)

    def __post_init__(self) -> None:
        b0, b1, b2, st = self.raw[0], self.raw[1], self.raw[2], self.raw[3]
        self.sae_code = decode_sae(b0, b1)
        self.volvo_code = f"{self.module}-{b0:02X}{b1:02X}"
        self.failure_type = b2
        self.status = st

    @property
    def status_text(self) -> list[str]:
        return [txt for bit, txt in STATUS_BITS.items() if self.status & (1 << bit)]

    @property
    def active(self) -> bool:
        return bool(self.status & 0x01)

    @property
    def confirmed(self) -> bool:
        return bool(self.status & 0x08)
