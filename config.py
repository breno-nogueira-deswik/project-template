"""
config.py — Centraliza caminhos, constantes e variáveis de ambiente.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Caminhos ────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent

# Lê o .env da raiz do projeto, independente da pasta de onde o código é rodado
# (main.py, notebooks/, Agendador de Tarefas).
load_dotenv(ROOT_DIR / ".env")

SRC_DIR = ROOT_DIR / "src"
NOTEBOOKS_DIR = ROOT_DIR / "notebooks"
DATA_DIR = ROOT_DIR / "data"
DATA_RAW_DIR = DATA_DIR / "raw"
DATA_PROCESSED_DIR = DATA_DIR / "processed"
DATA_OUTPUT_DIR = DATA_DIR / "output"
LOGS_DIR = ROOT_DIR / "logs"

# Logs de execução mais antigos que isso são apagados a cada execução do main.py
# (rodando todo dia pelo Agendador, a pasta logs/ cresceria sem limite).
LOG_RETENTION_DAYS = 30

# Pasta onde ficam os exports do PSA já consolidados (um arquivo por tema e data),
# lida pelo psa_loader. Padrão: data/raw do projeto; sobrescrevível via .env.
# Criada, se não existir, por consolidate_psa_exports.
PSA_RAW_DIR = Path(os.getenv("PSA_RAW_DIR") or DATA_RAW_DIR)

# Pasta no servidor onde os exports brutos do PSA são baixados (podem vir divididos
# em vários arquivos por tema). Sobrescrevível via .env (ex.: cópia local).
PSA_SOURCE_DIR = Path(
    os.getenv("PSA_SOURCE_DIR")
    or r"\\bhz-fp1\Departamentos\PMO\4_Banco_de_dados\1_PSA_data\raw"
)

# Pasta no servidor com bases mantidas manualmente (ex.: base de vigência).
# Sobrescrevível via .env.
PSA_EXTERNAL_DIR = Path(
    os.getenv("PSA_EXTERNAL_DIR")
    or r"\\bhz-fp1\Departamentos\PMO\4_Banco_de_dados\1_PSA_data\external"
)

# ── Temas do PSA (consolidação) ────────────────────────────────────────────
# Tema -> prefixo do nome dos arquivos em PSA_SOURCE_DIR e nome base do arquivo
# consolidado salvo em PSA_RAW_DIR como "<output>_<AAAA-MM-DD>.<ext>".
# O tema é identificado pelo INÍCIO do nome do arquivo (não por "contém").
# Manter só os temas usados por este pipeline; os demais arquivos da pasta são ignorados.
# A chave do tema também é a chave do DataFrame retornado por load_psa_data.
# "expected_columns" (opcional): colunas que o export precisa ter; load_psa_data
# falha se alguma estiver ausente.
PSA_THEMES = {
    # "Projects": {
    #     "prefix": "Projects",
    #     "output": "Projects",
    #     "expected_columns": ["<Coluna 1>", "<Coluna 2>"],
    # },
}

# ── Float ───────────────────────────────────────────────────────────────────
# API para conectar aos dados brutos do Float Deswik
FLOAT_BASE_URL = "https://api.float.com/v3"
FLOAT_BEARER_TOKEN = os.getenv("FLOAT_BEARER_TOKEN", "")
FLOAT_USER_AGENT = "<Nome do Projeto> (breno.nogueira@deswik.com)"

# ── Endpoints do Float ──────────────────────────────────────────────────────
# Chave -> configuração de um endpoint da API; a chave é a chave do DataFrame
# retornado por load_float_data (ex.: float_data["projects"]).
#   "endpoint": caminho na API (ex.: "tasks" -> GET /v3/tasks).
#   "params":   parâmetros da requisição (ex.: "fields", "active").
#   "explode":  (opcional) campos aninhados que viram tabelas separadas. Cada um
#               é pedido via "expand" e vira float_data[<chave>]:
#       "field":        campo aninhado no registro (ex.: "project_tasks").
#       "prefix":       prefixo das colunas do item (evita colisão com o pai).
#       "base_columns": colunas do registro pai repetidas em cada linha.
#       "join":         (opcional) enriquece a tabela com outro endpoint:
#           "with":      chave do outro endpoint (ex.: "people").
#           "left_on":   coluna da tabela explodida (já com prefixo).
#           "right_on":  coluna do outro endpoint (sem prefixo).
#           "columns":   colunas do outro endpoint a trazer.
#           "prefix":    prefixo dessas colunas.
# Todas as chaves (endpoints e explodidas) precisam ser únicas.
FLOAT_ENDPOINTS = {
    "projects": {
        "endpoint": "projects",
        "params": {
            # "fields": "project_id,name,client_id,active",  # opcional: payload menor
            # "active": 1,                                    # opcional: só projetos ativos
        },
        "explode": {
            "tasks": {
                "field": "project_tasks",
                "prefix": "task_",
                "base_columns": ["project_id", "name", "client_id", "active"],
            },
            "team": {
                "field": "project_team",
                "prefix": "team_",
                "base_columns": ["project_id", "name", "client_id", "active"],
                "join": {
                    "with": "people",
                    "left_on": "team_people_id",
                    "right_on": "people_id",
                    "columns": ["people_id", "name", "email", "job_title", "active"],
                    "prefix": "person_",
                },
            },
        },
    },
    "allocations": {
        "endpoint": "tasks",
        "params": {
            # "fields": "task_id,project_id,people_id,start_date,end_date,hours",
        },
    },
    "people": {
        "endpoint": "people",
        "params": {
            # "fields": "people_id,name,email,job_title,active",
        },
    },
}

# ── Constantes de negócio ───────────────────────────────────────────────────
# Filtros, status, taxas e demais constantes específicas do projeto.
