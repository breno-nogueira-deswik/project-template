# [Nome do Projeto]

> Template padrão dos projetos de dados da Deswik (PMO). Substitua este título e
> esta descrição pelo objetivo do projeto: o que ele gera, para quem e com que
> frequência.

Pipeline em Python que lê dados do **PSA** (exports em pasta de rede) e da
**Float API**, transforma e grava o resultado em `data/output/`. Feito para rodar
sem janela pelo **Agendador de Tarefas** do Windows em uma VM.

---

## Índice

- [Novo projeto a partir do template](#novo-projeto-a-partir-do-template)
- [Estrutura de pastas](#estrutura-de-pastas)
- [Ambiente virtual (venv)](#ambiente-virtual-venv)
  - [Local (sua máquina)](#local-sua-máquina)
  - [VM (produção)](#vm-produção)
- [Configuração do `.env`](#configuração-do-env)
- [Configuração do `config.py`](#configuração-do-configpy)
- [Fluxo do pipeline](#fluxo-do-pipeline)
- [Execução](#execução)
- [Logs](#logs)
- [Notebooks](#notebooks)
- [Problemas comuns](#problemas-comuns)

---

## Novo projeto a partir do template

1. Copie a pasta do template e renomeie com o nome do projeto
   (ex.: `purchase_orders_report`). Esse nome também é o nome padrão da tarefa no
   Agendador.
2. `pyproject.toml` → troque `name = "nome-do-projeto"`.
3. `config.py`:
   - `FLOAT_USER_AGENT` → nome do projeto;
   - `PSA_THEMES` → só os temas do PSA que o projeto usa;
   - `FLOAT_ENDPOINTS` → endpoints do Float que o projeto usa (vazio = não busca);
   - seção **Constantes de negócio** → filtros, status, taxas do projeto.
4. Crie o venv ([local](#local-sua-máquina)) e o `.env` ([ver abaixo](#configuração-do-env)).
5. Implemente as etapas em `src/transform/` e `src/output/` e chame-as em
   `run_pipeline()` no `main.py` (os pontos estão marcados com `TODO`).
6. Atualize este README.

---

## Estrutura de pastas

```
<projeto>/
├── main.py               # Orquestrador: ingestão -> transformação -> saída
├── config.py             # Caminhos, constantes, temas do PSA, endpoints do Float
├── register_task.ps1     # Registra a tarefa no Agendador do Windows (VM)
├── requirements.txt      # Dependências Python
├── pyproject.toml        # Torna config + src instaláveis (pip install -e .)
├── .env.example          # Modelo do .env (versionado)
├── .env                  # Tokens e caminhos locais (NÃO versionado)
│
├── src/
│   ├── ingestion/
│   │   ├── psa_loader.py     # Consolida e carrega os exports do PSA
│   │   └── float_loader.py   # Busca os dados da Float API
│   ├── transform/            # Regras de negócio do projeto
│   └── output/               # Exportação dos resultados
│
├── data/
│   ├── raw/              # Consolidados do PSA (<Tema>_<AAAA-MM-DD>.csv)
│   ├── processed/        # Dados intermediários
│   └── output/           # Resultado final
│
├── logs/                 # pipeline_<data_hora>.log (um por execução)
└── notebooks/            # Exploração e testes (Jupyter)
```

O conteúdo de `data/*` e `logs/` não é versionado (pode conter dados internos);
os arquivos `.gitkeep` mantêm só a estrutura das pastas no git.

---

## Ambiente virtual (venv)

O venv fica na raiz do projeto, em `.venv/`, e **não é copiado entre máquinas**
(nem versionado): cada máquina cria o seu. Os comandos abaixo usam o Python do
venv diretamente (`.\.venv\Scripts\python.exe`), então não é preciso ativá-lo
(evita o bloqueio de `Activate.ps1` pela política de execução do PowerShell).

O `requirements.txt` instala, além das bibliotecas, o próprio projeto em modo
editável (`-e .`): é isso que faz `from config import ...` e
`from src.ingestion... import ...` funcionarem de qualquer pasta (main.py,
notebooks, testes) sem mexer em `sys.path`.

Requer **Python 3.13**.

### Local (sua máquina)

No PowerShell, na raiz do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

No VS Code: `Ctrl+Shift+P` → **Python: Select Interpreter** → escolha
`.venv\Scripts\python.exe`. Os avisos do Pylance de import não resolvido
(`dotenv`, `requests`...) somem depois disso.

### VM (produção)

Na VM o projeto fica em uma **pasta local** (ex.: `C:\Scripts PMO\<projeto>`),
nunca no caminho de rede: o Agendador pode não ter acesso à rede no horário da
tarefa.

O venv **precisa** ser criado a partir do Python instalado para todos os
usuários (`C:\Program Files\Python313`), e não de um Python instalado no perfil
de um usuário (`AppData`). A tarefa roda mesmo sem ninguém logado; um venv
baseado no Python de um perfil de usuário pode não encontrar o Python base nessa
situação. Por isso o caminho do Python é passado explicitamente, em vez de
`python`, que pode apontar para outra instalação:

```powershell
& 'C:\Program Files\Python313\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Get-Content .venv\pyvenv.cfg   # home = C:\Program Files\Python313
```

O último comando confere de qual Python o venv foi criado: a linha `home` precisa
ser `C:\Program Files\Python313`. Se for outra, apague a pasta `.venv` e crie de
novo.

Depois crie o `.env` na VM ([ver abaixo](#configuração-do-env)) e registre a
tarefa ([Execução agendada](#agendada-agendador-de-tarefas)).

---

## Configuração do `.env`

Copie o `.env.example` para `.env` na raiz do projeto e preencha:

```
FLOAT_BEARER_TOKEN=sua_chave_aqui
```

A chave do Float fica em: Float → Configurações de conta → API.

Opcionais (descomente só se precisar trocar o padrão do `config.py`):

| Variável | Padrão | Quando usar |
|---|---|---|
| `PSA_RAW_DIR` | `<projeto>/data/raw` | Guardar os consolidados em outra pasta |
| `PSA_SOURCE_DIR` | `\\bhz-fp1\...\1_PSA_data\raw` | Sem acesso ao servidor (cópia local dos exports) |
| `PSA_EXTERNAL_DIR` | `\\bhz-fp1\...\1_PSA_data\external` | Bases manuais em outra pasta |

O `.env` não é versionado: cada máquina (sua, a VM) tem o seu.

---

## Configuração do `config.py`

### `PSA_THEMES`

Cada tema é um tipo de export do PSA. A chave do tema é a chave do DataFrame
retornado por `load_psa_data()`.

```python
PSA_THEMES = {
    "Projects": {
        "prefix": "Projects",                        # INÍCIO do nome dos arquivos na origem
        "output": "Projects",                        # nome do consolidado: Projects_<AAAA-MM-DD>.csv
        "expected_columns": ["<Coluna 1>", "..."],   # opcional: valida o layout do export
    },
}
```

### `FLOAT_ENDPOINTS`

Cada entrada é um endpoint da Float API; campos aninhados podem ser explodidos em
tabelas separadas e enriquecidos com join de outro endpoint. A chave é a chave do
DataFrame retornado por `load_float_data()`. O formato completo está comentado no
próprio `config.py`.

Por padrão o template traz:

| Chave | Origem |
|---|---|
| `projects` | `GET /v3/projects` |
| `tasks` | `project_tasks` explodido de `projects` |
| `team` | `project_team` explodido de `projects` + dados da pessoa (`people`) |
| `allocations` | `GET /v3/tasks` |
| `people` | `GET /v3/people` |

### Outras constantes

| Constante | Uso |
|---|---|
| `LOG_RETENTION_DAYS` | Logs mais antigos que isso são apagados a cada execução (padrão 30) |

---

## Fluxo do pipeline

`main.py` → `run_pipeline()`:

1. **Ingestão** (cada fonte só roda se estiver configurada no `config.py`)
   - PSA: `consolidate_psa_exports()` junta os exports da pasta de origem
     (que podem vir divididos em vários arquivos por tema) em um arquivo por tema
     em `data/raw/`; `load_psa_data()` lê o consolidado mais recente de cada tema.
     → `psa_data["<Tema>"]`
   - Float: `load_float_data()` busca todos os endpoints em paralelo.
     → `float_data["projects"]`, `float_data["team"]`...
2. **Transformação**: `src/transform/` (específico do projeto).
3. **Saída**: `src/output/` grava em `data/output/` (específico do projeto).

---

## Execução

### Manual

```powershell
.\.venv\Scripts\python.exe main.py
```

O log aparece no terminal e também é gravado em `logs/`.

### Agendada (Agendador de Tarefas)

A tarefa roda o `main.py` com **`pythonw.exe`** (Python sem janela de console,
nenhuma tela preta aparece). Sem console, toda a saída vai para o log, e o
código de saída (0 = sucesso, 1 = falha) chega ao Agendador.

Na VM, a partir da pasta local do projeto:

```powershell
# Teste: roda só com o usuário logado, todo dia às 08:00
powershell -ExecutionPolicy Bypass -File register_task.ps1

# Produção: roda mesmo sem ninguém logado (pede a senha do usuário)
powershell -ExecutionPolicy Bypass -File register_task.ps1 -Mode Password -Times '07:00','13:00'

# Só em dias úteis
powershell -ExecutionPolicy Bypass -File register_task.ps1 -Mode Password -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday

# Remover a tarefa
powershell -ExecutionPolicy Bypass -File register_task.ps1 -Remove
```

Rodar de novo com o mesmo nome atualiza a tarefa. O nome padrão é o nome da pasta
do projeto (troque com `-TaskName`).

Testar e conferir:

```powershell
Start-ScheduledTask -TaskName '<projeto>'
Get-ScheduledTaskInfo -TaskName '<projeto>'   # LastTaskResult 0 = sucesso, 1 = falha (ver log)
```

---

## Logs

- Um arquivo por execução: `logs/pipeline_<AAAA-MM-DD_HHMMSS>.log`.
- Em caso de erro, o log tem a mensagem e o traceback completo.
- Logs com mais de `LOG_RETENTION_DAYS` dias são apagados automaticamente.

---

## Notebooks

Use a pasta `notebooks/` para exploração. Selecione o kernel do `.venv` no
Jupyter/VS Code; como o projeto está instalado em modo editável, os imports
funcionam direto:

```python
from src.ingestion.float_loader import load_float_data
float_data = load_float_data()
float_data["projects"].head()
```

Não use `float` como nome de variável (sobrescreve o `float()` do Python).
Nunca deixe tokens escritos no notebook: eles vêm do `.env` via `config.py`.

---

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| `FLOAT_BEARER_TOKEN não definido` | `.env` ausente ou sem o token na raiz do projeto |
| `Pasta de origem do PSA inacessível` | Sem acesso ao servidor (VPN/rede). Para rodar localmente, defina `PSA_SOURCE_DIR` no `.env` |
| `ModuleNotFoundError: config` / `src` | Venv sem o `-e .`: rode de novo `pip install -r requirements.txt` |
| `pythonw.exe nao encontrado` no `register_task.ps1` | Venv não criado na raiz do projeto (`.venv`) |
| Tarefa com `LastTaskResult` 1 | Erro no pipeline: veja o log mais recente em `logs/` |
| Tarefa não roda sem usuário logado | Registrada em modo `Interactive`; registre com `-Mode Password` |
