"""
psa_loader.py — Consolida e carrega os exports do PSA.

Fluxo:
  1. `consolidate_psa_exports` lê os exports brutos em PSA_SOURCE_DIR (servidor),
     que podem vir divididos em vários arquivos por tema, e salva um arquivo
     consolidado por tema em PSA_RAW_DIR (data/raw): "<output>_<AAAA-MM-DD>.<ext>".
  2. `load_psa_data` lê de PSA_RAW_DIR o consolidado mais recente de cada tema
     (pela data do nome). Os consolidados antigos ficam como histórico.

Os temas usados pelo projeto são definidos em config.PSA_THEMES; este módulo não
tem nenhum tema fixo no código. Os demais arquivos da pasta de origem são ignorados.
"""

import glob
import logging
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from config import PSA_RAW_DIR, PSA_SOURCE_DIR, PSA_THEMES

logger = logging.getLogger(__name__)

PSA_EXPORT_EXTENSIONS = {".csv", ".xlsx"}


# ── Consolidação ────────────────────────────────────────────────────────────

def _match_theme(caminho: Path, themes: dict[str, dict]) -> str | None:
    """Tema do arquivo pelo INÍCIO do nome; None (com aviso) se casar com 0 ou 2+ temas."""
    nome = caminho.name.casefold()
    matches = [
        tema for tema, cfg in themes.items()
        if nome.startswith(cfg["prefix"].casefold())
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        logger.warning("Arquivo sem tema correspondente (ignorado): %s", caminho.name)
    else:
        logger.warning(
            "Arquivo casa com mais de um tema %s (ignorado): %s", matches, caminho.name
        )
    return None


def _read_export(caminho: Path) -> pd.DataFrame:
    """Lê um export bruto do PSA (.csv UTF-8 separado por vírgula, ou .xlsx)."""
    try:
        if caminho.suffix.lower() == ".csv":
            return pd.read_csv(caminho, encoding="utf-8", sep=",")
        return pd.read_excel(caminho, sheet_name=0)
    except Exception as exc:
        logger.error("Falha ao ler %s: %s: %s", caminho.name, type(exc).__name__, exc)
        raise


def consolidate_psa_exports(
    source_dir: Path = PSA_SOURCE_DIR,
    target_dir: Path = PSA_RAW_DIR,
    themes: dict[str, dict] = PSA_THEMES,
    run_date: date | None = None,
) -> dict[str, Path]:
    """
    Consolida os exports brutos do PSA em um arquivo por tema.

    O PSA não exporta arquivos grandes de uma vez, então um tema pode vir dividido
    em N arquivos com a mesma estrutura de colunas (ex.: "<Tema> - Status - Active"
    e "<Tema> - Status - Closed"). Os arquivos de cada tema (`themes`, ver
    config.PSA_THEMES) são concatenados, as linhas repetidas entre arquivos
    diferentes removidas (repetições dentro de um mesmo arquivo são mantidas),
    e o resultado salvo em `target_dir` como "<output>_<AAAA-MM-DD>.<ext>", formato
    esperado por `load_psa_data`. A extensão segue a dos arquivos de origem; se
    houver mistura, vale a do arquivo mais recente.

    Consolidados de datas anteriores são mantidos (histórico); rodar de novo no
    mesmo dia sobrescreve o arquivo do dia.

    Returns:
        {tema: caminho do arquivo consolidado salvo}

    Raises:
        FileNotFoundError: `source_dir` inacessível (servidor fora / sem rede).
        ValueError: arquivos de um mesmo tema com colunas divergentes.
    """
    run_date = run_date or date.today()

    try:
        acessivel = source_dir.is_dir()
    except OSError:
        acessivel = False
    if not acessivel:
        msg = (
            f"Pasta de origem do PSA inacessível: {source_dir} "
            "(servidor fora do ar ou máquina sem acesso à rede?). "
            "Para rodar localmente, defina PSA_SOURCE_DIR no .env."
        )
        logger.error(msg)
        raise FileNotFoundError(msg)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Agrupa os arquivos por tema
    por_tema: dict[str, list[Path]] = {tema: [] for tema in themes}
    for caminho in sorted(source_dir.iterdir()):
        if not caminho.is_file() or caminho.name.startswith("~$"):  # lock do Excel
            continue
        if caminho.suffix.lower() not in PSA_EXPORT_EXTENSIONS:
            logger.warning("Extensão não suportada (ignorado): %s", caminho.name)
            continue
        tema = _match_theme(caminho, themes)
        if tema:
            por_tema[tema].append(caminho)

    salvos = {}
    for tema, arquivos in por_tema.items():
        if not arquivos:
            logger.warning("[%s] nenhum arquivo encontrado em %s", tema, source_dir)
            continue

        dfs = {}
        for caminho in arquivos:
            logger.info("[%s] lendo: %s", tema, caminho.name)
            dfs[caminho] = _read_export(caminho)

        # Todos os arquivos do tema devem ter a mesma estrutura do primeiro
        ref_path, ref_df = next(iter(dfs.items()))
        ref_cols = list(ref_df.columns)
        divergentes = [
            f"{p.name} (faltando: {sorted(set(ref_cols) - set(df.columns))}, "
            f"extras: {sorted(set(df.columns) - set(ref_cols))})"
            for p, df in dfs.items()
            if list(df.columns) != ref_cols
        ]
        if divergentes:
            msg = (
                f"[{tema}] colunas divergentes em relação a {ref_path.name}: "
                + "; ".join(divergentes)
            )
            logger.error(msg)
            raise ValueError(msg)

        # Remove só linhas repetidas ENTRE arquivos (sobreposição dos exports
        # divididos). Linhas idênticas dentro de um mesmo arquivo são lançamentos
        # legítimos e são mantidas: a ocorrência (cumcount) dentro do arquivo
        # entra na chave, então a 2ª linha igual de um arquivo só casa com a 2ª
        # linha igual de outro.
        OCC = "__ocorrencia__"
        partes = [
            df.assign(**{OCC: df.groupby(ref_cols, dropna=False).cumcount()})
            for df in dfs.values() if not df.empty
        ]
        if partes:
            df_final = pd.concat(partes, ignore_index=True)
        else:
            df_final = ref_df.assign(**{OCC: 0})
        total = len(df_final)
        df_final = df_final.drop_duplicates(ignore_index=True).drop(columns=OCC)

        extensoes = {p.suffix.lower() for p in arquivos}
        ext = max(arquivos, key=lambda f: f.stat().st_mtime).suffix.lower()
        if len(extensoes) > 1:
            logger.warning(
                "[%s] extensões misturadas %s — salvando como %s (arquivo mais recente)",
                tema, sorted(extensoes), ext,
            )

        destino = target_dir / f"{themes[tema]['output']}_{run_date:%Y-%m-%d}{ext}"
        if ext == ".csv":
            df_final.to_csv(destino, index=False, encoding="utf-8-sig")
        else:
            df_final.to_excel(destino, index=False, sheet_name="Sheet 1")

        logger.info(
            "[%s] %d arquivo(s), %d linhas, %d repetida(s) entre arquivos removida(s) -> %s",
            tema, len(arquivos), len(df_final), total - len(df_final), destino.name,
        )
        salvos[tema] = destino

    return salvos


# ── Carga ───────────────────────────────────────────────────────────────────

def _latest_file(folder: Path, pattern: str, key=None) -> Path:
    """Retorna o arquivo mais recente que corresponde ao padrão.

    Por padrão ordena pela data de modificação (mtime); passe `key` para usar
    outro critério (ex: `_date_from_filename`, a data extraída do nome)."""
    matches = [
        f for f in folder.glob(pattern)
        if f.suffix.lower() in PSA_EXPORT_EXTENSIONS and not f.name.startswith("~$")
    ]
    if not matches:
        raise FileNotFoundError(
            f"Nenhum arquivo encontrado com o padrão '{pattern}' em: {folder}"
        )
    return max(matches, key=key or (lambda f: f.stat().st_mtime))


def _date_from_filename(caminho: Path) -> datetime:
    """Extrai a data (YYYY-MM-DD) do nome do arquivo; usa mtime como fallback."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", caminho.stem)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d")
    return datetime.fromtimestamp(caminho.stat().st_mtime)


def _read_consolidated(caminho: Path) -> pd.DataFrame:
    """Lê um consolidado gravado por `consolidate_psa_exports` (.csv UTF-8 com BOM
    ou .xlsx)."""
    if caminho.suffix.lower() == ".csv":
        return pd.read_csv(caminho, encoding="utf-8-sig")
    return pd.read_excel(caminho, sheet_name=0)


def load_psa_data(
    raw_dir: Path = PSA_RAW_DIR,
    themes: dict[str, dict] = PSA_THEMES,
) -> dict[str, pd.DataFrame]:
    """
    Lê de `raw_dir` o consolidado mais recente (pela data do nome) de cada tema
    de `themes` e retorna um dicionário de DataFrames.

    Se o tema tiver "expected_columns" em config.PSA_THEMES, valida que essas
    colunas existem no arquivo (protege contra mudanças no layout do export).

    Returns:
        {tema: DataFrame do consolidado mais recente}

    Raises:
        FileNotFoundError: nenhum consolidado do tema em `raw_dir`.
        ValueError: colunas esperadas ausentes.
    """
    data = {}
    for tema, cfg in themes.items():
        # escape: nomes com [ ] ou * não podem virar curinga do glob
        pattern = f"{glob.escape(cfg['output'])}_*"
        path = _latest_file(raw_dir, pattern, key=_date_from_filename)
        logger.info("[%s] usando: %s", tema, path.name)
        df = _read_consolidated(path)

        missing = set(cfg.get("expected_columns", ())) - set(df.columns)
        if missing:
            msg = f"[{tema}] colunas esperadas ausentes em {path.name}: {sorted(missing)}"
            logger.error(msg)
            raise ValueError(msg)

        logger.info("[%s] %d linhas carregadas", tema, len(df))
        data[tema] = df

    return data
