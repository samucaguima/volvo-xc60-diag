"""Remontagem de mensagens ISO-TP (ISO 15765-2) a partir dos quadros CAN.

Com cabeçalhos ligados (ATH1), o ELM327 mostra cada quadro CAN recebido, já
com o byte de controle (PCI). Mensagens longas (por exemplo, o VIN) chegam
divididas em um quadro inicial e quadros consecutivos; aqui elas são
remontadas por endereço de resposta.
"""

from __future__ import annotations


class IsoTpError(Exception):
    """Quadros inconsistentes."""


Frame = tuple[int, bytes]  # (endereço CAN, bytes de dados incluindo o PCI)


def reassemble(frames: list[Frame]) -> dict[int, bytes]:
    """Agrupa quadros por endereço e devolve a mensagem completa de cada um.

    Se o mesmo endereço enviar mais de uma mensagem, as mensagens são
    concatenadas na ordem de chegada (caso raro em diagnóstico).
    """
    by_addr: dict[int, list[bytes]] = {}
    for addr, data in frames:
        by_addr.setdefault(addr, []).append(data)

    result: dict[int, bytes] = {}
    for addr, datas in by_addr.items():
        out = bytearray()
        pending = bytearray()
        expected = 0
        next_seq = 1
        for data in datas:
            if not data:
                continue
            kind = data[0] >> 4
            if kind == 0:  # quadro único
                length = data[0] & 0x0F
                out.extend(data[1 : 1 + length])
            elif kind == 1:  # quadro inicial
                expected = ((data[0] & 0x0F) << 8) | data[1]
                pending = bytearray(data[2:])
                next_seq = 1
            elif kind == 2:  # quadro consecutivo
                if not expected:
                    raise IsoTpError(f"Quadro consecutivo sem quadro inicial em 0x{addr:03X}.")
                seq = data[0] & 0x0F
                if seq != next_seq:
                    raise IsoTpError(
                        f"Sequência ISO-TP fora de ordem em 0x{addr:03X}: "
                        f"esperado {next_seq}, recebido {seq}."
                    )
                pending.extend(data[1:])
                next_seq = (next_seq + 1) & 0x0F
                if len(pending) >= expected:
                    out.extend(pending[:expected])
                    pending = bytearray()
                    expected = 0
            # tipo 3 (controle de fluxo) é ignorado
        if expected:
            raise IsoTpError(
                f"Mensagem incompleta de 0x{addr:03X}: {len(pending)} de {expected} bytes."
            )
        result[addr] = bytes(out)
    return result


def split_frames(payload: bytes, pad: int = 0x55) -> list[bytes]:
    """Divide uma mensagem em quadros ISO-TP de 8 bytes (usado pelo simulador)."""
    if len(payload) <= 7:
        frame = bytes([len(payload)]) + payload
        return [frame.ljust(8, bytes([pad]))]
    frames = [bytes([0x10 | (len(payload) >> 8), len(payload) & 0xFF]) + payload[:6]]
    rest = payload[6:]
    seq = 1
    while rest:
        chunk, rest = rest[:7], rest[7:]
        frames.append((bytes([0x20 | seq]) + chunk).ljust(8, bytes([pad])))
        seq = (seq + 1) & 0x0F
    return frames
