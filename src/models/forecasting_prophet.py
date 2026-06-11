import os
import logging
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from neuralprophet import NeuralProphet
from sqlalchemy import create_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# NeuralProphet usa PyTorch Lightning internamente — silencia o output de treino
logging.getLogger("neuralprophet").setLevel(logging.ERROR)
logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)
logging.getLogger("lightning").setLevel(logging.ERROR)

DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.getenv('PGUSER', 'postgres')}:"
    f"{os.getenv('PGPASSWORD', '')}@"
    f"{os.getenv('PGHOST', 'localhost')}:"
    f"{os.getenv('PGPORT', '5432')}/"
    f"{os.getenv('PGDATABASE', 'zika')}"
)

DIR_PROCESSED = Path("data/processed")
DIR_PROCESSED.mkdir(parents=True, exist_ok=True)
Path("src/models").mkdir(parents=True, exist_ok=True)


def load_serie() -> pd.DataFrame:
    engine = create_engine(DB_URL)
    log.info("Lendo vw_serie_temporal_semanal...")
    df = pd.read_sql("SELECT * FROM sinan.vw_serie_temporal_semanal", engine)
    engine.dispose()
    return df


def build_ds(df: pd.DataFrame) -> pd.DataFrame:
    # agrega todas as UFs — série nacional por semana epidemiológica
    nacional = df.groupby(["nu_ano", "sem_pri"], as_index=False)["total_casos"].sum()

    # descarta semana 53 antes da conversão — nem todos os anos ISO têm essa semana
    nacional = nacional[nacional["sem_pri"].between(1, 52)]

    # monta ds no padrão ISO week: 'YYYY-WW-1' (segunda-feira da semana)
    nacional["ds"] = pd.to_datetime(
        nacional["nu_ano"].astype(str) + "-"
        + nacional["sem_pri"].astype(str).str.zfill(2) + "-1",
        format="%G-%V-%u",
        errors="coerce",
    )
    nacional.dropna(subset=["ds"], inplace=True)
    nacional = nacional.rename(columns={"total_casos": "y"})

    return nacional[["ds", "y"]].sort_values("ds").reset_index(drop=True)


def train_neuralprophet(serie: pd.DataFrame) -> tuple[NeuralProphet, pd.DataFrame]:
    m = NeuralProphet(
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        quantiles=[0.025, 0.975],
    )

    # garante dtype e índice limpos — NeuralProphet falha com Pandas 3.x sem isso
    serie["ds"] = pd.to_datetime(serie["ds"])
    serie = serie.reset_index(drop=True)

    log.info("Treinando NeuralProphet com %d semanas históricas...", len(serie))
    m.fit(serie, freq="W-MON")

    futuro = m.make_future_dataframe(df=serie, periods=52)
    forecast = m.predict(futuro)
    log.info("Previsão gerada: %d períodos (histórico + futuro)", len(forecast))

    return m, forecast


def save_outputs(m: NeuralProphet, forecast: pd.DataFrame, serie: pd.DataFrame):
    # detecta nomes reais das colunas de quantil (variam conforme versão do NeuralProphet)
    col_low  = next((c for c in forecast.columns if "2.5"  in c), None)
    col_high = next((c for c in forecast.columns if "97.5" in c), None)

    # salva CSV com nomes padronizados
    csv_out = forecast[["ds", "yhat1"]].rename(columns={"yhat1": "yhat"})
    if col_low:
        csv_out["yhat_lower"] = forecast[col_low]
    if col_high:
        csv_out["yhat_upper"] = forecast[col_high]

    csv_path = DIR_PROCESSED / "forecast_nacional.csv"
    csv_out.to_csv(csv_path, index=False)
    log.info("CSV salvo: %s", csv_path)

    # gráfico com estilo limpo em pt-BR
    fig, ax = plt.subplots(figsize=(14, 5))

    if col_low and col_high:
        ax.fill_between(
            forecast["ds"], forecast[col_low], forecast[col_high],
            alpha=0.25, color="#1f77b4", label="Intervalo de confiança (95%)",
        )
    ax.plot(forecast["ds"], forecast["yhat1"], color="#1f77b4", lw=1.8, label="Previsão")
    ax.scatter(serie["ds"], serie["y"], s=8, color="#444", zorder=3, label="Casos reais")

    # linha vertical separando histórico de futuro
    corte = serie["ds"].max()
    ax.axvline(corte, color="red", lw=1, ls="--", alpha=0.7, label="Início da previsão")

    ax.set_title("Previsão de Casos de Zika — Brasil (série semanal nacional)", fontsize=13)
    ax.set_xlabel("Data (semana epidemiológica)")
    ax.set_ylabel("Número de casos confirmados")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}".replace(",", ".")))
    ax.legend(fontsize=9)
    fig.tight_layout()

    png_path = DIR_PROCESSED / "forecast_plot_nacional.png"
    fig.savefig(png_path, dpi=150)
    plt.close(fig)
    log.info("Gráfico salvo: %s", png_path)


def run():
    df_raw  = load_serie()
    serie   = build_ds(df_raw)
    m, forecast = train_neuralprophet(serie)
    save_outputs(m, forecast, serie)
    log.info("Pipeline NeuralProphet concluído.")


if __name__ == "__main__":
    run()
