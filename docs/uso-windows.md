# Uso no Windows com o OBDLink MX+

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

## 3. Parear o OBDLink MX+

1. Encaixe o MX+ no conector OBD do XC60 (abaixo do painel, do lado do motorista).
2. Ligue a ignição (não precisa ligar o motor).
3. No Windows: Configurações > Bluetooth e dispositivos > Adicionar dispositivo > Bluetooth.
4. Aperte o botão do MX+ quando o Windows procurar e escolha "OBDLink MX+".
5. Rode `volvodiag portas`. O MX+ aparece como **"Serial padrão por link Bluetooth"**.
   Se houver duas portas, use a de **saída**. Em caso de dúvida, teste as duas.

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
volvodiag --porta COM5 ao-vivo --volvo
```

Ctrl+C encerra o painel. Para gerar o relatório da última sessão:

```powershell
volvodiag relatorio
```

O arquivo `relatorio-sessao-N.html` abre em qualquer navegador.

## 5. Descobrir dados do seu motor (opcional)

Os dados Volvo de temperatura do óleo e de pressão vieram de um P3 a diesel. Para
ver o que o Drive-E responde (somente leitura, com a ignição ligada):

```powershell
volvodiag --porta COM5 varrer-dids --modulo ECM
volvodiag --porta COM5 varrer-dids --modulo CEM
```

Os resultados ficam no histórico local. Envie a saída para continuarmos o
mapeamento: cada identificador precisa ser confirmado comparando o valor com o
painel do carro antes de ser usado.

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| `Não foi possível abrir COMx` | Feche outros programas que usam o MX+ (app OBDLink, Torque) e confira a porta com `volvodiag portas` |
| `Sem resposta do adaptador` | Ignição desligada, MX+ dormindo (aperte o botão) ou porta errada |
| `não conseguiu se comunicar com o carro` | Ligue a ignição; confira o encaixe no conector |
| Módulo "sem resposta" em `modulos` | Pode estar na rede MS-CAN (ainda não suportada) ou o endereço precisa ser confirmado |
| Ver a conversa com o adaptador | Acrescente `--debug` antes do comando |

Para enviar um log a alguém, use `--debug`, mas **apague o VIN** do texto antes de compartilhar.
