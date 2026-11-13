# volvo-xc60-diag

Sistema de diagnóstico **somente leitura** para o Volvo XC60 2014 (plataforma P3,
motor Drive-E 2.0 turbo, câmbio automático Aisin de 8 marchas), usando um
adaptador compatível com ELM327.

## Adaptador recomendado

O mais barato que atende ao sistema: **ELM327 USB com chip PIC18F25K80 e chave
HS-CAN/MS-CAN** (interface USB FTDI ou CH340).

* **Chip PIC18F25K80:** clones com chip ARM ("v2.1") costumam recusar comandos
  de que o sistema precisa. O número de versão impresso não é confiável.
* **USB:** vira porta COM no Windows, sem pareamento. Evite adaptadores
  "Bluetooth 4.0 / BLE": são feitos para iPhone e normalmente não aparecem como
  porta COM no Windows. Bluetooth clássico (2.0/3.0) e Wi-Fi também funcionam.
* **Chave HS/MS-CAN:** dá acesso à rede de média velocidade (pinos 3 e 11),
  onde devem ficar o painel e o climatizador (opção `--rede ms`, experimental).
* Adaptadores OBDLink (MX+, SX, EX) também funcionam, mas custam bem mais.

Ao receber, rode `volvodiag --porta COMx testar-adaptador` com o adaptador
encaixado no carro (ignição desligada) para confirmar, ainda no prazo de
devolução, que ele aceita todos os comandos usados.

> **Estado:** versão 0.1, testada em simulador e num emulador ELM327
> independente. **Ainda não foi testada no carro.** Os primeiros testes reais
> servem para confirmar módulos e dados marcados como "a confirmar".

## O que faz

| Comando | Para quê |
|---|---|
| `volvodiag portas` | Mostra as portas COM (para achar o adaptador) |
| `volvodiag testar-adaptador` | Confere se o adaptador aceita todos os comandos usados (aprova ou reprova) |
| `volvodiag info` | Adaptador, tensão da bateria, VIN, luz de injeção e dados que o carro oferece |
| `volvodiag dtc` | Lê e explica os códigos de erro: OBD-II do motor e dos módulos Volvo (motor, câmbio, CEM, freios, airbag) |
| `volvodiag painel` | Painel ao vivo no navegador, com gráficos e alertas, gravando no histórico (funciona sem internet) |
| `volvodiag ao-vivo` | O mesmo painel em modo texto, no terminal |
| `volvodiag saude` | Avaliação rápida: bateria, carga, arrefecimento, óleo, mistura e luz de injeção |
| `volvodiag modulos` | Verifica quais módulos do carro respondem |
| `volvodiag varrer-modulos` | Procura módulos em todos os endereços (não altera nada) |
| `--rede ms` | Rede de média velocidade (painel, climatizador), experimental, exige chave HS/MS-CAN |
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
volvodiag portas                # depois de conectar o adaptador
volvodiag --porta COM5 testar-adaptador   # use a porta que aparecer
volvodiag --porta COM5 info
```

## Como funciona

Detalhes técnicos e fontes em [docs/protocolo-p3.md](docs/protocolo-p3.md).

* Rede CAN de alta velocidade (pinos 6 e 14 do conector OBD), ISO 15765-4, 11 bits, 500 kbps.
* Rede de média velocidade (pinos 3 e 11), 125 kbps, com `--rede ms` (experimental).
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
  Os 202 códigos mais comuns têm tradução livre para o português (`src/volvodiag/data/dtc_pt.csv`, não oficial);
  os demais aparecem em inglês.
* Endereços e dados de referência para P3: [Sebastian-Gebus/volvo-p3-dashboard](https://github.com/Sebastian-Gebus/volvo-p3-dashboard)
  (MIT) e [oleksandrdiadyk-glitch/volvoscan](https://github.com/oleksandrdiadyk-glitch/volvoscan) (sem licença declarada; usado apenas como indicação, sem copiar código).

Projeto independente, sem vínculo com a Volvo Cars. Use por sua conta e risco.
