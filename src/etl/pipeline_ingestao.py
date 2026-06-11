import os
import sys
import logging

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DB_PARAMS = {
    "host":     os.getenv("PGHOST",     "localhost"),
    "port":     int(os.getenv("PGPORT", "5432")),
    "dbname":   os.getenv("PGDATABASE", "zika"),
    "user":     os.getenv("PGUSER",     "postgres"),
    "password": os.getenv("PGPASSWORD", ""),
}

CSV_PATH   = os.getenv("CSV_PATH", "data/raw/ZIKA_BR_2018_2026_UNIFICADO.csv")
CHUNK_SIZE = 10_000

UFS = [
    (11, "RO", "Rondônia",            "Norte"),
    (12, "AC", "Acre",                "Norte"),
    (13, "AM", "Amazonas",            "Norte"),
    (14, "RR", "Roraima",             "Norte"),
    (15, "PA", "Pará",                "Norte"),
    (16, "AP", "Amapá",               "Norte"),
    (17, "TO", "Tocantins",           "Norte"),
    (21, "MA", "Maranhão",            "Nordeste"),
    (22, "PI", "Piauí",               "Nordeste"),
    (23, "CE", "Ceará",               "Nordeste"),
    (24, "RN", "Rio Grande do Norte", "Nordeste"),
    (25, "PB", "Paraíba",             "Nordeste"),
    (26, "PE", "Pernambuco",          "Nordeste"),
    (27, "AL", "Alagoas",             "Nordeste"),
    (28, "SE", "Sergipe",             "Nordeste"),
    (29, "BA", "Bahia",               "Nordeste"),
    (31, "MG", "Minas Gerais",        "Sudeste"),
    (32, "ES", "Espírito Santo",      "Sudeste"),
    (33, "RJ", "Rio de Janeiro",      "Sudeste"),
    (35, "SP", "São Paulo",           "Sudeste"),
    (41, "PR", "Paraná",              "Sul"),
    (42, "SC", "Santa Catarina",      "Sul"),
    (43, "RS", "Rio Grande do Sul",   "Sul"),
    (50, "MS", "Mato Grosso do Sul",  "Centro-Oeste"),
    (51, "MT", "Mato Grosso",         "Centro-Oeste"),
    (52, "GO", "Goiás",               "Centro-Oeste"),
    (53, "DF", "Distrito Federal",    "Centro-Oeste"),
]

UF_CODIGOS = {uf[0] for uf in UFS}


def _conn():
    return psycopg2.connect(**DB_PARAMS)


def _si(v) -> int | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _sf(v) -> float | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _ss(v) -> str | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except TypeError:
        pass
    s = str(v).strip()
    return s if s else None


def _sd(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v.date() if hasattr(v, "date") else v


def _parse_dates(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for col in cols:
        if col not in df.columns:
            continue
        s = df[col].replace({"0000-00-00": None, "0": None, "": None})
        df[col] = pd.to_datetime(s, errors="coerce")
    return df


def _nullable_int(series: pd.Series, ignore: set) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    return s.where(~s.isin(ignore), other=pd.NA).astype("Int32")


def _extract_sem(series: pd.Series) -> pd.Series:
    # SEM_NOT e SEM_PRI vêm no formato YYYYWW — extrai só a semana epidemiológica
    s = pd.to_numeric(series, errors="coerce")
    sem = (s % 100).astype("Int16")
    return sem.where(sem.between(1, 53), other=pd.NA)


def _decode_age(df: pd.DataFrame) -> pd.DataFrame:
    nu = pd.to_numeric(df["NU_IDADE_N"], errors="coerce")
    df["age_unit"]  = (nu // 1000).astype("Int16")
    df["age_value"] = (nu % 1000).astype("Int16")

    # separando unidade e valor para calcular age_years vetorialmente
    u = df["age_unit"]
    v = df["age_value"].astype("Float64")
    age = pd.Series(pd.NA, index=df.index, dtype="Float64")
    age = age.where(u != 4, other=v)
    age = age.where(u != 3, other=(v / 12).round(3))
    age = age.where(u != 2, other=(v / 365).round(3))
    age = age.where(u != 1, other=(v / 8760).round(3))
    df["age_years"] = age
    return df


def _valid_mun_codes(series: pd.Series) -> set:
    # filtrando lixo do SINAN nos códigos IBGE — só 6 ou 7 dígitos
    s = pd.to_numeric(series, errors="coerce").dropna().astype("int64")
    return set(s[(s >= 100_000) & (s <= 9_999_999)].unique())


def load_dim_uf(conn):
    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO sinan.dim_uf (sg_uf, sigla, nome_uf, regiao) VALUES %s "
            "ON CONFLICT (sg_uf) DO NOTHING",
            UFS,
        )
    conn.commit()
    log.info("dim_uf: %d registros", len(UFS))


def load_dim_municipio(conn, df: pd.DataFrame):
    all_codes: set = set()
    for col in ["ID_MUNICIP", "ID_MN_RESI", "COMUNINF"]:
        if col in df.columns:
            all_codes |= _valid_mun_codes(df[col])

    rows = []
    for code in sorted(all_codes):
        sg_uf = int(str(int(code))[:2])
        if sg_uf in UF_CODIGOS:
            rows.append((int(code), f"Município {code}", sg_uf, False))

    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO sinan.dim_municipio (id_municipio, nome_municipio, sg_uf, capital) VALUES %s "
            "ON CONFLICT (id_municipio) DO NOTHING",
            rows,
            page_size=5_000,
        )
    conn.commit()
    log.info("dim_municipio: %d registros", len(rows))


def load_dim_unidade(conn, df: pd.DataFrame):
    sub = df[["ID_UNIDADE", "TPUNINOT", "SG_UF_NOT"]].copy()
    sub["ID_UNIDADE"] = pd.to_numeric(sub["ID_UNIDADE"], errors="coerce")
    sub = sub.dropna(subset=["ID_UNIDADE"])
    sub["ID_UNIDADE"] = sub["ID_UNIDADE"].astype("int64")
    sub["TPUNINOT"]   = pd.to_numeric(sub["TPUNINOT"],  errors="coerce")
    sub["SG_UF_NOT"]  = pd.to_numeric(sub["SG_UF_NOT"], errors="coerce")
    # UF inválida vira nula para não quebrar FK
    sub["SG_UF_NOT"] = sub["SG_UF_NOT"].where(sub["SG_UF_NOT"].isin(UF_CODIGOS), other=pd.NA)

    dedup = sub.drop_duplicates(subset=["ID_UNIDADE"])
    rows = [
        (_si(r.ID_UNIDADE), _si(r.TPUNINOT), _si(r.SG_UF_NOT))
        for r in dedup.itertuples(index=False)
    ]

    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO sinan.dim_unidade_saude (id_unidade, tp_uninot, sg_uf_not) VALUES %s "
            "ON CONFLICT (id_unidade) DO NOTHING",
            rows,
            page_size=5_000,
        )
    conn.commit()
    log.info("dim_unidade_saude: %d registros", len(rows))


def _register_run(conn, arquivo: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sinan.etl_run_log (arquivo_origem, status) "
            "VALUES (%s, 'RUNNING') RETURNING id",
            (arquivo,),
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def _finish_run(
    conn, run_id: int, lidas: int, inseridas: int,
    rejeitadas: int, status: str, erro: str = None,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE sinan.etl_run_log
               SET finalizado_em     = NOW(),
                   linhas_lidas      = %s,
                   linhas_inseridas  = %s,
                   linhas_rejeitadas = %s,
                   status            = %s,
                   detalhes_erro     = %s
             WHERE id = %s
            """,
            (lidas, inseridas, rejeitadas, status, erro, run_id),
        )
    conn.commit()


def transform(chunk: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    df = chunk.copy()
    df = _decode_age(df)
    df = _parse_dates(
        df, ["DT_NOTIFIC", "DT_SIN_PRI", "DT_OBITO", "DT_ENCERRA", "DT_INVEST", "DT_DIGITA"]
    )

    df["CS_RACA"]    = _nullable_int(df["CS_RACA"],    {9})
    df["CS_ESCOL_N"] = _nullable_int(df["CS_ESCOL_N"], {9, 10})
    df["EVOLUCAO"]   = _nullable_int(df["EVOLUCAO"],   {9})
    df["CS_GESTANT"] = _nullable_int(df["CS_GESTANT"], {9})
    df["CLASSI_FIN"] = _nullable_int(df["CLASSI_FIN"], {9})
    df["CRITERIO"]   = _nullable_int(df["CRITERIO"],   {9})
    df["DOENCA_TRA"] = _nullable_int(df["DOENCA_TRA"], {0, 9}) # CHECK (1,2) — 0 e 9 viram NULL
    df["TPAUTOCTO"]  = _nullable_int(df["TPAUTOCTO"],  {9})   # CHECK (1,2,3) — mesmo problema

    df["sem_not"] = _extract_sem(df["SEM_NOT"])
    df["sem_pri"] = _extract_sem(df["SEM_PRI"])

    # UF de notificação — filtra inválidas para não quebrar FK
    sg_not = pd.to_numeric(df["SG_UF_NOT"], errors="coerce")
    df["sg_uf_not_fk"] = sg_not.where(sg_not.isin(UF_CODIGOS), other=pd.NA)

    # UF de residência — opcional, pode ser nula
    sg_res = pd.to_numeric(df["SG_UF"], errors="coerce")
    df["sg_uf_res_fk"] = sg_res.where(sg_res.isin(UF_CODIGOS), other=pd.NA)

    # municípios — só aceita códigos com 6 ou 7 dígitos
    for raw, dest in [("ID_MUNICIP", "id_municip_fk"), ("ID_MN_RESI", "id_mn_resi_fk")]:
        s = pd.to_numeric(df[raw], errors="coerce")
        df[dest] = s.where(s.between(100_000, 9_999_999), other=pd.NA).astype("Int64")

    # descarta linhas sem FKs obrigatórias
    mask = (
        df["DT_NOTIFIC"].notna()
        & df["sem_not"].notna()
        & df["sg_uf_not_fk"].notna()
        & df["id_municip_fk"].notna()
    )
    df_ok = df[mask].reset_index(drop=True)
    return df_ok, int((~mask).sum())


def load_chunk(conn, df: pd.DataFrame) -> int:
    # paciente: sem FK, sempre primeiro
    pac_rows = [
        (
            _ss(r.CS_SEXO),
            _si(r.age_unit),
            _si(r.age_value),
            _sf(r.age_years),
            _si(r.ANO_NASC),
            _si(r.CS_RACA),
            _si(r.CS_ESCOL_N),
            _si(r.ID_OCUPA_N),
            _si(r.CS_GESTANT),
        )
        for r in df.itertuples(index=False)
    ]

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO sinan.paciente
                (cs_sexo, age_unit, age_value, age_years, ano_nasc,
                 cs_raca, cs_escol_n, id_ocupa_n, cs_gestant)
            VALUES %s
            RETURNING id_paciente
            """,
            pac_rows,
            page_size=CHUNK_SIZE,
        )
        ids_pac = [row[0] for row in cur.fetchall()]

    df["paciente_id"] = ids_pac

    # notificacao: depende de paciente_id
    not_rows = [
        (
            _ss(r.arquivo_origem),
            _si(r.ano_arquivo),
            _si(r.TP_NOT) or 2,
            _ss(r.ID_AGRAVO),
            _sd(r.DT_NOTIFIC),
            _si(r.sem_not),
            _si(r.NU_ANO),
            _si(r.sg_uf_not_fk),
            _si(r.id_municip_fk),
            _si(r.ID_REGIONA),
            _si(r.ID_UNIDADE),
            int(r.paciente_id),
            _sd(r.DT_INVEST),
            _sd(r.DT_DIGITA),
        )
        for r in df.itertuples(index=False)
    ]

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO sinan.notificacao
                (arquivo_origem, ano_arquivo, tp_not, id_agravo, dt_notific,
                 sem_not, nu_ano, sg_uf_not, id_municip, id_regiona,
                 id_unidade, id_paciente, dt_invest, dt_digita)
            VALUES %s
            RETURNING id_notif
            """,
            not_rows,
            page_size=CHUNK_SIZE,
        )
        ids_not = [row[0] for row in cur.fetchall()]

    df["notif_id"] = ids_not

    # evolucao_clinica e localizacao_caso: dependem de notif_id, loop único
    ev_rows, loc_rows = [], []
    for r in df.itertuples(index=False):
        id_notif = int(r.notif_id)

        ev_rows.append((
            id_notif,
            _si(r.CLASSI_FIN),
            _si(r.CRITERIO),
            _si(r.EVOLUCAO),
            _sd(r.DT_OBITO),
            _sd(r.DT_ENCERRA),
            _si(r.DOENCA_TRA),
            _si(r.NDUPLIC_N),
            _si(r.IN_VINCULA),
            _si(r.CS_FLXRET),
            _si(r.FLXRECEBI),
            _si(r.TP_SISTEMA),
        ))

        loc_rows.append((
            id_notif,
            _sd(r.DT_SIN_PRI),
            _si(r.sem_pri),
            _si(r.sg_uf_res_fk),
            _si(r.id_mn_resi_fk),
            _si(r.ID_RG_RESI),
            _si(r.ID_PAIS) or 1,
            _si(r.TPAUTOCTO),
            _si(r.COUFINF),
            _si(r.COMUNINF),
            _si(r.COPAISINF),
            _si(r.CS_SUSPEIT),
        ))

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO sinan.evolucao_clinica
                (id_notif, classi_fin, criterio, evolucao, dt_obito, dt_encerra,
                 doenca_tra, nduplic_n, in_vincula, cs_flxret, flxrecebi, tp_sistema)
            VALUES %s
            """,
            ev_rows,
            page_size=CHUNK_SIZE,
        )
        execute_values(
            cur,
            """
            INSERT INTO sinan.localizacao_caso
                (id_notif, dt_sin_pri, sem_pri, sg_uf, id_mn_resi, id_rg_resi,
                 id_pais, tpautocto, coufinf, comuninf, copaisinf, cs_suspeit)
            VALUES %s
            """,
            loc_rows,
            page_size=CHUNK_SIZE,
        )

    conn.commit()
    return len(ids_not)


def run():
    log.info("ETL iniciado — %s", CSV_PATH)
    conn = _conn()

    # leitura completa só para extrair dimensões; depois processa em chunks
    log.info("Lendo CSV para extração de dimensões...")
    df_full = pd.read_csv(CSV_PATH, dtype=str, low_memory=False)
    total_linhas = len(df_full)
    log.info("Total de linhas: %d", total_linhas)

    try:
        load_dim_uf(conn)
        load_dim_municipio(conn, df_full)
        load_dim_unidade(conn, df_full)
    except Exception as exc:
        conn.rollback()
        log.error("Falha ao carregar dimensões: %s", exc)
        conn.close()
        sys.exit(1)

    del df_full

    run_id          = _register_run(conn, os.path.basename(CSV_PATH))
    total_inseridas = 0
    total_rejeit    = 0

    try:
        chunks = pd.read_csv(CSV_PATH, dtype=str, low_memory=False, chunksize=CHUNK_SIZE)
        for i, chunk in enumerate(chunks, start=1):
            log.info("Chunk %d — %d linhas brutas", i, len(chunk))

            df_ok, rejeit = transform(chunk)
            total_rejeit += rejeit

            if df_ok.empty:
                log.warning("Chunk %d completamente rejeitado", i)
                continue

            try:
                n = load_chunk(conn, df_ok)
                total_inseridas += n
                log.info("Chunk %d — %d notificações inseridas", i, n)
            except Exception as exc:
                conn.rollback()
                log.error("Rollback chunk %d: %s", i, exc)
                total_rejeit += len(df_ok)

        _finish_run(conn, run_id, total_linhas, total_inseridas, total_rejeit, "SUCCESS")
        log.info("ETL concluído — inseridas: %d | rejeitadas: %d", total_inseridas, total_rejeit)

    except Exception as exc:
        conn.rollback()
        _finish_run(conn, run_id, total_linhas, total_inseridas, total_rejeit, "FAILED", str(exc))
        log.error("ETL falhou: %s", exc)
        sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    run()
