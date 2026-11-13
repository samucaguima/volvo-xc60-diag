"""Canais de comunicação com o adaptador ELM327/OBDLink.

* ``SerialTransport``: porta COM (Bluetooth SPP do OBDLink MX+ ou USB).
* ``TcpTransport``: adaptadores Wi-Fi e o emulador ELM327-emulator.
* O simulador de XC60 fica em ``volvodiag.simulator``.
"""

from __future__ import annotations

import socket
import time
from typing import Protocol

PROMPT = b">"


class TransportError(Exception):
    """Falha de comunicação com o adaptador."""


class Transport(Protocol):
    def write(self, data: bytes, keep_input: bool = False) -> None: ...

    def read_until_prompt(self, timeout: float) -> str: ...

    def close(self) -> None: ...


def _decode(buf: bytes) -> str:
    return buf.replace(PROMPT, b"").decode("ascii", errors="replace")


class SerialTransport:
    def __init__(self, port: str, baudrate: int = 115200) -> None:
        try:
            import serial  # pyserial
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise TransportError("Instale o pyserial: pip install pyserial") from exc
        self._serial_error = serial.SerialException
        try:
            self._ser = serial.Serial(port, baudrate=baudrate, timeout=0.05)
        except Exception as exc:  # serial.SerialException
            raise TransportError(f"Não foi possível abrir {port}: {exc}") from exc

    def write(self, data: bytes, keep_input: bool = False) -> None:
        try:
            if not keep_input:
                self._ser.reset_input_buffer()
            self._ser.write(data)
            self._ser.flush()
        except (OSError, self._serial_error) as exc:
            raise TransportError(f"Conexão com o adaptador perdida: {exc}") from exc

    def read_until_prompt(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            try:
                chunk = self._ser.read(self._ser.in_waiting or 1)
            except (OSError, self._serial_error) as exc:
                raise TransportError(f"Conexão com o adaptador perdida: {exc}") from exc
            if chunk:
                buf.extend(chunk)
                if PROMPT in chunk:
                    return _decode(bytes(buf))
        raise TransportError(f"Sem resposta do adaptador em {timeout:.1f} s.")

    def close(self) -> None:
        self._ser.close()


class TcpTransport:
    def __init__(self, host: str, port: int) -> None:
        try:
            self._sock = socket.create_connection((host, port), timeout=5)
        except OSError as exc:
            raise TransportError(f"Não foi possível conectar a {host}:{port}: {exc}") from exc
        self._sock.settimeout(0.05)

    def write(self, data: bytes, keep_input: bool = False) -> None:
        try:
            self._sock.sendall(data)
        except OSError as exc:
            raise TransportError(f"Conexão com o adaptador perdida: {exc}") from exc

    def read_until_prompt(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                continue
            except OSError as exc:
                raise TransportError(f"Conexão com o adaptador perdida: {exc}") from exc
            if not chunk:
                raise TransportError("Conexão encerrada pelo adaptador.")
            buf.extend(chunk)
            if PROMPT in chunk:
                return _decode(bytes(buf))
        raise TransportError(f"Sem resposta do adaptador em {timeout:.1f} s.")

    def close(self) -> None:
        self._sock.close()
