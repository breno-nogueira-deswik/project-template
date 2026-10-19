"""
main.py — Orquestrador do pipeline.

Fluxo: ingestão (PSA, Float) -> transformação -> saída (data/output/).

Feito para rodar pelo Agendador de Tarefas com pythonw.exe (sem janela de
console). Sem console, print e erros não aparecem em lugar nenhum, então:
  - tudo é registrado via logging em logs/pipeline_<timestamp>.log;
  - qualquer erro é gravado no log com o traceback completo;
  - o processo termina com código 1 em caso de erro, para o Agendador mostrar
    a falha em "Resultado da Última Execução" (0x1).
Rodando pelo terminal (python main.py), o log também aparece na tela.

Execução:
    python main.py      # manual, com saída no terminal
    pythonw main.py     # Agendador de Tarefas, sem janela
"""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from config import FLOAT_ENDPOINTS, LOG_RETENTION_DAYS, LOGS_DIR, PSA_THEMES
from src.ingestion.float_loader import load_float_data
from src.ingestion.psa_loader import consolidate_psa_exports, load_psa_data

logger = logging.getLogger("pipeline")


def _configurar_logging() -> Path:
    """Log em arquivo (sempre) e no terminal (só se houver console)."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"pipeline_{datetime.now():%Y-%m-%d_%H%M%S}.log"

    handlers = [logging.FileHandler(log_path, encoding="utf-8")]
    # Com pythonw, sys.stdout é None: um StreamHandler quebraria ao escrever
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
    # Warnings do Python/pandas iriam para o stderr (inexistente no pythonw)
    logging.captureWarnings(True)
    return log_path


def _limpar_logs_antigos(dias: int = LOG_RETENTION_DAYS) -> None:
    """Apaga logs do pipeline com mais de `dias` dias."""
    limite = datetime.now() - timedelta(days=dias)
    for log in LOGS_DIR.glob("pipeline_*.log"):
        try:
            if datetime.fromtimestamp(log.stat().st_mtime) < limite:
                log.unlink()
        except OSError as exc:  # ex.: arquivo aberto em outro programa
            logger.warning("Não foi possível apagar %s: %s", log.name, exc)


def run_pipeline() -> None:
    """Executa o pipeline de ponta a ponta."""
    logger.info("[1/3] Ingestão")
    # Cada fonte só roda se estiver configurada no config.py
    psa_data = {}
    if PSA_THEMES:
        consolidate_psa_exports()
        psa_data = load_psa_data()
    float_data = {}
    if FLOAT_ENDPOINTS:
        float_data = load_float_data()

    logger.info("[2/3] Transformação")
    # TODO: chamar as funções de src/transform/ (ex.: build_<tema>(psa_data, float_data))

    logger.info("[3/3] Saída")
    # TODO: chamar as funções de src/output/ (ex.: export_<relatorio>(df) em data/output/)


def main() -> int:
    log_path = _configurar_logging()
    _limpar_logs_antigos()

    inicio = datetime.now()
    logger.info("Pipeline iniciado — log: %s", log_path.name)
    try:
        run_pipeline()
    except Exception:
        # logger.exception grava a mensagem + traceback completo no log
        logger.exception("Pipeline falhou após %.1fs", (datetime.now() - inicio).total_seconds())
        return 1

    logger.info("Pipeline concluído em %.1fs", (datetime.now() - inicio).total_seconds())
    return 0


if __name__ == "__main__":
    sys.exit(main())
