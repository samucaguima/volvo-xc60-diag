"""Trava de segurança: só deixa sair para o carro pedidos de LEITURA.

Toda requisição enviada aos módulos passa por ``SafetyGuard.check``. Serviços
que gravam, reprogramam, reiniciam ou desbloqueiam módulos são sempre
recusados. O apagamento de códigos de erro só é aceito quando habilitado
explicitamente (``allow_clear=True``), o que a linha de comando faz apenas
depois de uma confirmação digitada pelo usuário.
"""

from __future__ import annotations

from dataclasses import dataclass

# Serviços OBD-II (SAE J1979) e UDS (ISO 14229) que apenas leem dados.
READ_ONLY_SERVICES: dict[int, str] = {
    0x01: "OBD 01 - dados atuais",
    0x02: "OBD 02 - dados congelados (freeze frame)",
    0x03: "OBD 03 - códigos de erro armazenados",
    0x06: "OBD 06 - resultados de monitores",
    0x07: "OBD 07 - códigos de erro pendentes",
    0x09: "OBD 09 - informações do veículo (VIN)",
    0x0A: "OBD 0A - códigos de erro permanentes",
    0x19: "UDS 19 - leitura de códigos de erro",
    0x22: "UDS 22 - leitura de dado por identificador",
    0x3E: "UDS 3E - presença do testador (não altera nada)",
}

# Serviços que apagam códigos de erro: só com autorização explícita.
CLEAR_SERVICES: dict[int, str] = {
    0x04: "OBD 04 - apagar códigos de erro do motor",
    0x14: "UDS 14 - apagar códigos de erro do módulo",
}

# Exemplos de serviços sempre bloqueados (lista informativa; o bloqueio
# vale para QUALQUER serviço fora das duas listas acima).
ALWAYS_BLOCKED: dict[int, str] = {
    0x10: "UDS 10 - troca de sessão de diagnóstico",
    0x11: "UDS 11 - reinicialização do módulo",
    0x27: "UDS 27 - desbloqueio de segurança",
    0x28: "UDS 28 - controle de comunicação",
    0x2E: "UDS 2E - gravação de dado",
    0x2F: "UDS 2F - acionamento de componentes",
    0x31: "UDS 31 - execução de rotinas",
    0x34: "UDS 34 - início de reprogramação",
    0x36: "UDS 36 - transferência de dados",
    0x3D: "UDS 3D - gravação de memória",
    0x85: "UDS 85 - controle de registro de falhas",
}


class BlockedRequest(Exception):
    """Pedido recusado pela trava de segurança."""


@dataclass
class SafetyGuard:
    allow_clear: bool = False

    def check(self, payload: bytes) -> None:
        if not payload:
            raise BlockedRequest("Pedido vazio.")
        sid = payload[0]
        if sid in READ_ONLY_SERVICES:
            return
        if sid in CLEAR_SERVICES:
            if self.allow_clear:
                return
            raise BlockedRequest(
                f"{CLEAR_SERVICES[sid]}: apagar códigos exige confirmação explícita."
            )
        name = ALWAYS_BLOCKED.get(sid, f"serviço 0x{sid:02X}")
        raise BlockedRequest(
            f"{name}: bloqueado. Este sistema não grava nem reprograma módulos."
        )
