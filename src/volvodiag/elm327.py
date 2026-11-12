"""Controle do adaptador ELM327 / OBDLink (STN) pela rede CAN de alta velocidade.

Configuração usada (XC60 P3, conector OBD-II pinos 6 e 14):
ISO 15765-4, CAN 11 bits, 500 kbps (ATSP6), cabeçalhos ligados (ATH1),
espaços desligados (ATS0) para reduzir o tráfego pelo Bluetooth.
"""

from __future__ import annotations

import logging
import re

from .isotp import Frame, reassemble
from .safety import SafetyGuard
from .transport import Transport

log = logging.getLogger(__name__)

FUNCTIONAL_HEADER = 0x7DF  # pedido OBD-II para todos os módulos de emissões

_ERRORS = {
    "?": "o adaptador não reconheceu o comando",
    "CANERROR": "erro no barramento CAN (ignição desligada ou conexão ruim?)",
    "BUSERROR": "erro no barramento",
    "UNABLETOCONNECT": "o adaptador não conseguiu se comunicar com o carro (ignição ligada?)",
    "BUFFERFULL": "memória do adaptador cheia",
    "STOPPED": "operação interrompida",
    "DATAERROR": "erro nos dados recebidos",
    "FBERROR": "erro de retorno elétrico no adaptador",
    "ACTALERT": "o adaptador entrou em modo de economia",
    "LVRESET": "tensão baixa: o adaptador reiniciou",
}
_IGNORED = ("SEARCHING", "BUSINIT", "OK")
_HEX = re.compile(r"^[0-9A-F]+$")


class ElmError(Exception):
    """Erro informado pelo adaptador."""


class Elm327:
    def __init__(self, transport: Transport, guard: SafetyGuard | None = None) -> None:
        self.transport = transport
        self.guard = guard or SafetyGuard()
        self._target: tuple[int, int | None] | None = None
        self.version = ""

    # ------------------------------------------------------------------ AT
    def command(self, cmd: str, timeout: float = 2.0) -> list[str]:
        """Envia um comando AT/ST interno e devolve as linhas da resposta."""
        log.debug(">> %s", cmd)
        self.transport.write((cmd + "\r").encode("ascii"))
        raw = self.transport.read_until_prompt(timeout).replace(">", "")
        lines = [ln.strip() for ln in re.split(r"[\r\n]+", raw) if ln.strip()]
        log.debug("<< %s", lines)
        for ln in lines:
            key = ln.replace(" ", "").upper()
            if key in _ERRORS:
                raise ElmError(f"{cmd}: {_ERRORS[key]}")
        return lines

    def initialize(self) -> str:
        """Reinicia e configura o adaptador. Devolve a identificação dele."""
        lines = self.command("ATZ", timeout=5.0)
        for cmd in ("ATE0", "ATL0", "ATS0", "ATH1", "ATAT1", "ATSP6"):
            self.command(cmd)
        ident = self.command("ATI")
        self.version = ident[-1] if ident else (lines[-1] if lines else "")
        try:  # adaptadores OBDLink respondem ao STI com o modelo do chip STN
            sti = self.command("STI")
            if sti:
                self.version += f" ({sti[-1]})"
        except ElmError:
            pass
        self._target = None
        return self.version

    def adapter_voltage(self) -> float | None:
        """Tensão medida pelo próprio adaptador no pino 16 (bateria)."""
        lines = self.command("ATRV")
        for ln in lines:
            m = re.search(r"(\d+(?:\.\d+)?)\s*V", ln.upper())
            if m:
                return float(m.group(1))
        return None

    # ------------------------------------------------------------ destino
    def select_functional(self) -> None:
        """Pedidos OBD-II padrão, respondidos por todos os módulos de emissões."""
        if self._target == (FUNCTIONAL_HEADER, None):
            return
        self.command(f"ATSH{FUNCTIONAL_HEADER:03X}")
        self.command("ATAR")
        self.command("ATFCSM0")
        self._target = (FUNCTIONAL_HEADER, None)

    def select_module(self, tx: int, rx: int) -> None:
        """Conversa com um único módulo (endereço de envio e de resposta)."""
        if self._target == (tx, rx):
            return
        self.command(f"ATSH{tx:03X}")
        self.command(f"ATCRA{rx:03X}")
        # controle de fluxo explícito para mensagens longas
        self.command(f"ATFCSH{tx:03X}")
        self.command("ATFCSD300000")
        self.command("ATFCSM1")
        self._target = (tx, rx)

    # ------------------------------------------------------------ pedido
    def request(self, payload: bytes, timeout: float = 2.0) -> dict[int, bytes]:
        """Envia um pedido de diagnóstico e devolve {endereço: resposta}.

        Passa sempre pela trava de segurança. ``{}`` significa sem resposta
        (NO DATA).
        """
        self.guard.check(payload)
        hexcmd = payload.hex().upper()
        log.debug(">> %s", hexcmd)
        self.transport.write((hexcmd + "\r").encode("ascii"))
        raw = self.transport.read_until_prompt(timeout).replace(">", "")
        frames: list[Frame] = []
        for line in re.split(r"[\r\n]+", raw):
            key = line.replace(" ", "").strip().upper()
            if not key or key.startswith(_IGNORED):
                continue
            if key == "NODATA":
                return {}
            if key in _ERRORS:
                raise ElmError(f"{hexcmd}: {_ERRORS[key]}")
            if _HEX.match(key) and len(key) > 3 and (len(key) - 3) % 2 == 0:
                frames.append((int(key[:3], 16), bytes.fromhex(key[3:])))
            else:
                log.debug("linha ignorada: %r", line)
        log.debug("<< %s", [(f"{a:03X}", d.hex()) for a, d in frames])
        return reassemble(frames)
