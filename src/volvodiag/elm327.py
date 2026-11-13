"""Controle do adaptador ELM327 / OBDLink (STN) pela rede CAN de alta velocidade.

Configuração usada (XC60 P3, conector OBD-II pinos 6 e 14):
ISO 15765-4, CAN 11 bits, 500 kbps (ATSP6), cabeçalhos ligados (ATH1),
espaços desligados (ATS0) para reduzir o tráfego pelo Bluetooth.
"""

from __future__ import annotations

import logging
import re
import time

from .isotp import Frame, reassemble
from .safety import SafetyGuard
from .transport import Transport

log = logging.getLogger(__name__)

FUNCTIONAL_HEADER = 0x7DF  # pedido OBD-II para todos os módulos de emissões

# Comandos de protocolo por rede. "ms": protocolo B do ELM327 configurado só
# para esta sessão (AT PB 81 04 = CAN 11 bits, quadros de 8 bytes, formatação
# ISO 15765-4, 500/4 = 125 kbps; datasheet ELM327, PP 2C e 2D).
NETWORKS: dict[str, tuple[str, ...]] = {
    "hs": ("ATSP6",),
    "ms": ("ATPB8104", "ATSPB"),
}

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
        self._target: tuple[int, int | None, bool] | None = None
        self._fc_mode: int | None = None  # modo de controle de fluxo já configurado
        self.version = ""
        self.network = "hs"
        self.is_stn = False

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

    def initialize(self, network: str = "hs") -> str:
        """Reinicia e configura o adaptador. Devolve a identificação dele.

        ``network``: "hs" para a CAN de alta velocidade (500 kbps, pinos 6/14)
        ou "ms" para a de média velocidade (125 kbps, pinos 3/11). A rede "ms"
        exige um adaptador ELM327 com chave HS/MS-CAN na posição MS; antes de
        transmitir nela, use ``verify_ms_bus``.
        """
        if network not in NETWORKS:
            raise ValueError(f"rede desconhecida: {network}")
        lines = self.command("ATZ", timeout=5.0)
        for cmd in ("ATE0", "ATL0", "ATS0", "ATH1", "ATAT1"):
            self.command(cmd)
        ident = self.command("ATI")
        self.version = ident[-1] if ident else (lines[-1] if lines else "")
        self.is_stn = False
        try:  # adaptadores OBDLink respondem ao STI com o modelo do chip STN
            sti = self.command("STI")
            if sti:
                self.version += f" ({sti[-1]})"
                self.is_stn = True
        except ElmError:
            pass
        if network == "ms" and self.is_stn:
            raise ElmError(
                "a rede MS-CAN ainda não é suportada em adaptadores OBDLink/STN: neles o "
                "protocolo B continua nos pinos 6/14 da rede principal. Use um ELM327 com chave HS/MS."
            )
        for cmd in NETWORKS[network]:  # só configura; nada é transmitido aqui
            self.command(cmd)
        self.network = network
        self._target = None
        self._fc_mode = None
        return self.version

    def listen(self, seconds: float = 1.5) -> list[str]:
        """Escuta o barramento em silêncio (AT CSM1 + AT MA): o ELM327 não
        transmite nem confirma mensagens nesse modo (datasheet, comandos CSM e MA).
        Devolve as linhas recebidas."""
        self.command("ATCSM1")
        log.debug(">> ATMA (%.1f s)", seconds)
        self.transport.write(b"ATMA\r")
        time.sleep(seconds)
        self.transport.write(b"\r", keep_input=True)  # qualquer caractere interrompe
        raw = self.transport.read_until_prompt(3.0).replace(">", "")
        lines = [ln.strip() for ln in re.split(r"[\r\n]+", raw) if ln.strip()]
        log.debug("<< %s", lines[:20])
        return lines

    def verify_ms_bus(self, seconds: float = 1.5) -> tuple[bool, str]:
        """Confere, só escutando, se o adaptador está mesmo numa rede a 125 kbps.

        Evita transmitir a 125 kbps na rede principal (500 kbps), o que
        aconteceria com a chave do adaptador na posição HS.
        """
        lines = self.listen(seconds)
        keys = [ln.replace(" ", "").upper() for ln in lines]
        frames = [k for k in keys if _HEX.match(k) and len(k) > 3 and (len(k) - 3) % 2 == 0]
        errors = [k for k in keys if "ERROR" in k]
        if errors:
            return False, (f"erros de recepção ({errors[0]}): a velocidade não confere. "
                           "A chave do adaptador provavelmente está em HS.")
        if len(frames) >= 2 or "BUFFERFULL" in keys:
            return True, f"{len(frames)} mensagem(ns) válida(s) ouvida(s) a 125 kbps"
        return False, ("nenhuma mensagem ouvida a 125 kbps. Confira se a ignição está ligada "
                       "e se a chave do adaptador está em MS.")

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
        if self.network != "hs":
            raise ElmError("pedidos OBD-II padrão só existem na rede principal (rode sem --rede ms)")
        if self._target == (FUNCTIONAL_HEADER, None, False):
            return
        self.command(f"ATSH{FUNCTIONAL_HEADER:03X}")
        self.command("ATAR")
        self.command("ATFCSM0")
        self._fc_mode = 0
        self._target = (FUNCTIONAL_HEADER, None, False)

    def select_module(self, tx: int, rx: int, flow_control: bool = True) -> None:
        """Conversa com um único módulo (endereço de envio e de resposta).

        ``flow_control=False`` pula a configuração de mensagens longas, útil
        para pedidos de resposta curta como a varredura de módulos.
        """
        same = self._target is not None and self._target[:2] == (tx, rx)
        if same and (self._target[2] or not flow_control):
            return
        if not same:
            self.command(f"ATSH{tx:03X}")
            self.command(f"ATCRA{rx:03X}")
        if flow_control:
            # controle de fluxo explícito para mensagens longas
            self.command(f"ATFCSH{tx:03X}")
            if self._fc_mode != 1:
                self.command("ATFCSD300000")
                self.command("ATFCSM1")
                self._fc_mode = 1
        self._target = (tx, rx, flow_control)

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
