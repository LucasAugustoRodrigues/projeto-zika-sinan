import argparse
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _run_etl() -> float:
    from src.etl.pipeline_ingestao import run as etl_run
    t0 = time.perf_counter()
    etl_run()
    return time.perf_counter() - t0


def _run_prophet() -> float:
    from src.models.forecasting_prophet import run as prophet_run
    t0 = time.perf_counter()
    prophet_run()
    return time.perf_counter() - t0


def _run_kmeans() -> float:
    from src.models.clustering_kmeans import run as kmeans_run
    t0 = time.perf_counter()
    kmeans_run()
    return time.perf_counter() - t0


def _step(name: str, fn) -> tuple[bool, float]:
    log.info("=== %s ===", name)
    t0 = time.perf_counter()
    try:
        fn()
        elapsed = time.perf_counter() - t0
        log.info("%s concluído em %.1fs", name, elapsed)
        return True, elapsed
    except (Exception, SystemExit) as exc:
        elapsed = time.perf_counter() - t0
        log.error("%s falhou: %s", name, exc)
        return False, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Orquestrador do pipeline Zika SINAN",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "exemplos:\n"
            "  python main.py --etl\n"
            "  python main.py --models\n"
            "  python main.py --all\n"
            "  python main.py --etl --models"
        ),
    )
    parser.add_argument("--etl",    action="store_true", help="executa a ingestão ETL do CSV")
    parser.add_argument("--models", action="store_true", help="executa NeuralProphet + K-Means")
    parser.add_argument("--all",    action="store_true", help="ETL → NeuralProphet → K-Means (sequencial)")
    args = parser.parse_args()

    if not (args.etl or args.models or args.all):
        parser.print_help()
        return

    run_etl    = args.all or args.etl
    run_models = args.all or args.models
    results: dict[str, tuple[bool, float]] = {}

    if run_etl:
        results["ETL"] = _step("ETL", _run_etl)

    if run_models:
        results["NeuralProphet"] = _step("NeuralProphet", _run_prophet)
        results["K-Means"]       = _step("K-Means",       _run_kmeans)

    log.info("=== Resumo ===")
    for name, (ok, sec) in results.items():
        status = "OK" if ok else "FALHOU"
        log.info("  %-15s %7.1fs  [%s]", name, sec, status)

    failed = [n for n, (ok, _) in results.items() if not ok]
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
