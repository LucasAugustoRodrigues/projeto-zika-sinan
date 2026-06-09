import os
import logging
import sys
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sqlalchemy import create_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.getenv('PGUSER', 'postgres')}:"
    f"{os.getenv('PGPASSWORD', 'lucas01')}@"
    f"{os.getenv('PGHOST', 'localhost')}:"
    f"{os.getenv('PGPORT', '5432')}/"
    f"{os.getenv('PGDATABASE', 'zika')}"
)

DIR_PROCESSED = Path("data/processed")
DIR_PROCESSED.mkdir(parents=True, exist_ok=True)

MIN_CASOS    = 10   # municípios com menos casos são descartados
K_RANGE      = range(2, 9)
K_DEFAULT    = 4    # usado se o método do cotovelo não for conclusivo
RANDOM_STATE = 42

QUERY = """
    SELECT
        n.id_municip,
        COUNT(*)                                                        AS total_casos,
        ROUND(
            100.0 * COUNT(*) FILTER (WHERE p.cs_gestant IN (1,2,3))
                  / COUNT(*), 2
        )                                                               AS perc_gestantes,
        ROUND(
            100.0 * COUNT(*) FILTER (WHERE ec.evolucao = 2)
                  / COUNT(*), 2
        )                                                               AS perc_obitos,
        ROUND(AVG((n.dt_notific - lc.dt_sin_pri))::NUMERIC, 2)         AS media_atraso_dias,
        ROUND(AVG(p.age_years)::NUMERIC, 2)                            AS media_age_anos
    FROM  sinan.notificacao      n
    JOIN  sinan.evolucao_clinica ec USING (id_notif)
    JOIN  sinan.paciente         p  ON p.id_paciente = n.id_paciente
    JOIN  sinan.localizacao_caso lc USING (id_notif)
    WHERE ec.classi_fin   = 1
      AND lc.dt_sin_pri  IS NOT NULL
    GROUP BY n.id_municip
    HAVING COUNT(*) >= 10
"""

FEATURES = ["total_casos", "perc_gestantes", "perc_obitos", "media_atraso_dias", "media_age_anos"]


def load_data() -> pd.DataFrame:
    log.info("Conectando ao banco e lendo dados por município...")
    engine = create_engine(DB_URL)
    df = pd.read_sql(QUERY, engine)
    engine.dispose()
    log.info("Leitura concluída: %d linhas, %d colunas", *df.shape)
    return df


def filter_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    log.info("Aplicando filtro: municípios com >= %d casos confirmados...", MIN_CASOS)
    antes = len(df)

    # remove linhas com qualquer feature nula (ex: municípios sem idade registrada)
    df = df.dropna(subset=FEATURES)
    log.info("Após remover nulos nas features: %d → %d municípios", antes, len(df))

    if df.empty:
        log.error(
            "DataFrame vazio após filtragem. Possíveis causas: "
            "nenhum município tem >= %d casos confirmados (classi_fin=1) com dt_sin_pri preenchida, "
            "ou as features têm 100%% de nulos. Verifique o ETL e a view.",
            MIN_CASOS,
        )
        sys.exit(1)

    return df.reset_index(drop=True)


def normalize(df: pd.DataFrame) -> tuple[pd.DataFrame, StandardScaler]:
    log.info("Normalizando %d features com StandardScaler...", len(FEATURES))
    scaler = StandardScaler()
    X = scaler.fit_transform(df[FEATURES])
    log.info("Normalização concluída — shape: %s", X.shape)
    return pd.DataFrame(X, columns=FEATURES), scaler


def choose_k(X: pd.DataFrame) -> int:
    log.info("Calculando inércia e silhouette para k=%d até %d...", K_RANGE.start, K_RANGE.stop - 1)
    inertias, silhouettes = [], []

    for k in K_RANGE:
        km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init="auto")
        labels = km.fit_predict(X)
        inertias.append(km.inertia_)
        sil = silhouette_score(X, labels)
        silhouettes.append(sil)
        log.info("  k=%d — inércia=%.1f  silhouette=%.4f", k, km.inertia_, sil)

    # k ótimo pelo maior silhouette
    k_opt = list(K_RANGE)[silhouettes.index(max(silhouettes))]
    log.info("k ótimo pelo silhouette: %d (score=%.4f)", k_opt, max(silhouettes))

    _save_elbow(list(K_RANGE), inertias, silhouettes, k_opt)
    return k_opt


def _validate_k(X: pd.DataFrame, k: int, n_total: int) -> int:
    km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init="auto")
    labels = km.fit_predict(X)
    menor_cluster = pd.Series(labels).value_counts().min()

    if menor_cluster / n_total < 0.05:
        log.warning(
            "k=%d gerou cluster com apenas %d/%d municípios (%.1f%% < 5%%) — "
            "provável dominância de outliers. Usando fallback k=%d.",
            k, menor_cluster, n_total, 100 * menor_cluster / n_total, K_DEFAULT,
        )
        return K_DEFAULT

    return k


def _save_elbow(ks, inertias, silhouettes, k_opt):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

    ax1.plot(ks, inertias, marker="o", color="#1f77b4")
    ax1.axvline(k_opt, color="red", ls="--", lw=1, alpha=0.7)
    ax1.set_title("Método do Cotovelo")
    ax1.set_xlabel("Número de clusters (k)")
    ax1.set_ylabel("Inércia")
    ax1.xaxis.set_major_locator(mticker.MultipleLocator(1))

    ax2.plot(ks, silhouettes, marker="o", color="#2ca02c")
    ax2.axvline(k_opt, color="red", ls="--", lw=1, alpha=0.7, label=f"k={k_opt} (ótimo)")
    ax2.set_title("Silhouette Score")
    ax2.set_xlabel("Número de clusters (k)")
    ax2.set_ylabel("Silhouette")
    ax2.xaxis.set_major_locator(mticker.MultipleLocator(1))
    ax2.legend(fontsize=9)

    fig.suptitle("Seleção de k — Clustering de Municípios (Zika SINAN)", fontsize=12)
    fig.tight_layout()

    path = DIR_PROCESSED / "clustering_elbow.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    log.info("Gráfico do cotovelo salvo: %s", path)


def train_kmeans(df_original: pd.DataFrame, X_norm: pd.DataFrame, k: int) -> pd.DataFrame:
    log.info("Treinando KMeans com k=%d e random_state=%d...", k, RANDOM_STATE)
    km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init="auto")
    df_original = df_original.copy()
    df_original["cluster"] = km.fit_predict(X_norm)

    for c in range(k):
        n = (df_original["cluster"] == c).sum()
        log.info("  Cluster %d: %d municípios", c, n)

    sil = silhouette_score(X_norm, df_original["cluster"])
    log.info("Silhouette final (k=%d): %.4f", k, sil)
    return df_original


def save_results(df: pd.DataFrame):
    path = DIR_PROCESSED / "clustering_municipios.csv"
    df.to_csv(path, index=False)
    log.info("CSV com clusters salvo: %s  (%d municípios)", path, len(df))


def run():
    df_raw  = load_data()
    df      = filter_and_clean(df_raw)
    X_norm, _ = normalize(df)
    k       = choose_k(X_norm)
    k       = _validate_k(X_norm, k, len(df))
    df_clus = train_kmeans(df, X_norm, k)
    save_results(df_clus)
    log.info("Pipeline K-Means concluído.")


if __name__ == "__main__":
    run()
