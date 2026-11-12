"""Nomes em português de todos os valores exibidos e gravados."""

from .dids import DIDS
from .pids import PIDS

NAMES: dict[str, str] = {p.key: p.name for p in PIDS.values()}
NAMES.update({d.key: d.name for d in DIDS})
NAMES.update({
    "pressao_turbo": "Pressão do turbo, relativa (negativo = vácuo)",
    "tensao_adaptador": "Tensão da bateria (adaptador)",
    "carga_bateria": "Estado de carga da bateria (CEM)",
    "temp_oleo_volvo": "Temperatura do óleo (Volvo, a confirmar)",
    "pressao_turbo_volvo": "Pressão no coletor, absoluta (Volvo, a confirmar)",
    "luz_injecao": "Luz de injeção (1 = acesa)",
    "qtd_codigos": "Quantidade de códigos armazenados",
})


def name(key: str) -> str:
    return NAMES.get(key, key)
