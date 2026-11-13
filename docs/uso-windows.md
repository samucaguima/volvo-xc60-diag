# Uso no Windows com adaptador ELM327 (USB ou Bluetooth)

## 1. Instalar o Python e o Git

1. Instale o **Python 3.12 ou mais novo** em <https://www.python.org/downloads/>.
   Na instalação, marque **"Add python.exe to PATH"**.
2. Instale o **Git for Windows** em <https://git-scm.com/download/win>.

## 2. Baixar e instalar o volvodiag

No PowerShell:

```powershell
cd $HOME\Documents
git clone https://github.com/samucaguima/volvo-xc60-diag
cd volvo-xc60-diag
py -m pip install .
volvodiag --simulador info
```

Se o repositório for privado, o Git abre uma janela para você entrar no GitHub.
Se o comando `volvodiag` não for encontrado, use `py -m volvodiag` no lugar dele.

## 3. Conectar o adaptador

**Adaptador USB (recomendado):**

1. Ligue o adaptador no USB do notebook. O Windows 10/11 costuma instalar o
   driver sozinho. Se não instalar, baixe o driver do chip indicado no anúncio:
   **CH340** (fabricante WCH) ou **FTDI** (site da FTDI).
2. Rode `volvodiag portas`. O adaptador aparece como "USB-SERIAL CH340" ou
   "USB Serial Port" com uma porta COM (ex.: COM3).

**Adaptador Bluetooth clássico (ou OBDLink MX+):**

1. Encaixe o adaptador no carro e ligue a ignição.
2. No Windows: Configurações > Bluetooth e dispositivos > Adicionar dispositivo > Bluetooth.
   Escolha o adaptador (a senha costuma ser 1234 ou 0000; no MX+, aperte o botão).
3. Rode `volvodiag portas`. Ele aparece como **"Serial padrão por link Bluetooth"**.
   Se houver duas portas, use a de **saída**. Em caso de dúvida, teste as duas.

O conector OBD do XC60 fica abaixo do painel, do lado do motorista.

## Ao receber o adaptador: teste antes de tudo

Ainda no prazo de devolução, encaixe o adaptador no carro com a **ignição
desligada** (adaptadores USB recebem energia da tomada OBD, não do USB) e rode:

```powershell
volvodiag --porta COM3 testar-adaptador
```

* **APROVADO:** o adaptador aceita todos os comandos que o sistema usa.
* **REPROVADO:** ele recusou comandos essenciais. É provavelmente um clone
  incompleto; peça troca ou devolução e mostre o resultado ao vendedor.
* "Sem resposta do adaptador": confira se ele está bem encaixado no carro e se a
  porta COM é a certa.

O teste não envia nada que altere o carro. Com a ignição ligada, ele também
confirma a comunicação com o motor.

Para ver como é uma reprovação sem ter o adaptador:
`volvodiag --simulador testar-adaptador --simular-clone-ruim`.

## 4. Primeiros testes no carro (nesta ordem)

Ignição ligada, motor desligado:

```powershell
volvodiag --porta COM5 info
volvodiag --porta COM5 modulos
volvodiag --porta COM5 dtc
```

Depois com o motor ligado e o carro parado:

```powershell
volvodiag --porta COM5 saude
volvodiag --porta COM5 painel --volvo
```

O `painel` abre o navegador com os dados ao vivo, gráficos e alertas (endereço
`http://127.0.0.1:8765`, só no próprio notebook, sem precisar de internet).
`ao-vivo --volvo` mostra o mesmo no terminal. Ctrl+C encerra os dois. Para gerar o relatório da última sessão:

```powershell
volvodiag relatorio
```

O arquivo `relatorio-sessao-N.html` abre em qualquer navegador.

## 5. Rede de média velocidade: painel e climatizador (experimental)

Só para adaptadores com **chave HS/MS-CAN**. Com a ignição ligada, mude a chave
para **MS** e rode:

```powershell
volvodiag --porta COM3 --rede ms varrer-modulos
volvodiag --porta COM3 --rede ms modulos
volvodiag --porta COM3 --rede ms dtc
```

Antes de transmitir qualquer coisa com `--rede ms`, o sistema **escuta o
barramento em silêncio** por cerca de 1,5 segundo. Só continua se ouvir
mensagens válidas a 125 kbps; se a chave estiver em HS (rede principal, a
500 kbps), ele para sem enviar nada ao carro e avisa. Isso evita transmitir na
velocidade errada na rede do motor e do câmbio.

Volte a chave para **HS** antes de usar os demais comandos. A rede MS é
recusada em adaptadores OBDLink nesta versão (neles, o protocolo usado não muda
de pinos).

Para mapear todos os módulos da rede principal também:

```powershell
volvodiag --porta COM3 varrer-modulos
```

Envie as duas listas de endereços para completarmos o mapa de módulos.

## 6. Descobrir dados do seu motor (opcional)

Os dados Volvo de temperatura do óleo e de pressão vieram de um P3 a diesel. Para
ver o que o Drive-E responde (somente leitura, com a ignição ligada):

```powershell
volvodiag --porta COM5 varrer-dids --modulo ECM
volvodiag --porta COM5 varrer-dids --modulo CEM
```

Os resultados ficam no histórico local. Envie a saída para continuarmos o
mapeamento: cada identificador precisa ser confirmado comparando o valor com o
painel do carro antes de ser usado.

## 7. Acompanhar o carro ao longo do tempo

**Tendências.** Cada `painel` ou `ao-vivo` gravado vira uma sessão. Para a
comparação de bateria ser útil, comece a sessão com a **ignição ligada e o
motor desligado** por uns 30 segundos e só então dê a partida. Depois de
algumas sessões:

```powershell
volvodiag tendencias
```

**Manutenção.** Cadastre os intervalos do manual do seu XC60 ou da sua
concessionária (o sistema não traz intervalos oficiais da Volvo). Exemplo:

```powershell
volvodiag manutencao intervalo --item "Troca de óleo e filtro" --km 10000 --meses 12
volvodiag manutencao adicionar --item "Troca de óleo e filtro" --km 98000 --data 2026-08-20
volvodiag manutencao proximas --km-atual 101500
```

Use sempre o mesmo nome de item no intervalo e nos registros (maiúsculas e
minúsculas não importam).

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| `Não foi possível abrir COMx` | Feche outros programas que usam o adaptador (Torque, FORScan, app OBDLink) e confira a porta com `volvodiag portas` |
| `Sem resposta do adaptador` | Adaptador desencaixado do carro, adaptador Bluetooth dormindo ou porta errada |
| `não conseguiu se comunicar com o carro` | Ligue a ignição; confira o encaixe no conector |
| Módulo "sem resposta" em `modulos` | Pode estar na outra rede (`--rede ms` / chave do adaptador) ou o endereço precisa ser confirmado (`varrer-modulos`) |
| Ver a conversa com o adaptador | Acrescente `--debug` antes do comando |

Para enviar um log a alguém, use `--debug`, mas **apague o VIN** do texto antes de compartilhar.
