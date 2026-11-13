"""Leitura periódica dos dados ao vivo, usada pelo terminal (ao-vivo) e pelo painel web."""

from __future__ import annotations

from . import dids, modules
from .elm327 import Elm327, ElmError
from .obd import ObdClient
from .pids import LIVE_PIDS, PIDS
from .uds import NegativeResponse, NoResponse, UdsClient

Values = dict[str, tuple[float, str]]  # chave -> (valor, unidade)

# Dados Volvo lidos com --volvo: (módulo, identificador)
VOLVO_LIVE = (("CEM", 0x4028), ("ECM", 0xD9DC))


def snapshot(obd: ObdClient, uds: UdsClient, pids: list[int], volvo: bool) -> Values:
    """Um instantâneo dos dados OBD-II (e, se pedido, dos dados Volvo)."""
    values: Values = {}
    for r in obd.read_pids(pids):
        if r.ecu == 0x7E8 or r.key not in values:  # prefere o módulo do motor
            values[r.key] = (r.value, r.unit)
    if "map" in values and "pressao_barometrica" in values:
        values["pressao_turbo"] = (round(values["map"][0] - values["pressao_barometrica"][0], 1), "kPa")
    if volvo:
        for name, did in VOLVO_LIVE:
            spec = next(d for d in dids.for_module(name) if d.did == did)
            try:
                val = spec.decode(uds.read_did(modules.get(name), did))
                if isinstance(val, (int, float)):
                    values[spec.key] = (float(val), spec.unit)
            except (NoResponse, NegativeResponse, ElmError, IndexError):
                pass
    return values


class LivePoller:
    """Faz um ciclo de leitura por chamada a ``poll``.

    Luz de injeção, quantidade de códigos e tensão do adaptador mudam devagar
    e são lidos a cada ``slow_every`` ciclos, para não atrasar o painel.
    """

    def __init__(self, elm: Elm327, obd: ObdClient, uds: UdsClient, volvo: bool, slow_every: int = 10) -> None:
        self.elm, self.obd, self.uds, self.volvo = elm, obd, uds, volvo
        self.slow_every = slow_every
        supported = obd.supported_pids()
        self.pids = [p for p in LIVE_PIDS if p in supported]
        self.missing = [PIDS[p].name for p in LIVE_PIDS if p not in supported]
        self.cycle = 0
        self._slow: Values = {}

    def poll(self) -> Values:
        if self.cycle % self.slow_every == 0:
            st = self.obd.monitor_status()
            if st:
                self._slow["luz_injecao"] = (float(st.mil_on), "")
                self._slow["qtd_codigos"] = (float(st.dtc_count), "")
            volt = self.elm.adapter_voltage()
            if volt:
                self._slow["tensao_adaptador"] = (volt, "V")
        self.cycle += 1
        return {**snapshot(self.obd, self.uds, self.pids, self.volvo), **self._slow}
