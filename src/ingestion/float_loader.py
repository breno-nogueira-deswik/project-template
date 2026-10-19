"""
float_loader.py — Busca dados da Float API v3.

Os endpoints buscados, os campos aninhados explodidos em tabelas separadas e os
joins entre tabelas são definidos em config.FLOAT_ENDPOINTS; este módulo não tem
nenhum endpoint fixo no código.

Otimizações: sessão HTTP com pool de conexões, per-page=200, páginas baixadas
em paralelo, todos os endpoints rodando ao mesmo tempo, retry com backoff só
quando há 429/5xx, e explosão em Python puro.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import FLOAT_BASE_URL, FLOAT_BEARER_TOKEN, FLOAT_ENDPOINTS, FLOAT_USER_AGENT

logger = logging.getLogger(__name__)

PER_PAGE = 200   # máximo aceito pela Float API (o padrão, se omitido, é 50)
# Threads de paginação POR endpoint. O total de requisições simultâneas é
# MAX_WORKERS × nº de endpoints: se adicionar endpoints e começar a receber 429
# (rate limit), reduza este valor.
MAX_WORKERS = 4


# ── Requisições ─────────────────────────────────────────────────────────────

def _criar_sessao(pool: int) -> requests.Session:
    """Sessão com pool de conexões e retry (backoff) em 429/5xx."""
    if not FLOAT_BEARER_TOKEN:
        raise EnvironmentError(
            "FLOAT_BEARER_TOKEN não definido. "
            "Crie um arquivo .env com FLOAT_BEARER_TOKEN=<sua_chave>."
        )
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {FLOAT_BEARER_TOKEN}",
        "User-Agent": FLOAT_USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    })
    retry = Retry(
        total=5, backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool, pool_maxsize=pool)
    s.mount("https://", adapter)
    return s


def _get_all(
    session: requests.Session,
    endpoint: str,
    params: dict | None = None,
    per_page: int = PER_PAGE,
    workers: int = MAX_WORKERS,
) -> list[dict]:
    """Busca a 1ª página, descobre o total (X-Pagination-Page-Count) e baixa o
    restante em paralelo."""
    base_params = {**(params or {}), "per-page": per_page}
    url = f"{FLOAT_BASE_URL}/{endpoint}"

    def fetch(page: int) -> requests.Response:
        r = session.get(url, params={**base_params, "page": page}, timeout=60)
        r.raise_for_status()
        return r

    primeira = fetch(1)
    total_paginas = int(primeira.headers.get("X-Pagination-Page-Count", 1))
    registros = primeira.json()

    if total_paginas > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for r in ex.map(fetch, range(2, total_paginas + 1)):
                registros.extend(r.json())

    logger.info("[%s] %d página(s), %d registros", endpoint, total_paginas, len(registros))
    return registros


def _params_requisicao(cfg: dict) -> dict:
    """Parâmetros do endpoint + "expand" com os campos a explodir."""
    params = dict(cfg.get("params") or {})
    campos = [e["field"] for e in (cfg.get("explode") or {}).values()]
    if campos:
        params["expand"] = ",".join(campos)
    return params


# ── Explosão + join ─────────────────────────────────────────────────────────

def _explodir(
    registros: list[dict],
    campo: str,
    prefixo: str,
    base_columns: list[str],
    manter_vazios: bool = True,
) -> pd.DataFrame:
    """Uma linha por item do campo aninhado, com as `base_columns` do registro
    pai e as colunas do item prefixadas.

    Cada campo aninhado vira uma tabela separada (explodir dois juntos geraria
    produto cartesiano, ex.: tarefa × membro). Registros sem itens ficam com uma
    linha vazia; use manter_vazios=False para descartá-los."""
    linhas = []
    append = linhas.append
    for p in registros:
        base = {c: p.get(c) for c in base_columns}
        itens = p.get(campo) or []
        if itens:
            for item in itens:
                append({**base, **{prefixo + k: v for k, v in item.items()}})
        elif manter_vazios:
            append(base)
    return pd.DataFrame(linhas)


def _juntar(df: pd.DataFrame, outro: pd.DataFrame, join: dict, nome: str) -> pd.DataFrame:
    """Enriquece `df` com colunas de `outro` (prefixadas), via left join."""
    left_on, right_on, prefixo = join["left_on"], join["right_on"], join["prefix"]
    if left_on not in df.columns or right_on not in outro.columns:
        logger.warning(
            "[%s] join com '%s' ignorado: coluna '%s' ou '%s' ausente",
            nome, join["with"], left_on, right_on,
        )
        return df
    cols = [c for c in join["columns"] if c in outro.columns]
    if right_on not in cols:
        cols.append(right_on)
    direita = outro[cols].add_prefix(prefixo)
    return df.merge(
        direita, left_on=left_on, right_on=prefixo + right_on, how="left"
    ).drop(columns=prefixo + right_on)


def _validar(endpoints: dict) -> None:
    """Chaves únicas (endpoints + explodidas) e joins apontando para endpoints."""
    chaves = list(endpoints)
    for cfg in endpoints.values():
        chaves += list(cfg.get("explode") or {})
    repetidas = sorted({c for c in chaves if chaves.count(c) > 1})
    if repetidas:
        raise ValueError(f"FLOAT_ENDPOINTS: chaves repetidas {repetidas}")
    for cfg in endpoints.values():
        for nome, exp in (cfg.get("explode") or {}).items():
            alvo = (exp.get("join") or {}).get("with")
            if alvo and alvo not in endpoints:
                raise ValueError(
                    f"FLOAT_ENDPOINTS: join de '{nome}' aponta para '{alvo}', "
                    "que não é um endpoint configurado"
                )


# ── Carga ───────────────────────────────────────────────────────────────────

def load_float_data(
    endpoints: dict[str, dict] = FLOAT_ENDPOINTS,
    manter_vazios: bool = True,
) -> dict[str, pd.DataFrame]:
    """
    Busca todos os endpoints de `endpoints` em paralelo, explode os campos
    aninhados configurados e aplica os joins.

    Parâmetros:
        endpoints:     configuração dos endpoints (ver config.FLOAT_ENDPOINTS).
        manter_vazios: mantém nas tabelas explodidas os registros sem itens
                       (uma linha só com as base_columns).

    Returns:
        {chave: DataFrame} — uma chave por endpoint (sem os campos aninhados) e
        uma por tabela explodida. Ex.: float_data["projects"], float_data["team"].
    """
    _validar(endpoints)
    if not endpoints:
        logger.warning("[float] nenhum endpoint configurado em FLOAT_ENDPOINTS")
        return {}

    # Pool comporta todos os endpoints paginando em paralelo
    session = _criar_sessao(pool=MAX_WORKERS * len(endpoints))

    logger.info("[float] buscando %s...", ", ".join(endpoints))
    with ThreadPoolExecutor(max_workers=len(endpoints)) as ex:
        futuros = {
            chave: ex.submit(_get_all, session, cfg["endpoint"], _params_requisicao(cfg))
            for chave, cfg in endpoints.items()
        }
        registros = {chave: fut.result() for chave, fut in futuros.items()}

    # Endpoints primeiro (os joins dependem deles), sem os campos aninhados
    data = {}
    for chave, cfg in endpoints.items():
        aninhados = {e["field"] for e in (cfg.get("explode") or {}).values()}
        data[chave] = pd.DataFrame(
            [{k: v for k, v in r.items() if k not in aninhados} for r in registros[chave]]
        )

    # Tabelas explodidas + joins
    for chave, cfg in endpoints.items():
        for nome, exp in (cfg.get("explode") or {}).items():
            df = _explodir(
                registros[chave], exp["field"], exp["prefix"],
                exp["base_columns"], manter_vazios,
            )
            if exp.get("join"):
                df = _juntar(df, data[exp["join"]["with"]], exp["join"], nome)
            data[nome] = df

    logger.info(
        "[float] %s", " | ".join(f"{k}: {df.shape}" for k, df in data.items())
    )
    return data
