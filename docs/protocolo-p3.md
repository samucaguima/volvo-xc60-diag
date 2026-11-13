# Notas técnicas: XC60 P3 (2014) pelo ELM327 / OBDLink

## Veículo

* Volvo XC60 primeira geração (2009-2017), plataforma **P3** (também chamada EUCD).
* Motor Drive-E 2.0 turbo a gasolina (245 cv), câmbio automático Aisin de 8 marchas.

## Rede e adaptador

| Item | Valor | Comando ELM |
|---|---|---|
| Protocolo | ISO 15765-4, CAN 11 bits, 500 kbps | `ATSP6` |
| Pinos OBD | 6 (CAN-H) e 14 (CAN-L) | |
| Cabeçalhos | ligados (para identificar quem respondeu) | `ATH1` |
| Espaços | desligados (menos tráfego no Bluetooth) | `ATS0` |
| Endereço funcional OBD | 0x7DF | `ATSH7DF` + `ATAR` |
| Endereço de um módulo | envio 0x7xx, resposta 0x7xx + 8 | `ATSHxxx` + `ATCRAyyy` |
| Controle de fluxo | explícito para mensagens longas | `ATFCSH`, `ATFCSD300000`, `ATFCSM1` |

### Rede de média velocidade (MS-CAN), experimental

Pinos 3 e 11, 125 kbps. Uma medição da Snap-on num XC60 2017 encontrou essa rede
nesses pinos, e fóruns Volvo dizem o mesmo; não há documento oficial da Volvo
consultado. Acesso com a opção `--rede ms`, em adaptadores ELM327 com **chave
HS/MS-CAN** (a chave liga o adaptador aos pinos 3/11):

| Item | Valor | Comando ELM |
|---|---|---|
| Protocolo | B (USER1), CAN 11 bits, quadros de 8 bytes, ISO 15765-4 | `ATPB8104` + `ATSPB` |
| Velocidade | 500 ÷ 4 = 125 kbps | (divisor 04 no `ATPB`) |

`AT PB` vale só para a sessão e não altera a memória do adaptador (datasheet do
ELM327, parâmetros programáveis 2C e 2D). Adaptadores OBDLink usam comandos
próprios (STN) para essa rede, ainda não implementados; por isso `--rede ms` é
recusado quando o adaptador responde ao `STI`.

**Escuta antes de transmitir.** Transmitir a 125 kbps na rede principal
(500 kbps), o que aconteceria com a chave do adaptador em HS, gera erros no
barramento do motor e do câmbio. Por isso, antes de qualquer pedido, o sistema
usa `AT CSM1` + `AT MA`: no modo de monitoramento o ELM327 não transmite nem
confirma mensagens (datasheet, comandos CSM e MA; o próprio fabricante recomenda
manter a escuta silenciosa até ter certeza da velocidade). Só segue se ouvir
mensagens válidas; erros de recepção ou silêncio interrompem sem transmitir.

O comando `varrer-modulos` procura, nas duas redes, quais endereços respondem à
presença do testador (`3E 00`, que não altera nada), para confirmar o mapa abaixo.

## Módulos

| Módulo | Envio | Resposta | Fonte | Confiança |
|---|---|---|---|---|
| ECM (motor) | 7E0 | 7E8 | volvo-p3-dashboard (P3 real) | verificado em P3 diesel |
| CEM (central) | 726 | 72E | volvo-p3-dashboard (P3 real) | verificado em P3 diesel |
| TCM (câmbio) | 7E1 | 7E9 | volvoscan | a confirmar |
| BCM (freios) | 760 | 768 | volvoscan | a confirmar |
| SRS (airbags) | 772 | 77A | volvoscan | a confirmar |
| DIM (painel) | 720 | 728 | volvoscan | a confirmar, provável MS-CAN (`--rede ms`) |
| CCM (clima) | 733 | 73B | volvoscan | a confirmar, provável MS-CAN (`--rede ms`) |

O projeto volvoscan tem modo de demonstração e não comprova os endereços no
carro. Por isso a versão 0.1 trata esses módulos como hipóteses e o comando
`modulos` existe para confirmá-los.

## Dados Volvo (UDS 22)

| Módulo | DID | Dado | Fórmula | Situação |
|---|---|---|---|---|
| CEM | F190 | VIN | ASCII | padrão ISO 14229 |
| CEM | 4028 | Estado de carga da bateria | A (%) | verificado em P3 diesel |
| ECM | D9DC | Temperatura do óleo | (256A+B)/10 − 273,15 °C | verificado em P3 **diesel**; confirmar no Drive-E |
| ECM | D941 | Pressão no coletor (absoluta) | (256A+B)/10 kPa | verificado em P3 **diesel**; confirmar no Drive-E |

O Drive-E a gasolina usa outra central de motor. Antes de confiar num dado do
motor, rode `varrer-dids` e compare os valores com o painel do carro.

## Códigos de erro

* OBD-II: serviços 03 (armazenados), 07 (pendentes) e 0A (permanentes), formato SAE de 2 bytes.
* UDS: serviço 19 02 com máscara FF; cada registro tem 3 bytes de código + 1 de estado.
  O sistema mostra o código no estilo `MÓDULO-XXXX` (2 primeiros bytes), o tipo de
  falha (3º byte) e, para motor e câmbio, o equivalente SAE.
  Essa leitura do formato Volvo é uma interpretação a confirmar com uma ferramenta oficial.

## Serviços permitidos

Somente leitura: OBD 01, 02, 03, 06, 07, 09, 0A; UDS 19, 22 e 3E.
Apagar códigos (OBD 04, UDS 14) só com confirmação. Todo o resto é bloqueado
pela trava em `src/volvodiag/safety.py`.
