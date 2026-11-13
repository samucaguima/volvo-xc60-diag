"""Mapa de módulos da plataforma Volvo P3 (XC60 2009-2017).

Endereços de 11 bits: o módulo responde no endereço de envio + 8.

Fontes e grau de confiança:
* "verificado P3": usado com sucesso num P3 real pelo projeto
  github.com/Sebastian-Gebus/volvo-p3-dashboard (XC60/V70 diesel).
* "a confirmar": listado pelo projeto github.com/oleksandrdiadyk-glitch/volvoscan
  (XC70 2008), sem comprovação; confirme com o comando ``modulos``.

Rede: a maioria dos módulos de diagnóstico fica na CAN de alta velocidade
(pinos 6/14, opção ``--rede hs``). Os marcados como "MS-CAN (provável)" devem
ficar na rede de média velocidade (pinos 3/11, 125 kbps), acessível com
``--rede ms`` e um adaptador com chave HS/MS-CAN na posição MS (experimental).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    name: str
    tx: int
    description: str
    bus: str
    confidence: str

    @property
    def rx(self) -> int:
        return self.tx + 8


MODULES: dict[str, Module] = {
    m.name: m
    for m in [
        Module("ECM", 0x7E0, "Motor (Drive-E 2.0 turbo)", "HS-CAN", "verificado P3"),
        Module("TCM", 0x7E1, "Câmbio automático Aisin 8 marchas", "HS-CAN", "a confirmar"),
        Module("CEM", 0x726, "Central eletrônica (carroceria, bateria)", "HS-CAN", "verificado P3"),
        Module("BCM", 0x760, "Freios, ABS, controle de estabilidade, freio de estacionamento", "HS-CAN (provável)", "a confirmar"),
        Module("SRS", 0x772, "Airbags", "HS-CAN (provável)", "a confirmar"),
        Module("DIM", 0x720, "Painel de instrumentos", "MS-CAN (provável)", "a confirmar"),
        Module("CCM", 0x733, "Climatizador", "MS-CAN (provável)", "a confirmar"),
    ]
}


def on_network(network: str) -> list[Module]:
    """Módulos esperados em cada rede ("hs" ou "ms")."""
    prefix = "MS" if network == "ms" else "HS"
    return [m for m in MODULES.values() if m.bus.startswith(prefix)]


def get(name: str) -> Module:
    try:
        return MODULES[name.upper()]
    except KeyError:
        opts = ", ".join(MODULES)
        raise SystemExit(f"Módulo desconhecido: {name}. Opções: {opts}") from None
