"""Regras de saúde a partir dos dados lidos.

Os limites são referências gerais de mecânica para motores a gasolina
turbo, NÃO são especificações oficiais da Volvo. Servem para chamar atenção,
não para diagnosticar. Confirme qualquer alerta com uma oficina.
"""

from __future__ import annotations

from dataclasses import dataclass

OK, ATENCAO, ALERTA = "ok", "atenção", "alerta"


@dataclass
class Finding:
    level: str
    item: str
    message: str


def evaluate(v: dict[str, float]) -> list[Finding]:
    """Avalia um instantâneo {chave: valor} (chaves de pids.py e dids.py)."""
    out: list[Finding] = []
    rpm = v.get("rpm")
    running = rpm is not None and rpm > 400

    # Bateria / carga
    volt = v.get("tensao_modulo", v.get("tensao_adaptador"))
    if volt is not None:
        if running:
            if volt < 12.6:
                out.append(Finding(ALERTA, "Carga", f"{volt:.2f} V com motor ligado: alternador pode não estar carregando."))
            elif volt > 15.0:
                out.append(Finding(ALERTA, "Carga", f"{volt:.2f} V: tensão alta, verifique o regulador."))
            else:
                out.append(Finding(OK, "Carga", f"{volt:.2f} V com motor ligado."))
        else:
            if volt < 11.8:
                out.append(Finding(ALERTA, "Bateria", f"{volt:.2f} V com motor desligado: bateria muito descarregada."))
            elif volt < 12.3:
                out.append(Finding(ATENCAO, "Bateria", f"{volt:.2f} V com motor desligado: bateria fraca ou descarregada."))
            else:
                out.append(Finding(OK, "Bateria", f"{volt:.2f} V com motor desligado."))

    soc = v.get("carga_bateria")
    if soc is not None:
        lvl = ALERTA if soc < 50 else ATENCAO if soc < 70 else OK
        out.append(Finding(lvl, "Estado de carga (CEM)", f"{soc:.0f} %"))

    # Arrefecimento
    ect = v.get("temp_arrefecimento")
    runtime = v.get("tempo_motor_ligado", 0)
    if ect is not None:
        if ect >= 110:
            out.append(Finding(ALERTA, "Arrefecimento", f"{ect:.0f} °C: superaquecimento. Pare com segurança."))
        elif ect >= 104:
            out.append(Finding(ATENCAO, "Arrefecimento", f"{ect:.0f} °C: acima do normal."))
        elif running and runtime > 900 and ect < 75:
            out.append(Finding(ATENCAO, "Arrefecimento", f"{ect:.0f} °C após {runtime / 60:.0f} min: possível válvula termostática aberta."))
        else:
            out.append(Finding(OK, "Arrefecimento", f"{ect:.0f} °C"))

    # Óleo
    oil = v.get("temp_oleo", v.get("temp_oleo_volvo"))
    if oil is not None:
        lvl = ALERTA if oil >= 135 else ATENCAO if oil >= 125 else OK
        out.append(Finding(lvl, "Óleo do motor", f"{oil:.0f} °C"))

    # Mistura ar/combustível (só faz sentido com motor ligado)
    st, lt = v.get("stft_b1"), v.get("ltft_b1")
    if running and lt is not None:
        total = lt + (st or 0)
        if abs(total) > 20:
            lvl = ALERTA
        elif abs(lt) > 10 or abs(total) > 15:
            lvl = ATENCAO
        else:
            lvl = OK
        hint = ""
        if lvl != OK:
            hint = (" Mistura pobre: possível entrada falsa de ar, bomba ou bico."
                    if total > 0 else " Mistura rica: possível sensor, bico ou pressão de combustível.")
        out.append(Finding(lvl, "Mistura", f"curto {st or 0:+.1f} %, longo {lt:+.1f} %.{hint}"))

    # Luz de injeção
    mil = v.get("luz_injecao")
    if mil is not None:
        n = int(v.get("qtd_codigos", 0))
        if mil:
            out.append(Finding(ALERTA, "Luz de injeção", f"acesa, {n} código(s) armazenado(s)."))
        elif n:
            out.append(Finding(ATENCAO, "Códigos de erro", f"{n} código(s) sem acender a luz."))
        else:
            out.append(Finding(OK, "Luz de injeção", "apagada, sem códigos."))
    return out
