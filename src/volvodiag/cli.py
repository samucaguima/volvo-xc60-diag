"""Linha de comando: ``volvodiag <comando>``. Use ``volvodiag -h`` para ajuda."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

from . import __version__, adapter_check, dids, modules
from .dtc import describe
from .elm327 import Elm327, ElmError
from .health import evaluate
from .labels import name as label
from .live import LivePoller, snapshot
from .obd import ObdClient
from .pids import LIVE_PIDS, PIDS
from .report import build as build_report
from .safety import BlockedRequest, SafetyGuard
from .storage import Store
from .transport import SerialTransport, TcpTransport, Transport, TransportError
from .uds import NegativeResponse, NoResponse, UdsClient

def dtc_modules(network: str) -> list[str]:
    """Módulos consultados por UDS em cada rede."""
    return [m.name for m in modules.on_network(network)]


UDS_DTC_MODULES = dtc_modules("hs")  # ECM, TCM, CEM, BCM, SRS
LEVEL_MARK = {"ok": "[ ok ]", "atenção": "[ ! ]", "alerta": "[!!!]"}


# ---------------------------------------------------------------- conexão
SIM_BAD_CLONE = ("ATS0", "ATAT1", "ATCRA", "ATFCSH", "ATFCSD", "ATFCSM", "ATPPS", "ATPB", "ATSPB")


def open_transport(args: argparse.Namespace) -> tuple[Transport, str]:
    if args.simulador:
        from .simulator import SimulatedTransport

        bad = getattr(args, "simular_clone_ruim", False)
        off = getattr(args, "simular_ignicao_desligada", False)
        transport = SimulatedTransport(
            unsupported=SIM_BAD_CLONE if bad else (), ignition_on=not off
        )
        print("*** MODO SIMULADOR: dados fictícios, nenhum carro conectado ***\n")
        return transport, "simulador"
    if args.tcp:
        host, _, port = args.tcp.partition(":")
        return TcpTransport(host, int(port or 35000)), f"tcp {args.tcp}"
    if args.porta:
        return SerialTransport(args.porta), args.porta
    raise SystemExit(
        "Informe a conexão: --porta COM5 (Bluetooth/USB), --tcp ip:porta ou --simulador.\n"
        "Para ver as portas disponíveis: volvodiag portas"
    )


class Session:
    def __init__(self, args: argparse.Namespace, allow_clear: bool = False) -> None:
        self.simulated = bool(args.simulador)
        transport, self.label = open_transport(args)
        self.transport = transport
        self.elm = Elm327(transport, SafetyGuard(allow_clear=allow_clear))
        self.network = getattr(args, "rede", None) or "hs"
        version = self.elm.initialize(self.network)
        self.label += f" · {version}"
        if self.network == "ms":
            self.label += " · rede MS-CAN"
            print("Rede MS-CAN (125 kbps, pinos 3/11): experimental. A chave do adaptador deve estar em MS.\n")
        self.obd = ObdClient(self.elm)
        self.uds = UdsClient(self.elm)

    def vin(self) -> str | None:
        if self.network == "ms":
            return None  # VIN só é lido na rede principal
        vin = self.obd.read_vin()
        if not vin:
            try:
                vin = self.uds.read_did(modules.get("CEM"), 0xF190).decode("ascii", "replace").strip()
            except (NoResponse, NegativeResponse, ElmError):
                vin = None
        return vin

    def close(self) -> None:
        self.transport.close()


def _store(args: argparse.Namespace) -> Store:
    return Store(args.db)


# --------------------------------------------------------------- comandos
def cmd_portas(args: argparse.Namespace) -> None:
    try:
        from serial.tools import list_ports
    except ImportError:
        raise SystemExit("Instale o pyserial: pip install pyserial") from None
    ports = list(list_ports.comports())
    if not ports:
        print("Nenhuma porta serial encontrada. Ligue o adaptador USB ou pareie o adaptador Bluetooth.")
    for p in ports:
        print(f"{p.device:10} {p.description}")
    print("\nAdaptador USB: aparece como 'USB-SERIAL CH340' ou 'USB Serial Port'.\n"
          "Adaptador Bluetooth: aparece como 'Serial padrão por link Bluetooth';\n"
          "se houver duas portas, use a de SAÍDA (outgoing).")


def cmd_testar_adaptador(args: argparse.Namespace) -> None:
    transport, where = open_transport(args)
    print(f"Testando o adaptador em {where}. Nada é gravado no carro.\n")
    try:
        rep = adapter_check.run(transport, test_car=True)
    finally:
        transport.close()
    print(f"Identificação: {rep.identification}\n")
    print(f"{'Resultado':10} {'Comando':14} Finalidade")
    for r in rep.results:
        mark = "ok" if r.ok else ("FALHOU" if r.check.required else "ausente")
        tag = "" if r.check.required else " (opcional)"
        print(f"{mark:10} {r.check.cmd:14} {r.check.purpose}{tag}")
        if not r.ok:
            print(f"{'':25} resposta: {r.response}")
    if rep.car_link:
        print(f"\nComunicação com o carro: {rep.car_link}")
    print()
    if rep.approved:
        print("APROVADO: o adaptador aceita todos os comandos que o volvodiag usa.")
        optional = [r.check.cmd for r in rep.results if not r.check.required and not r.ok]
        if optional:
            print("Recursos opcionais ausentes: " + ", ".join(optional) + ". Não impedem o uso atual.")
    else:
        cmds = ", ".join(r.check.cmd for r in rep.missing_required)
        print(f"REPROVADO: o adaptador recusou {cmds}.")
        print("Provável clone incompleto (chip ARM / \"v2.1\"). Se estiver no prazo, peça a troca ou devolução.")
        raise SystemExit(1)


def cmd_info(args: argparse.Namespace) -> None:
    s = Session(args)
    try:
        print(f"Adaptador: {s.label}")
        volt = s.elm.adapter_voltage()
        print(f"Tensão da bateria (medida pelo adaptador): {volt} V" if volt else "Tensão: não informada")
        print(f"VIN: {s.vin() or 'não lido'}")
        st = s.obd.monitor_status()
        if st:
            print(f"Luz de injeção: {'ACESA' if st.mil_on else 'apagada'} · códigos armazenados: {st.dtc_count}")
        sup = sorted(s.obd.supported_pids())
        print(f"\nDados OBD-II oferecidos pelo carro ({len(sup)}):")
        for pid in sup:
            p = PIDS.get(pid)
            if p:
                print(f"  {pid:02X}  {p.name}")
    finally:
        s.close()


def cmd_dtc(args: argparse.Namespace) -> None:
    s = Session(args)
    store = _store(args)
    sid = store.new_session("dtc", s.vin(), s.label, s.simulated)
    now = time.time()
    found = 0
    try:
        obd_modes = ((0x03, "armazenado"), (0x07, "pendente"), (0x0A, "permanente"))
        if s.network == "hs":
            print("== Códigos OBD-II (motor e câmbio) ==")
        else:
            obd_modes = ()  # os módulos de emissões ficam na rede principal
        for mode, label in obd_modes:
            for ecu, codes in s.obd.read_dtcs(mode).items():
                for code in codes:
                    desc = describe(code) or "sem descrição genérica"
                    print(f"  {code}  [{label}, módulo 0x{ecu:03X}]  {desc}")
                    store.add_dtc(sid, now, f"OBD {label}", code, desc)
                    found += 1
        if not args.sem_modulos:
            print(f"\n== Códigos dos módulos Volvo (UDS, rede {s.network.upper()}-CAN) ==")
            for name in dtc_modules(s.network):
                mod = modules.get(name)
                try:
                    items = s.uds.read_dtcs(mod)
                except NoResponse:
                    print(f"  {name}: sem resposta ({mod.confidence}, {mod.bus})")
                    continue
                except NegativeResponse as exc:
                    print(f"  {name}: {exc}")
                    continue
                if not items:
                    print(f"  {name}: nenhum código")
                for d in items:
                    extra = ""
                    if name in ("ECM", "TCM"):
                        desc = describe(d.sae_code)
                        extra = f" · equivalente SAE {d.sae_code}" + (f": {desc}" if desc else "")
                    detail = f"tipo 0x{d.failure_type:02X}; " + ", ".join(d.status_text) + extra
                    print(f"  {d.volvo_code}  {detail}")
                    store.add_dtc(sid, now, f"UDS {name}", d.volvo_code, detail)
                    found += 1
        print(f"\n{found} código(s) encontrado(s). Registrado na sessão {sid}.")
        if found:
            print("Códigos Volvo (ex.: CEM-A12B) não têm descrição pública nesta base; "
                  "consulte uma oficina ou documentação técnica da Volvo.")
    finally:
        store.close()
        s.close()


def cmd_apagar(args: argparse.Namespace) -> None:
    alvo = args.modulo.upper()
    network = getattr(args, "rede", None) or "hs"
    allowed = dtc_modules(network)
    if alvo not in ("MOTOR-OBD", "TODOS", *allowed) or (alvo == "MOTOR-OBD" and network == "ms"):
        opts = (["motor-obd"] if network == "hs" else []) + ["todos", *allowed]
        raise SystemExit(f"Na rede {network.upper()}-CAN use --modulo " + ", ".join(opts) + ".")
    print("ATENÇÃO: apagar códigos também zera os monitores de emissões (o carro pode\n"
          "reprovar numa inspeção até rodar o suficiente) e apaga informações úteis para a oficina.\n"
          "Os códigos atuais serão lidos e salvos no histórico antes de apagar.")
    if input("Digite APAGAR para confirmar: ").strip() != "APAGAR":
        print("Cancelado.")
        return
    cmd_dtc(argparse.Namespace(**{**vars(args), "sem_modulos": False}))
    s = Session(args, allow_clear=True)
    try:
        if alvo == "MOTOR-OBD" or (alvo == "TODOS" and network == "hs"):
            print("Motor (OBD 04):", s.obd.clear_dtcs())
        targets = allowed if alvo == "TODOS" else ([] if alvo == "MOTOR-OBD" else [alvo])
        for name in targets:
            try:
                s.uds.clear_dtcs(modules.get(name))
                print(f"{name}: apagado")
            except (NoResponse, NegativeResponse) as exc:
                print(f"{name}: {exc}")
    finally:
        s.close()


def cmd_modulos(args: argparse.Namespace) -> None:
    s = Session(args)
    try:
        print(f"Rede {s.network.upper()}-CAN\n")
        print(f"{'Módulo':6} {'Endereço':9} {'Responde':9} {'Rede':18} {'Fonte':14} Descrição")
        for m in modules.on_network(s.network):
            ok = s.uds.ping(m)
            print(f"{m.name:6} 0x{m.tx:03X}     {'sim' if ok else 'não':9} {m.bus:18} {m.confidence:14} {m.description}")
        other = "ms" if s.network == "hs" else "hs"
        names = ", ".join(dtc_modules(other))
        print(f"\nNa outra rede ({other.upper()}-CAN): {names}. Use --rede {other} para consultá-los.")
        print("Para procurar módulos em todos os endereços: volvodiag varrer-modulos")
    finally:
        s.close()


def cmd_varrer_modulos(args: argparse.Namespace) -> None:
    s = Session(args)
    known = {m.tx: m.name for m in modules.MODULES.values()}
    found: list[int] = []
    print(f"Procurando módulos de 0x700 a 0x7F7 na rede {s.network.upper()}-CAN "
          "(só a presença do testador, 3E 00, que não altera nada). Leva cerca de 1 a 2 minutos.")
    try:
        for tx in s.uds.scan_addresses(progress=lambda a: print(f"\r  0x{a:03X}", end="", flush=True)):
            found.append(tx)
            print(f"\r  0x{tx:03X} responde ({known.get(tx, 'desconhecido')})")
    except KeyboardInterrupt:
        print("\nInterrompido.")
    finally:
        s.close()
    print(f"\r{len(found)} endereço(s) responderam: " + ", ".join(f"0x{t:03X}" for t in found))
    unknown = [t for t in found if t not in known]
    if unknown:
        print("Endereços desconhecidos são módulos ainda não mapeados; envie esta lista para identificarmos.")


def cmd_ler_did(args: argparse.Namespace) -> None:
    s = Session(args)
    try:
        mod = modules.get(args.modulo)
        did = int(args.did, 16)
        data = s.uds.read_did(mod, did)
        print(f"{mod.name} {did:04X}: {data.hex(' ').upper()}")
        for d in dids.for_module(mod.name):
            if d.did == did:
                print(f"  {d.name}: {d.decode(data)} {d.unit}  ({d.source})")
    except (NoResponse, NegativeResponse) as exc:
        print(exc)
    finally:
        s.close()


def cmd_varrer(args: argparse.Namespace) -> None:
    mod = modules.get(args.modulo)
    start, end = dids.SCAN_RANGES.get(mod.name, (0xF180, 0xF1FF))
    if args.inicio:
        start = int(args.inicio, 16)
    if args.fim:
        end = int(args.fim, 16)
    if end < start or end - start > 0x0FFF:
        raise SystemExit("Faixa inválida (máximo de 4096 identificadores por varredura).")
    print(f"Varredura SOMENTE LEITURA em {mod.name}: {start:04X} a {end:04X} "
          f"({end - start + 1} pedidos). Ctrl+C interrompe.")
    s = Session(args)
    store = _store(args)
    found = 0
    try:
        for did, data in s.uds.scan_dids(mod, start, end, delay=args.atraso):
            found += 1
            store.save_did(mod.name, did, data)
            print(f"  {did:04X}: {data.hex(' ').upper()}")
    except KeyboardInterrupt:
        print("\nInterrompido.")
    except NoResponse as exc:
        print(exc)
    finally:
        print(f"{found} identificador(es) responderam. Salvos no histórico local.")
        store.close()
        s.close()


def _print_findings(values: dict[str, float]) -> None:
    for f in evaluate(values):
        print(f"  {LEVEL_MARK.get(f.level, f.level)} {f.item}: {f.message}")


def cmd_ao_vivo(args: argparse.Namespace) -> None:
    s = Session(args)
    store = None if args.sem_gravar else _store(args)
    sid = store.new_session("ao-vivo", s.vin(), s.label, s.simulated) if store else None
    poller = LivePoller(s.elm, s.obd, s.uds, args.volvo)
    if poller.missing:
        print("Não oferecidos pelo carro: " + "; ".join(poller.missing))
    if os.name == "nt":
        os.system("")  # habilita cores/ANSI no console do Windows
    t_end = time.monotonic() + args.duracao if args.duracao else None
    values: dict[str, tuple[float, str]] = {}
    try:
        while t_end is None or time.monotonic() < t_end:
            t0 = time.monotonic()
            values = poller.poll()
            if store and sid:
                store.add_samples(sid, time.time(), values)
            if sys.stdout.isatty():
                print("\033[H\033[J", end="")
            print(f"XC60 ao vivo · ciclo {poller.cycle} · {'gravando sessão ' + str(sid) if sid else 'sem gravar'} · Ctrl+C para sair")
            for key, (val, unit) in values.items():
                print(f"  {label(key):48} {val:10.2f} {unit}")
            time.sleep(max(0.0, args.intervalo - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        print("\nAvaliação do último instante:")
        _print_findings({k: v for k, (v, _) in values.items()})
        if sid:
            print(f"\nSessão {sid} gravada. Relatório: volvodiag relatorio --sessao {sid}")
        if store:
            store.close()
        s.close()


def cmd_painel(args: argparse.Namespace) -> None:
    import webbrowser

    from .web import Dashboard

    s = Session(args)
    store = None if args.sem_gravar else Store(args.db, check_same_thread=False)
    sid = store.new_session("painel", s.vin(), s.label, s.simulated) if store else None
    poller = LivePoller(s.elm, s.obd, s.uds, args.volvo)
    meta = {"adaptador": s.label, "simulado": s.simulated}
    try:
        dash = Dashboard(poller, store, sid, meta, interval=args.intervalo, port=args.porta_painel)
    except OSError as exc:
        s.close()
        raise SystemExit(f"Não foi possível abrir o painel na porta {args.porta_painel}: {exc}. "
                         "Use --porta-painel com outro número.") from None
    url = f"http://127.0.0.1:{dash.port}/"
    dash.start()
    print(f"Painel aberto em {url}  (só neste computador). Ctrl+C encerra.")
    if not args.nao_abrir:
        webbrowser.open(url)
    try:
        if args.duracao:
            time.sleep(args.duracao)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        dash.stop()
        final = dash.data()
        print("\nAvaliação do último instante:")
        _print_findings({k: v["valor"] for k, v in final["values"].items()})
        if sid:
            print(f"\nSessão {sid} gravada. Relatório: volvodiag relatorio --sessao {sid}")
        if store:
            store.close()
        s.close()


def cmd_saude(args: argparse.Namespace) -> None:
    s = Session(args)
    try:
        supported = s.obd.supported_pids()
        values = snapshot(s.obd, s.uds, [p for p in LIVE_PIDS if p in supported], volvo=True)
        st = s.obd.monitor_status()
        if st:
            values["luz_injecao"] = (float(st.mil_on), "")
            values["qtd_codigos"] = (float(st.dtc_count), "")
        volt = s.elm.adapter_voltage()
        if volt and "tensao_modulo" not in values:
            values["tensao_adaptador"] = (volt, "V")
        print("Avaliação de saúde (referências gerais, não especificações da Volvo):")
        _print_findings({k: v for k, (v, _) in values.items()})
    finally:
        s.close()


def cmd_sessoes(args: argparse.Namespace) -> None:
    store = _store(args)
    for r in store.sessions():
        sim = " (simulada)" if r["simulated"] else ""
        print(f"{r['id']:4}  {r['started_at']}  {r['kind']:8} {r['n']:6} leituras  VIN {r['vin'] or '?'}{sim}")
    store.close()


def cmd_relatorio(args: argparse.Namespace) -> None:
    store = _store(args)
    sid = args.sessao
    if sid is None:
        rows = store.sessions()
        if not rows:
            raise SystemExit("Nenhuma sessão gravada ainda.")
        sid = rows[0]["id"]
    html = build_report(store, sid)
    out = Path(args.saida or f"relatorio-sessao-{sid}.html")
    out.write_text(html, encoding="utf-8")
    print(f"Relatório salvo em {out.resolve()}")
    store.close()


def cmd_manutencao(args: argparse.Namespace) -> None:
    store = _store(args)
    if args.acao == "adicionar":
        if not args.item:
            raise SystemExit("Informe --item (ex.: 'Troca de óleo e filtro').")
        mid = store.add_maintenance(args.data or date.today().isoformat(), args.km, args.item, args.notas or "")
        print(f"Registro {mid} salvo.")
    else:
        for m in store.maintenance():
            print(f"{m['date']}  {m['km'] or '':>7} km  {m['item']}  {m['notes'] or ''}")
    store.close()


# ------------------------------------------------------------------ main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="volvodiag", description="Diagnóstico do Volvo XC60 (P3) por adaptador ELM327 (USB, Bluetooth ou Wi-Fi).")
    p.add_argument("--version", action="version", version=f"volvodiag {__version__}")
    conn = p.add_argument_group("conexão")
    conn.add_argument("--porta", help="porta serial do adaptador (ex.: COM5)")
    conn.add_argument("--tcp", help="adaptador Wi-Fi ou emulador (ip:porta)")
    conn.add_argument("--simulador", action="store_true", help="usa um XC60 simulado (dados fictícios)")
    conn.add_argument("--rede", choices=["hs", "ms"], default="hs",
                      help="hs: CAN principal, 500 kbps (padrão); ms: CAN média velocidade, 125 kbps "
                           "(experimental, exige adaptador com chave HS/MS na posição MS)")
    p.add_argument("--db", help="arquivo do histórico (padrão: ~/.volvodiag/historico.sqlite)")
    p.add_argument("--debug", action="store_true", help="mostra a conversa com o adaptador")
    sub = p.add_subparsers(dest="comando", required=True)

    sub.add_parser("portas", help="lista as portas seriais (Bluetooth/USB)").set_defaults(fn=cmd_portas)
    t = sub.add_parser("testar-adaptador", help="confere se o adaptador aceita os comandos usados (ignição pode ficar desligada)")
    t.add_argument("--simular-clone-ruim", action="store_true", help=argparse.SUPPRESS)
    t.add_argument("--simular-ignicao-desligada", action="store_true", help=argparse.SUPPRESS)
    t.set_defaults(fn=cmd_testar_adaptador)
    sub.add_parser("info", help="adaptador, VIN, luz de injeção e dados oferecidos").set_defaults(fn=cmd_info)
    d = sub.add_parser("dtc", help="lê e explica os códigos de erro")
    d.add_argument("--sem-modulos", action="store_true", help="só os códigos OBD-II do motor")
    d.set_defaults(fn=cmd_dtc)
    a = sub.add_parser("apagar-dtc", help="apaga códigos de erro (pede confirmação)")
    a.add_argument("--modulo", required=True, help="motor-obd, todos ou um módulo (ECM, TCM, CEM, BCM, SRS)")
    a.set_defaults(fn=cmd_apagar)
    sub.add_parser("modulos", help="verifica quais módulos respondem").set_defaults(fn=cmd_modulos)
    sub.add_parser("varrer-modulos", help="procura módulos em todos os endereços (não altera nada)").set_defaults(fn=cmd_varrer_modulos)
    r = sub.add_parser("ler-did", help="lê um identificador UDS de um módulo (somente leitura)")
    r.add_argument("--modulo", required=True)
    r.add_argument("--did", required=True, help="identificador em hexadecimal (ex.: 4028)")
    r.set_defaults(fn=cmd_ler_did)
    v = sub.add_parser("varrer-dids", help="descobre identificadores que um módulo responde (somente leitura)")
    v.add_argument("--modulo", required=True)
    v.add_argument("--inicio")
    v.add_argument("--fim")
    v.add_argument("--atraso", type=float, default=0.03, help="pausa entre pedidos, em segundos")
    v.set_defaults(fn=cmd_varrer)
    lv = sub.add_parser("ao-vivo", help="painel de dados em tempo real, gravando no histórico")
    lv.add_argument("--intervalo", type=float, default=1.0, help="segundos entre leituras")
    lv.add_argument("--duracao", type=float, help="encerra após N segundos")
    lv.add_argument("--volvo", action="store_true", help="inclui dados Volvo (bateria pela CEM, óleo a confirmar)")
    lv.add_argument("--sem-gravar", action="store_true")
    lv.set_defaults(fn=cmd_ao_vivo)
    pn = sub.add_parser("painel", help="painel ao vivo no navegador, gravando no histórico")
    pn.add_argument("--intervalo", type=float, default=1.0, help="segundos entre leituras")
    pn.add_argument("--volvo", action="store_true", help="inclui dados Volvo (bateria pela CEM, óleo a confirmar)")
    pn.add_argument("--sem-gravar", action="store_true")
    pn.add_argument("--porta-painel", type=int, default=8765, help="porta local do painel (padrão 8765)")
    pn.add_argument("--nao-abrir", action="store_true", help="não abre o navegador automaticamente")
    pn.add_argument("--duracao", type=float, help=argparse.SUPPRESS)
    pn.set_defaults(fn=cmd_painel)
    sub.add_parser("saude", help="avaliação rápida de bateria, arrefecimento, mistura e luz de injeção").set_defaults(fn=cmd_saude)
    sub.add_parser("sessoes", help="lista as sessões gravadas").set_defaults(fn=cmd_sessoes)
    rp = sub.add_parser("relatorio", help="gera relatório HTML de uma sessão")
    rp.add_argument("--sessao", type=int)
    rp.add_argument("--saida")
    rp.set_defaults(fn=cmd_relatorio)
    m = sub.add_parser("manutencao", help="registra e lista manutenções")
    m.add_argument("acao", choices=["adicionar", "listar"])
    m.add_argument("--data", help="AAAA-MM-DD (padrão: hoje)")
    m.add_argument("--km", type=int)
    m.add_argument("--item")
    m.add_argument("--notas")
    m.set_defaults(fn=cmd_manutencao)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rede == "ms" and args.comando in ("info", "ao-vivo", "painel", "saude"):
        raise SystemExit(f"'{args.comando}' usa a rede principal. Rode sem --rede ms "
                         "(e com a chave do adaptador em HS).")
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING, format="%(message)s")
    try:
        args.fn(args)
    except (TransportError, ElmError) as exc:
        print(f"Erro de comunicação: {exc}", file=sys.stderr)
        return 2
    except BlockedRequest as exc:
        print(f"Bloqueado pela trava de segurança: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
