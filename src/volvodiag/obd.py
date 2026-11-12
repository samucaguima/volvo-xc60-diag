"""Serviços OBD-II padrão: dados ao vivo, códigos de erro e VIN."""

from __future__ import annotations

from dataclasses import dataclass

from .dtc import decode_sae
from .elm327 import Elm327
from .pids import PID_SIZES, PIDS

MAX_PIDS_PER_REQUEST = 6  # limite do padrão ISO 15765-4


@dataclass
class Reading:
    key: str
    name: str
    value: float
    unit: str
    ecu: int


@dataclass
class MonitorStatus:
    mil_on: bool
    dtc_count: int


class ObdClient:
    def __init__(self, elm: Elm327) -> None:
        self.elm = elm
        self._supported: set[int] | None = None

    def _request(self, payload: bytes, timeout: float = 2.0) -> dict[int, bytes]:
        self.elm.select_functional()
        return self.elm.request(payload, timeout)

    # ------------------------------------------------------------ suporte
    def supported_pids(self) -> set[int]:
        if self._supported is not None:
            return self._supported
        supported: set[int] = set()
        base = 0x00
        while base <= 0xC0:
            resp = self._request(bytes([0x01, base]))
            bitmap = 0
            for data in resp.values():
                if len(data) >= 6 and data[0] == 0x41 and data[1] == base:
                    bitmap |= int.from_bytes(data[2:6], "big")
            if not bitmap:
                break
            for bit in range(32):
                if bitmap & (1 << (31 - bit)):
                    supported.add(base + bit + 1)
            if not bitmap & 1:  # o último bit indica se existe o próximo mapa
                break
            base += 0x20
        self._supported = supported
        return supported

    # ------------------------------------------------------- dados atuais
    def read_pids(self, pids: list[int]) -> list[Reading]:
        """Lê vários PIDs, agrupando até 6 por pedido."""
        wanted = [p for p in pids if p in PIDS]
        readings: list[Reading] = []
        for i in range(0, len(wanted), MAX_PIDS_PER_REQUEST):
            group = wanted[i : i + MAX_PIDS_PER_REQUEST]
            resp = self._request(bytes([0x01, *group]))
            for ecu, data in resp.items():
                readings.extend(_parse_mode01(data, ecu))
        return readings

    def monitor_status(self) -> MonitorStatus | None:
        resp = self._request(bytes([0x01, 0x01]))
        for data in resp.values():
            if len(data) >= 3 and data[:2] == b"\x41\x01":
                return MonitorStatus(mil_on=bool(data[2] & 0x80), dtc_count=data[2] & 0x7F)
        return None

    # ---------------------------------------------------- códigos de erro
    def read_dtcs(self, mode: int = 0x03) -> dict[int, list[str]]:
        """Modo 03 (armazenados), 07 (pendentes) ou 0A (permanentes)."""
        resp = self._request(bytes([mode]), timeout=3.0)
        result: dict[int, list[str]] = {}
        for ecu, data in resp.items():
            if not data or data[0] != mode + 0x40:
                continue
            body = data[2:]  # em CAN o 2º byte é a quantidade de códigos
            codes = []
            for j in range(0, len(body) - 1, 2):
                if body[j] == 0 and body[j + 1] == 0:
                    continue
                codes.append(decode_sae(body[j], body[j + 1]))
            result[ecu] = codes
        return result

    def clear_dtcs(self) -> dict[int, bool]:
        """Modo 04. Bloqueado pela trava, a menos que autorizado."""
        resp = self._request(bytes([0x04]), timeout=5.0)
        return {ecu: bool(d) and d[0] == 0x44 for ecu, d in resp.items()}

    # --------------------------------------------------------------- VIN
    def read_vin(self) -> str | None:
        resp = self._request(bytes([0x09, 0x02]), timeout=3.0)
        for data in resp.values():
            if len(data) >= 20 and data[:2] == b"\x49\x02":
                vin = data[3:].decode("ascii", errors="replace").strip("\x00 ")
                if len(vin) == 17:
                    return vin
        return None


def _parse_mode01(data: bytes, ecu: int) -> list[Reading]:
    """Separa uma resposta 41 com um ou mais PIDs."""
    out: list[Reading] = []
    if not data or data[0] != 0x41:
        return out
    i = 1
    while i < len(data):
        pid = data[i]
        size = PID_SIZES.get(pid)
        if size is None or i + 1 + size > len(data):
            break  # PID de tamanho desconhecido: não dá para continuar
        raw = data[i + 1 : i + 1 + size]
        p = PIDS.get(pid)
        if p:
            out.append(Reading(p.key, p.name, round(p.decode(raw), 2), p.unit, ecu))
        i += 1 + size
    return out
