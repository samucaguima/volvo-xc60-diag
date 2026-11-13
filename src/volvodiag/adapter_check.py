"""Teste do adaptador ELM327: confere se ele aceita os comandos que o sistema usa.

Feito para ser rodado logo que o adaptador chegar, ainda no prazo de
devolução. Basta encaixá-lo no carro com a IGNIÇÃO DESLIGADA: a tomada OBD
fornece energia ao adaptador e só os comandos internos dele são testados,
nada é enviado aos módulos do carro. Se a ignição estiver ligada, um último
teste opcional confirma também a comunicação com o motor.

Clones de ELM327 com chip ARM ("v2.1") costumam recusar parte desses
comandos (respondem "?"); os de chip PIC18F25K80 costumam aceitar todos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .elm327 import Elm327, ElmError
from .transport import Transport, TransportError


@dataclass(frozen=True)
class Check:
    cmd: str
    purpose: str
    required: bool
    expect: str = "OK"  # "OK", "V" (tensão) ou "ANY" (qualquer resposta que não seja erro)


CHECKS: list[Check] = [
    Check("ATE0", "desligar o eco", True),
    Check("ATL0", "desligar quebras de linha extras", True),
    Check("ATS0", "respostas sem espaços (mais rápido no Bluetooth)", True),
    Check("ATH1", "mostrar o endereço de quem respondeu", True),
    Check("ATAT1", "temporização adaptativa", True),
    Check("ATSP6", "protocolo CAN 11 bits 500 kbps (rede principal do XC60)", True),
    Check("ATSH7E0", "escolher o módulo de destino", True),
    Check("ATCRA7E8", "filtrar respostas de um único módulo", True),
    Check("ATFCSH7E0", "controle de fluxo: endereço (mensagens longas)", True),
    Check("ATFCSD300000", "controle de fluxo: dados", True),
    Check("ATFCSM1", "controle de fluxo: modo manual", True),
    Check("ATAR", "voltar ao filtro automático", True),
    Check("ATRV", "ler a tensão da bateria", True, expect="V"),
    Check("ATPPS", "parâmetros programáveis (indício de clone mais completo)", False, expect="ANY"),
    Check("ATSPB", "protocolo B, 125 kbps (rede MS-CAN, uso futuro)", False),
]


@dataclass
class Result:
    check: Check
    ok: bool
    response: str


@dataclass
class Report:
    identification: str
    results: list[Result]
    car_link: str | None  # None: não testado

    @property
    def missing_required(self) -> list[Result]:
        return [r for r in self.results if r.check.required and not r.ok]

    @property
    def approved(self) -> bool:
        return not self.missing_required


def _matches(check: Check, lines: list[str]) -> bool:
    text = " ".join(lines).upper()
    if check.expect == "OK":
        return "OK" in text
    if check.expect == "V":
        return re.search(r"\d+(\.\d+)?\s*V", text) is not None
    return bool(lines)


def run(transport: Transport, test_car: bool = True) -> Report:
    """Executa os testes. Não envia nenhum pedido de escrita ao carro."""
    elm = Elm327(transport)
    try:
        boot = elm.command("ATZ", timeout=5.0)
    except TransportError as exc:
        raise TransportError(
            "O adaptador não respondeu. Adaptadores USB recebem energia da tomada OBD: "
            "encaixe-o no carro (a ignição pode ficar desligada) e confira a porta COM."
        ) from exc
    try:
        ident = elm.command("ATI")
    except ElmError:
        ident = boot
    identification = (ident or boot or ["desconhecido"])[-1]

    results: list[Result] = []
    for chk in CHECKS:
        try:
            lines = elm.command(chk.cmd, timeout=3.0)
            results.append(Result(chk, _matches(chk, lines), " | ".join(lines)[:60] or "(vazio)"))
        except ElmError:
            results.append(Result(chk, False, "?  (comando não reconhecido)"))
        except TransportError:
            results.append(Result(chk, False, "sem resposta"))

    car_link: str | None = None
    if test_car:
        try:
            elm.command("ATSP6")
            elm.select_functional()
        except (ElmError, TransportError) as exc:
            car_link = f"não testada: o próprio adaptador recusou um comando ({exc})"
        else:
            try:
                resp = elm.request(b"\x01\x00", timeout=5.0)
                car_link = (
                    f"ok: {len(resp)} módulo(s) responderam" if resp
                    else "sem resposta do carro (ignição desligada?)"
                )
            except (ElmError, TransportError) as exc:
                car_link = f"sem comunicação com o carro ({exc}); normal com a ignição desligada"

    try:  # devolve o adaptador às configurações de fábrica
        elm.command("ATD")
    except (ElmError, TransportError):
        pass
    return Report(identification, results, car_link)
