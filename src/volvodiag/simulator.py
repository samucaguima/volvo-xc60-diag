"""Simulador de um OBDLink MX+ ligado a um XC60 2014 Drive-E (dados FICTÍCIOS).

Serve para testar o sistema sem o carro: responde aos mesmos comandos AT e
pedidos OBD/UDS, no mesmo formato de quadros CAN do adaptador real. Os
valores, códigos de erro e o VIN são inventados.
"""

from __future__ import annotations

import math
import time

from .isotp import split_frames
from .pids import PID_SIZES

SIM_VIN = "YV1DZ40SIMULADO01"  # fictício


class SimulatedCar:
    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.stored = {0x7E8: [(0x04, 0x20)]}  # P0420 (fictício)
        self.pending = {0x7E8: [(0x01, 0x71)]}  # P0171 (fictício)
        self.uds_dtcs = {
            0x7E0: [bytes([0x04, 0x20, 0x00, 0x2F])],
            0x726: [bytes([0xA1, 0x2B, 0x15, 0x08])],
            0x7E1: [], 0x760: [], 0x772: [],
        }
        self.ecm_pids = {
            0x01, 0x04, 0x05, 0x06, 0x07, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F,
            0x10, 0x11, 0x1F, 0x21, 0x2F, 0x31, 0x33, 0x42, 0x46,
        }
        self.tcm_pids = {0x01, 0x0D}

    # ------------------------------------------------------------- valores
    def _t(self) -> float:
        return time.monotonic() - self.t0

    def pid_bytes(self, pid: int) -> bytes:
        t = self._t()
        wave = (1 + math.sin(t / 4)) / 2  # 0..1
        rpm = 780 + 2200 * wave
        values = {
            0x01: bytes([0x81, 0x07, 0xE5, 0x00]),  # luz acesa, 1 código
            0x04: bytes([int(20 + 60 * wave)]),
            0x05: bytes([88 + 40]),
            0x06: bytes([128 + int(3 * math.sin(t))]),
            0x07: bytes([132]),  # +3,1 %
            0x0B: bytes([int(95 + 85 * wave)]),
            0x0C: int(rpm * 4).to_bytes(2, "big"),
            0x0D: bytes([int(40 + 60 * wave)]),
            0x0E: bytes([int((12 + 64) * 2)]),
            0x0F: bytes([35 + 40]),
            0x10: int((4 + 60 * wave) * 100).to_bytes(2, "big"),
            0x11: bytes([int(255 * (0.12 + 0.5 * wave))]),
            0x1F: int(t + 600).to_bytes(2, "big"),
            0x21: (0).to_bytes(2, "big"),
            0x2F: bytes([158]),
            0x31: (1250).to_bytes(2, "big"),
            0x33: bytes([93]),
            0x42: (14100).to_bytes(2, "big"),
            0x46: bytes([27 + 40]),
        }
        return values[pid]

    def did_bytes(self, tx: int, did: int) -> bytes | None:
        vin = SIM_VIN.encode()
        table = {
            (0x7E0, 0xF190): vin,
            (0x726, 0xF190): vin,
            (0x7E0, 0xD9DC): int((93.0 + 273.15) * 10).to_bytes(2, "big"),
            (0x7E0, 0xD941): int(1400 + 400 * math.sin(self._t() / 4)).to_bytes(2, "big"),
            (0x726, 0x4028): bytes([83]),
            (0x726, 0x4005): bytes([0x01, 0x2C]),
            (0x7E0, 0xDA10): bytes([0x00, 0x64]),
        }
        return table.get((tx, did))

    # ------------------------------------------------------------ respostas
    def functional(self, req: bytes) -> dict[int, bytes]:
        mode = req[0]
        out: dict[int, bytes] = {}
        for rx, pids in ((0x7E8, self.ecm_pids), (0x7E9, self.tcm_pids)):
            if mode == 0x01:
                body = bytearray([0x41])
                for pid in req[1:]:
                    if pid in (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0):
                        bitmap = 0
                        for p in pids:
                            if pid < p <= pid + 32:
                                bitmap |= 1 << (32 - (p - pid))
                        if any(p > pid + 32 for p in pids):
                            bitmap |= 1
                        if bitmap:
                            body += bytes([pid]) + bitmap.to_bytes(4, "big")
                    elif pid in pids and pid in PID_SIZES:
                        body += bytes([pid]) + self.pid_bytes(pid)
                if len(body) > 1:
                    out[rx] = bytes(body)
            elif mode in (0x03, 0x07, 0x0A):
                src = self.pending if mode == 0x07 else self.stored
                codes = src.get(rx, [])
                out[rx] = bytes([mode + 0x40, len(codes)]) + b"".join(bytes(c) for c in codes)
            elif mode == 0x04:
                self.stored.pop(rx, None)
                self.pending.pop(rx, None)
                out[rx] = b"\x44"
            elif mode == 0x09 and rx == 0x7E8 and req[1:2] == b"\x02":
                out[rx] = b"\x49\x02\x01" + SIM_VIN.encode()
        return out

    def physical(self, tx: int, req: bytes) -> bytes | None:
        if tx not in self.uds_dtcs:
            return None  # módulo ausente ou em outra rede
        sid = req[0]
        if sid == 0x3E:
            return b"\x7e\x00"
        if sid == 0x22 and len(req) == 3:
            data = self.did_bytes(tx, (req[1] << 8) | req[2])
            if data is None:
                return b"\x7f\x22\x31"
            return b"\x62" + req[1:3] + data
        if sid == 0x19 and req[1:2] == b"\x02":
            return b"\x59\x02\xff" + b"".join(self.uds_dtcs[tx])
        if sid == 0x14:
            self.uds_dtcs[tx] = []
            return b"\x54"
        return bytes([0x7F, sid, 0x11])


class SimulatedTransport:
    """Implementa a mesma interface de ``SerialTransport``."""

    def __init__(self, car: SimulatedCar | None = None) -> None:
        self.car = car or SimulatedCar()
        self.header = 0x7DF
        self.spaces = True
        self._out = ""

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").strip().upper().replace(" ", "")
        self._out = self._handle(cmd)

    def read_until_prompt(self, timeout: float) -> str:
        out, self._out = self._out, ""
        return out + "\r\r>"

    def close(self) -> None:
        pass

    def _fmt(self, rx: int, payload: bytes) -> str:
        lines = []
        for fr in split_frames(payload):
            h = f"{rx:03X}"
            d = fr.hex().upper()
            if self.spaces:
                d = " ".join(d[i : i + 2] for i in range(0, len(d), 2))
                lines.append(f"{h} {d}")
            else:
                lines.append(h + d)
        return "\r".join(lines)

    def _handle(self, cmd: str) -> str:
        if cmd.startswith("AT") or cmd.startswith("ST"):
            if cmd in ("ATZ", "ATI"):
                return "ELM327 v1.4b"
            if cmd == "STI":
                return "STN2255 v5.10.3 (simulador)"
            if cmd == "ATRV":
                return "14.1V"
            if cmd.startswith("ATSH"):
                self.header = int(cmd[4:], 16)
                return "OK"
            if cmd in ("ATS0", "ATS1"):
                self.spaces = cmd == "ATS1"
                return "OK"
            known = ("ATE0", "ATL0", "ATH1", "ATAT1", "ATSP6", "ATAR", "ATCRA",
                     "ATFCSH", "ATFCSD", "ATFCSM")
            return "OK" if cmd.startswith(known) else "?"
        try:
            req = bytes.fromhex(cmd)
        except ValueError:
            return "?"
        if self.header == 0x7DF:
            resp = self.car.functional(req)
            if not resp:
                return "NO DATA"
            return "\r".join(self._fmt(rx, p) for rx, p in resp.items())
        payload = self.car.physical(self.header, req)
        if payload is None:
            return "NO DATA"
        return self._fmt(self.header + 8, payload)
