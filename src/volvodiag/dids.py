"""Dados específicos da Volvo lidos com o serviço UDS 22 (somente leitura).

ATENÇÃO: os identificadores do motor foram verificados num P3 a DIESEL. O
Drive-E a gasolina tem outra central de motor, então eles podem não existir
ou ter outro significado no seu carro. Use ``varrer-dids`` para descobrir os
identificadores que o seu XC60 realmente responde e confirme cada um
comparando com o painel do carro antes de confiar no valor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Did:
    module: str
    did: int
    key: str
    name: str
    unit: str
    decode: Callable[[bytes], float | str]
    source: str


def _kelvin10(d: bytes) -> float:
    return round((d[0] * 256 + d[1]) / 10 - 273.15, 1)


def _ascii(d: bytes) -> str:
    return d.decode("ascii", errors="replace").strip("\x00 ")


DIDS: list[Did] = [
    Did("CEM", 0xF190, "vin_cem", "Chassi (VIN) gravado na CEM", "", _ascii,
        "padrão UDS (ISO 14229, identificador F190)"),
    Did("CEM", 0x4028, "carga_bateria", "Estado de carga da bateria", "%", lambda d: float(d[0]),
        "verificado num P3 diesel (volvo-p3-dashboard)"),
    Did("ECM", 0xF190, "vin_ecm", "Chassi (VIN) gravado no motor", "", _ascii,
        "padrão UDS (ISO 14229, identificador F190)"),
    Did("ECM", 0xD9DC, "temp_oleo_volvo", "Temperatura do óleo (Volvo)", "°C", _kelvin10,
        "verificado num P3 DIESEL; confirmar no Drive-E"),
    Did("ECM", 0xD941, "pressao_turbo_volvo", "Pressão no coletor, absoluta (Volvo)", "kPa",
        lambda d: round((d[0] * 256 + d[1]) / 10, 1),
        "verificado num P3 DIESEL; confirmar no Drive-E"),
]

# Faixas sugeridas para a varredura de descoberta (somente leitura).
SCAN_RANGES: dict[str, tuple[int, int]] = {
    "ECM": (0xD900, 0xDAFF),
    "CEM": (0x4000, 0x40FF),
    "TCM": (0x1E00, 0x1EFF),  # sugestão sem comprovação (volvoscan)
}


def for_module(module: str) -> list[Did]:
    return [d for d in DIDS if d.module == module.upper()]
