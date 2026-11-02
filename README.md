# MISS UESP

Sistema local de avaliação e controle da UESP 2027.

## Compatibilidade

O projeto utiliza a biblioteca padrão do Python (incluindo `http.server` e `sqlite3`) e a dependência externa `openpyxl`, necessária para importar planilhas Excel. Mantenha a mesma versão do Python e as mesmas dependências nos dois notebooks para obter o mesmo comportamento.

Configuração prevista para Windows 10 e Windows 11 com Python 3.15.x (64 bits).

## Preparação em cada notebook

1. Instale Python 3.15.2 (64 bits) pelo instalador oficial. Marque a opção de adicionar o Python ao PATH, se disponível.
2. Baixe/clोनe este repositório e extraia todos os arquivos para uma pasta local, por exemplo `C:\MISS-UESP`.
3. Abra essa pasta no Explorador de Arquivos e execute `instalar_ambiente.bat`.
4. Depois da instalação, execute `iniciar_servidor.bat`.
5. No próprio notebook, acesse `http://127.0.0.1:8765/central.html`.

Também é possível configurar manualmente no PowerShell, dentro da pasta do projeto:

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe servidor.py
```

O ambiente virtual `.venv` é local de cada notebook; não copie a pasta `.venv` de um computador para o outro.

## Transferência dos dados entre notebooks

Os bancos de dados são criados automaticamente na pasta do projeto:

- `banco_audicao.db`
- `banco_concurso.db`
- `banco_agulha_ouro.db` (avaliadores, notas, apuração e liberação próprias do Agulha de Ouro)

Para levar os dados atuais ao segundo notebook:

1. Encerre o servidor no primeiro notebook com `Ctrl+C`.
2. Copie todos os arquivos `.db` listados acima para a pasta do projeto no segundo notebook, substituindo os bancos vazios que possam ter sido criados.
3. Copie também eventuais arquivos de dados/fotos que estejam na pasta do projeto.
4. Inicie o servidor no segundo notebook.

**Importante:** não mantenha duas cópias independentes do sistema recebendo avaliações ao mesmo tempo. Os bancos SQLite são arquivos locais e não sincronizam automaticamente entre notebooks. Escolha um notebook como servidor principal durante o evento; os demais dispositivos acessam o endereço de rede exibido no terminal. Faça cópias de segurança dos dois bancos antes de transferências ou atualizações.

## Acesso pela rede

O servidor escuta na porta TCP 8765 em todas as interfaces. Para acessar de outros dispositivos na mesma rede Wi-Fi, use o endereço de rede mostrado no terminal, por exemplo `http://192.168.x.x:8765/central.html`. Se o Windows solicitar, permita o acesso do Python em redes privadas no Firewall.

## Atualização e segurança dos dados

- Antes de atualizar os arquivos do projeto, encerre o servidor e faça backup dos três bancos `.db`.
- Não apague os bancos para atualizar o código.
- Os bancos de dados e os backups são arquivos locais e estão excluídos do Git. Nunca publique arquivos `.db` com dados reais no repositório.
- Reimportações, limpezas totais e restaurações criam conjuntos consistentes dos três bancos em `backup de banco/`, com um identificador comum de data/hora e um manifesto que agrupa os arquivos. A Central permite listar e restaurar conjuntos completos; antes de restaurar, também cria um backup do estado atual. São mantidos os 30 conjuntos mais recentes. Os arquivos individuais sem manifesto de versões anteriores continuam disponíveis para recuperação manual.
- Não compartilhe a pasta de bancos por sincronização simultânea (OneDrive/Dropbox/Google Drive) enquanto o servidor estiver gravando.
- O servidor serve somente as páginas e os recursos da aplicação; os bancos SQLite, backups e arquivos Python não são baixáveis pelas rotas HTTP.
- Requisições de gravação precisam vir da mesma origem da aplicação. Isso reduz requisições forjadas por páginas abertas em outros sites.
- O servidor continua disponível para dispositivos na mesma rede local. Para usar uma senha fixa, escreva-a em uma única linha no arquivo local `UESP_ACCESS_PIN.txt), na pasta do projeto. Esse arquivo é ignorado pelo Git. Se ele não existir ou estiver vazio, o terminal mostra um código temporário. Também é possível definir `UESP_ACCESS_PIN` antes de iniciar o servidor; a variável de ambiente tem prioridade sobre o arquivo.
- Cada dispositivo informa o código uma vez; as sessões expiram em oito horas ou quando o servidor é encerrado.
- Use somente uma rede Wi-Fi confiável, permita o Python apenas em redes privadas no Firewall e nunca exponha a porta 8765 diretamente à internet. O acesso usa HTTP sem criptografia TLS; o código e os dados podem ser observados por alguém capaz de monitorar a rede local.
- O Avaliador guarda rascunhos não enviados no armazenamento local do navegador, separados por avaliador, etapa e participante. A lista de candidatas e as notas salvas continuam dependendo do servidor; se a conexão cair depois que a lista carregar, reconecte e pressione Salvar para enviar cada rascunho. Rascunhos não sincronizam entre dispositivos e não substituem os bancos do servidor; não limpe os dados do navegador até confirmar o envio.

## Dependências Python

As dependências externas ficam registradas em `requirements.txt`. Para reinstalá-las:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```


## Agulha de Ouro

A avaliação do Agulha de Ouro fica no modo próprio da tela `avaliador.html?stage=agulha`, seguindo o fluxo do Concurso, mas usando avaliadores e notas armazenados em `banco_agulha_ouro.db`. O gerenciamento, a apuração e a liberação ao apresentador ficam em `agulha.html`. Participam as candidatas elegíveis de Rainha do Samba e Diva do Samba (Plus Size), com nota exclusiva para vestido/roupa de 9,0 a 10,0 em intervalos de 0,1. A classificação soma as notas de todas as participantes elegíveis numa lista única, incluindo pontuações parciais durante a apuração; há uma única vencedora geral, independente da categoria. Se houver empate geral em primeiro lugar, o painel sinaliza as empatadas e a liberação fica bloqueada até que um avaliador reavalie e edite uma nota existente, repetindo a revisão se necessário. A liberação exige que todas as avaliações estejam completas. O resultado é independente do Concurso e pode ser liberado separadamente no Painel do Apresentador. O HTML de controle também permite limpar as notas e os avaliadores cadastrados sem apagar participantes.
