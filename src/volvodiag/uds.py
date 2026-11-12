"""Leitura dos módulos Volvo por UDS (ISO 14229): dados e códigos de erro."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator

from .dtc import UdsDtc
from .elm327 import Elm327
from .modules import Module

NRC = {
    0x10: "recusa geral",
    0x11: "serviço não suportado",
    0x12: "subfunção não suportada",
    0x13: "tamanho de mensagem incorreto",
    0x14: "resposta grande demais",
    0x22: "condições não atendidas (ex.: motor ligado/desligado)",
    0x31: "identificador fora da faixa (não existe neste módulo)",
    0x33: "acesso de segurança negado",
    0x78: "módulo ocupado, resposta pendente",
    0x7E: "subfunção não suportada nesta sessão",
    0x7F: "serviço não suportado nesta sessão",
}


class NegativeResponse(Exception):
    def __init__(self, service: int, code: int) -> None:
        self.service = service
        self.code = code
        super().__init__(
            f"Resposta negativa ao serviço 0x{service:02X}: "
            f"{NRC.get(code, 'código')} (0x{code:02X})"
        )


class NoResponse(Exception):
    """O módulo não respondeu (ausente, desligado ou em outra rede)."""


class UdsClient:
    def __init__(self, elm: Elm327) -> None:
        self.elm = elm

    def _call(self, module: Module, payload: bytes, timeout: float = 2.0) -> bytes:
        self.elm.select_module(module.tx, module.rx)
        resp = self.elm.request(payload, timeout).get(module.rx)
        if resp is None:
            raise NoResponse(f"{module.name} (0x{module.tx:03X}) não respondeu.")
        if resp[0] == 0x7F and len(resp) >= 3:
            raise NegativeResponse(resp[1], resp[2])
        if resp[0] != payload[0] + 0x40:
            raise NoResponse(f"Resposta inesperada de {module.name}: {resp.hex()}")
        return resp

    def ping(self, module: Module) -> bool:
        """Presença do testador (3E 00): só confirma que o módulo responde."""
        try:
            self._call(module, b"\x3e\x00", timeout=1.0)
            return True
        except (NoResponse, NegativeResponse):
            return False

    def read_did(self, module: Module, did: int) -> bytes:
        resp = self._call(module, bytes([0x22, did >> 8, did & 0xFF]))
        if resp[1:3] != bytes([did >> 8, did & 0xFF]):
            raise NoResponse(f"{module.name} respondeu outro identificador: {resp[1:3].hex()}")
        return resp[3:]

    def read_dtcs(self, module: Module, status_mask: int = 0xFF) -> list[UdsDtc]:
        """19 02: códigos de erro filtrados pela máscara de estado."""
        resp = self._call(module, bytes([0x19, 0x02, status_mask]), timeout=3.0)
        body = resp[3:]  # 59 02 <máscara disponível> + registros de 4 bytes
        return [UdsDtc(module.name, body[i : i + 4]) for i in range(0, len(body) - 3, 4)]

    def clear_dtcs(self, module: Module) -> None:
        """14 FF FF FF. Bloqueado pela trava, a menos que autorizado."""
        self._call(module, b"\x14\xff\xff\xff", timeout=5.0)

    def scan_dids(
        self,
        module: Module,
        start: int,
        end: int,
        delay: float = 0.03,
        progress: Callable[[int], None] | None = None,
    ) -> Iterator[tuple[int, bytes]]:
        """Varre identificadores com o serviço 22 (somente leitura).

        Devolve apenas os identificadores que o módulo respondeu. Respostas
        negativas (não existe, condição não atendida) são ignoradas.
        """
        silent = 0
        for did in range(start, end + 1):
            if progress:
                progress(did)
            try:
                yield did, self.read_did(module, did)
                silent = 0
            except NegativeResponse:
                silent = 0
            except NoResponse:
                silent += 1
                if silent >= 10:
                    raise NoResponse(
                        f"{module.name} parou de responder (10 pedidos seguidos sem resposta)."
                    ) from None
            if delay:
                time.sleep(delay)
