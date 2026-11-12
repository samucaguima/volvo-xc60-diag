"""Dados OBD-II padrão (SAE J1979, serviço 01) usados no painel ao vivo.

As fórmulas são as do padrão. Quais PIDs o seu XC60 realmente oferece é
descoberto em tempo de execução pelos mapas de suporte (PIDs 00, 20, 40...).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Pid:
    pid: int
    key: str
    name: str
    unit: str
    nbytes: int
    decode: Callable[[bytes], float]


def _a(d: bytes) -> int:
    return d[0]


def _ab(d: bytes) -> int:
    return d[0] * 256 + d[1]


PIDS: dict[int, Pid] = {
    p.pid: p
    for p in [
        Pid(0x04, "carga_motor", "Carga do motor", "%", 1, lambda d: _a(d) * 100 / 255),
        Pid(0x05, "temp_arrefecimento", "Temperatura do líquido de arrefecimento", "°C", 1, lambda d: _a(d) - 40),
        Pid(0x06, "stft_b1", "Correção de mistura de curto prazo", "%", 1, lambda d: (_a(d) - 128) * 100 / 128),
        Pid(0x07, "ltft_b1", "Correção de mistura de longo prazo", "%", 1, lambda d: (_a(d) - 128) * 100 / 128),
        Pid(0x0B, "map", "Pressão absoluta no coletor", "kPa", 1, lambda d: float(_a(d))),
        Pid(0x0C, "rpm", "Rotação do motor", "rpm", 2, lambda d: _ab(d) / 4),
        Pid(0x0D, "velocidade", "Velocidade", "km/h", 1, lambda d: float(_a(d))),
        Pid(0x0E, "avanco_ignicao", "Avanço de ignição", "°", 1, lambda d: _a(d) / 2 - 64),
        Pid(0x0F, "temp_ar_admissao", "Temperatura do ar de admissão", "°C", 1, lambda d: _a(d) - 40),
        Pid(0x10, "maf", "Fluxo de ar (MAF)", "g/s", 2, lambda d: _ab(d) / 100),
        Pid(0x11, "borboleta", "Posição da borboleta", "%", 1, lambda d: _a(d) * 100 / 255),
        Pid(0x1F, "tempo_motor_ligado", "Tempo desde a partida", "s", 2, lambda d: float(_ab(d))),
        Pid(0x21, "km_com_luz_injecao", "Distância com a luz de injeção acesa", "km", 2, lambda d: float(_ab(d))),
        Pid(0x2F, "nivel_combustivel", "Nível de combustível", "%", 1, lambda d: _a(d) * 100 / 255),
        Pid(0x31, "km_desde_apagar_codigos", "Distância desde que os códigos foram apagados", "km", 2, lambda d: float(_ab(d))),
        Pid(0x33, "pressao_barometrica", "Pressão barométrica", "kPa", 1, lambda d: float(_a(d))),
        Pid(0x42, "tensao_modulo", "Tensão no módulo do motor", "V", 2, lambda d: _ab(d) / 1000),
        Pid(0x46, "temp_ambiente", "Temperatura ambiente", "°C", 1, lambda d: _a(d) - 40),
        Pid(0x5C, "temp_oleo", "Temperatura do óleo do motor", "°C", 1, lambda d: _a(d) - 40),
    ]
}

# Ordem de leitura no painel ao vivo.
LIVE_PIDS: list[int] = [
    0x0C, 0x0D, 0x04, 0x05, 0x0F, 0x0B, 0x33, 0x10, 0x11,
    0x06, 0x07, 0x0E, 0x42, 0x5C, 0x46, 0x2F, 0x1F,
]

# Tamanho em bytes de cada PID, usado para separar respostas de pedidos
# com vários PIDs. Inclui PIDs que não decodificamos.
PID_SIZES: dict[int, int] = {pid: p.nbytes for pid, p in PIDS.items()}
PID_SIZES.update({0x00: 4, 0x20: 4, 0x40: 4, 0x60: 4, 0x80: 4, 0xA0: 4, 0xC0: 4, 0x01: 4})
