# volvo-xc60-diag

Sistema de diagnóstico **somente leitura** para o Volvo XC60 2014 (plataforma P3,
motor Drive-E 2.0 turbo, câmbio automático Aisin de 8 marchas), usando um
adaptador **OBDLink MX+** (Bluetooth) ou outro compatível com ELM327.

> **Estado:** versão 0.1, testada em simulador e num emulador ELM327
> independente. **Ainda não foi testada no carro.** Os primeiros testes reais
> servem para confirmar módulos e dados marcados como "a confirmar".

## O que faz

| Comando | Para quê |
|---|---|
| `volvodiag portas` | Mostra as portas COM (para achar o OBDLink MX+) |
| `volvodiag info` | Adaptador, tensão da bateria, VIN, luz de injeção e dados que o carro oferece |
| `volvodiag dtc` | Lê e explica os códigos de erro: OBD-II do motor e dos módulos Volvo (motor, câmbio, CEM, freios, airbag) |
| `volvodiag ao-vivo` | Painel em tempo real (rotação, temperaturas, turbo, misturas, tensão...) e gravação no histórico |
| `volvodiag saude` | Avaliação rápida: bateria, carga, arrefecimento, óleo, mistura e luz de injeção |
| `volvodiag modulos` | Verifica quais módulos do carro respondem |
| `volvodiag ler-did` / `varrer-dids` | Lê e descobre dados específicos da Volvo (somente leitura) |
| `volvodiag relatorio` | Gera um relatório HTML de uma sessão gravada, com gráficos |
| `volvodiag manutencao` | Registra e lista revisões e trocas |
| `volvodiag apagar-dtc` | Apaga códigos de erro, com confirmação digitada |

Todos os comandos aceitam `--simulador` para testar sem o carro (dados fictícios).

## Segurança

* Uma **trava** (`src/volvodiag/safety.py`) só deixa sair pedidos de **leitura**.
  Gravação, reprogramação, desbloqueio de segurança, rotinas e reinicialização de
  módulos são sempre bloqueados, e há teste automatizado garantindo isso.
* Apagar códigos exige digitar `APAGAR`; os códigos são salvos no histórico antes.
* Alterar configurações dos módulos **não está implementado**. Se for feito no
  futuro, exigirá hardware J2534 e cópia de segurança dos módulos. Alteração de
  hodômetro e anulação de sistemas de segurança ou emissões não serão implementadas.
* Os limites da avaliação de saúde são referências gerais de mecânica, **não**
  especificações da Volvo. Não substitui uma oficina.

## Instalação (Windows)

Passo a passo completo em [docs/uso-windows.md](docs/uso-windows.md). Resumo:

```powershell
git clone https://github.com/samucaguima/volvo-xc60-diag
cd volvo-xc60-diag
py -m pip install .
volvodiag --simulador info      # teste sem o carro
volvodiag portas                # depois de parear o OBDLink MX+
volvodiag --porta COM5 info     # use a porta que aparecer
```

## Como funciona

Detalhes técnicos e fontes em [docs/protocolo-p3.md](docs/protocolo-p3.md).

* Rede CAN de alta velocidade (pinos 6 e 14 do conector OBD), ISO 15765-4, 11 bits, 500 kbps.
* Dados padrão: OBD-II (SAE J1979), com até 6 dados por pedido.
* Módulos Volvo: UDS (ISO 14229), serviços 19 (códigos de erro) e 22 (dados).
* Histórico local em SQLite (`~/.volvodiag/historico.sqlite`).

## Desenvolvimento

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## Créditos

* Descrições genéricas de códigos de erro: [Wal33D/dtc-database](https://github.com/Wal33D/dtc-database) (MIT).
* Endereços e dados de referência para P3: [Sebastian-Gebus/volvo-p3-dashboard](https://github.com/Sebastian-Gebus/volvo-p3-dashboard)
  (MIT) e [oleksandrdiadyk-glitch/volvoscan](https://github.com/oleksandrdiadyk-glitch/volvoscan) (sem licença declarada; usado apenas como indicação, sem copiar código).

Projeto independente, sem vínculo com a Volvo Cars. Use por sua conta e risco.
