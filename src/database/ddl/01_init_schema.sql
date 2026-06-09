-- Projeto Zika SINAN 2018-2026
-- DDL principal -- schema sinan + tabelas + índices
CREATE SCHEMA IF NOT EXISTS sinan;
SET search_path TO sinan, public;
-- UFs do Brasil (código IBGE 2 dígitos)
CREATE TABLE IF NOT EXISTS sinan.dim_uf (
    sg_uf       SMALLINT    NOT NULL,
    sigla       CHAR(2)     NOT NULL,
    nome_uf     VARCHAR(60) NOT NULL,
    regiao      VARCHAR(20) NOT NULL CHECK (regiao IN ('Norte','Nordeste','Centro-Oeste','Sudeste','Sul')),
    CONSTRAINT pk_dim_uf PRIMARY KEY (sg_uf)
);
-- Municípios (código IBGE 6/7 dígitos)
CREATE TABLE IF NOT EXISTS sinan.dim_municipio (
    id_municipio    INTEGER         NOT NULL,
    nome_municipio  VARCHAR(100)    NOT NULL,
    sg_uf           SMALLINT        NOT NULL,
    capital         BOOLEAN         NOT NULL DEFAULT FALSE,
    CONSTRAINT pk_dim_municipio PRIMARY KEY (id_municipio),
    CONSTRAINT fk_municipio_uf  FOREIGN KEY (sg_uf)
        REFERENCES sinan.dim_uf (sg_uf)
        ON UPDATE CASCADE ON DELETE RESTRICT
);
-- Unidades de saúde notificadoras (CNES)
CREATE TABLE IF NOT EXISTS sinan.dim_unidade_saude (
    id_unidade  INTEGER     NOT NULL,
    tp_uninot   SMALLINT,
    sg_uf_not   SMALLINT,
    CONSTRAINT pk_dim_unidade   PRIMARY KEY (id_unidade),
    CONSTRAINT fk_unidade_uf    FOREIGN KEY (sg_uf_not)
        REFERENCES sinan.dim_uf (sg_uf)
        ON UPDATE CASCADE ON DELETE SET NULL
);
-- Dados do paciente separados para não misturar com dados da notificação
CREATE TABLE IF NOT EXISTS sinan.paciente (
    id_paciente BIGSERIAL   NOT NULL,
    cs_sexo     CHAR(1)     CHECK (cs_sexo IN ('M','F','I')),
    -- nu_idade_n original do SINAN ex: 4025 = 25 anos, 3006 = 6 meses
    nu_idade_n  SMALLINT,
    -- primeiro dígito indica unidade: 1=horas 2=dias 3=meses 4=anos
    age_unit    SMALLINT    CHECK (age_unit IN (1,2,3,4)),
    age_value   SMALLINT    CHECK (age_value >= 0),
    -- convertido pra anos decimais no ETL, usado nas análises
    age_years   NUMERIC(6,3),
    ano_nasc    SMALLINT,
    -- código 9 (ignorado) vira NULL no ETL, nunca 0
    cs_raca     SMALLINT    CHECK (cs_raca IN (1,2,3,4,5) OR cs_raca IS NULL),
    cs_escol_n  SMALLINT    CHECK (cs_escol_n BETWEEN 0 AND 10 OR cs_escol_n IS NULL),
    id_ocupa_n  INTEGER,
    cs_gestant  SMALLINT    CHECK (cs_gestant IN (1,2,3,4,5,6) OR cs_gestant IS NULL),
    CONSTRAINT pk_paciente PRIMARY KEY (id_paciente)
);
-- Tabela central -- cada linha é uma ficha de notificação
CREATE TABLE IF NOT EXISTS sinan.notificacao (
    id_notif        BIGSERIAL   NOT NULL,
    arquivo_origem  VARCHAR(30),            -- ex: ZIKABR18.dbc
    ano_arquivo     SMALLINT,
    tp_not          SMALLINT    NOT NULL DEFAULT 2,
    id_agravo       VARCHAR(10),            -- CID-10: A92. ou A928
    dt_notific      DATE        NOT NULL,
    sem_not         SMALLINT    NOT NULL CHECK (sem_not BETWEEN 1 AND 53),
    nu_ano          SMALLINT    NOT NULL,
    sg_uf_not       SMALLINT    NOT NULL,
    id_municip      INTEGER     NOT NULL,
    id_regiona      INTEGER,
    id_unidade      INTEGER,
    id_paciente     BIGINT      NOT NULL,
    dt_invest       DATE,
    dt_digita       DATE,
    CONSTRAINT pk_notificacao       PRIMARY KEY (id_notif),
    CONSTRAINT fk_notif_uf_not      FOREIGN KEY (sg_uf_not)
        REFERENCES sinan.dim_uf (sg_uf)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_notif_municipio   FOREIGN KEY (id_municip)
        REFERENCES sinan.dim_municipio (id_municipio)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_notif_unidade     FOREIGN KEY (id_unidade)
        REFERENCES sinan.dim_unidade_saude (id_unidade)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_notif_paciente    FOREIGN KEY (id_paciente)
        REFERENCES sinan.paciente (id_paciente)
        ON UPDATE CASCADE ON DELETE RESTRICT
);
-- Classificação e evolução clínica -- 1:1 com notificacao
-- atenção: classi_fin = 1 é o filtro obrigatório pra qualquer análise confirmada
CREATE TABLE IF NOT EXISTS sinan.evolucao_clinica (
    id_notif    BIGINT  NOT NULL,
    -- 0=descartado 1=confirmado 2=em investigação 8=inconclusivo
    classi_fin  SMALLINT CHECK (classi_fin IN (0,1,2,8) OR classi_fin IS NULL),
    -- 1=laboratorial 2=clínico-epidemiológico
    criterio    SMALLINT CHECK (criterio IN (0,1,2) OR criterio IS NULL),
    -- código 9 vira NULL
    evolucao    SMALLINT CHECK (evolucao IN (0,1,2,3) OR evolucao IS NULL),
    -- dt_obito só faz sentido quando evolucao = 2 ou 3 (validado no trigger)
    dt_obito    DATE,
    dt_encerra  DATE,
    doenca_tra  SMALLINT CHECK (doenca_tra IN (1,2) OR doenca_tra IS NULL),
    nduplic_n   SMALLINT,
    in_vincula  SMALLINT,
    cs_flxret   SMALLINT,
    flxrecebi   SMALLINT,
    tp_sistema  SMALLINT,
    CONSTRAINT pk_evolucao_clinica  PRIMARY KEY (id_notif),
    CONSTRAINT fk_evolucao_notif    FOREIGN KEY (id_notif)
        REFERENCES sinan.notificacao (id_notif)
        ON UPDATE CASCADE ON DELETE CASCADE
);
-- Localização do caso -- três locais distintos que o SINAN registra separado
-- notificação fica em notificacao, aqui ficam residência e infecção
CREATE TABLE IF NOT EXISTS sinan.localizacao_caso (
    id_notif    BIGINT  NOT NULL,
    -- usar dt_sin_pri pra curvas epidêmicas, não dt_notific
    dt_sin_pri  DATE,
    sem_pri     SMALLINT CHECK (sem_pri BETWEEN 1 AND 53 OR sem_pri IS NULL),
    -- onde o paciente mora
    sg_uf       SMALLINT,
    id_mn_resi  INTEGER,
    id_rg_resi  INTEGER,
    id_pais     INTEGER DEFAULT 1,
    -- onde provavelmente pegou o vírus
    tpautocto   SMALLINT CHECK (tpautocto IN (1,2,3) OR tpautocto IS NULL),
    coufinf     SMALLINT,
    comuninf    INTEGER,
    copaisinf   INTEGER,
    cs_suspeit  SMALLINT,
    CONSTRAINT pk_localizacao_caso  PRIMARY KEY (id_notif),
    CONSTRAINT fk_local_notif       FOREIGN KEY (id_notif)
        REFERENCES sinan.notificacao (id_notif)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_local_uf_res      FOREIGN KEY (sg_uf)
        REFERENCES sinan.dim_uf (sg_uf)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_local_municipio   FOREIGN KEY (id_mn_resi)
        REFERENCES sinan.dim_municipio (id_municipio)
        ON UPDATE CASCADE ON DELETE RESTRICT
);
-- audit_log sem FK pra sobreviver a deletes -- populado pelos triggers depois
CREATE TABLE IF NOT EXISTS sinan.audit_log (
    id              BIGSERIAL   NOT NULL,
    tabela          VARCHAR(60) NOT NULL,
    operacao        CHAR(6)     NOT NULL CHECK (operacao IN ('INSERT','UPDATE','DELETE')),
    id_notif        BIGINT,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by      VARCHAR(100) NOT NULL DEFAULT CURRENT_USER,
    snapshot_before JSONB,
    snapshot_after  JSONB,
    CONSTRAINT pk_audit_log PRIMARY KEY (id)
);
-- controle de execução do ETL
CREATE TABLE IF NOT EXISTS sinan.etl_run_log (
    id                  SERIAL      NOT NULL,
    arquivo_origem      VARCHAR(60) NOT NULL,
    iniciado_em         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finalizado_em       TIMESTAMPTZ,
    linhas_lidas        INTEGER,
    linhas_inseridas    INTEGER,
    linhas_rejeitadas   INTEGER,
    status              VARCHAR(20) NOT NULL DEFAULT 'RUNNING'
        CHECK (status IN ('RUNNING','SUCCESS','FAILED')),
    detalhes_erro       TEXT,
    CONSTRAINT pk_etl_run_log PRIMARY KEY (id)
);
-- índices de performance
CREATE INDEX IF NOT EXISTS idx_notif_classi
    ON sinan.evolucao_clinica (classi_fin);
-- partial index pra queries de casos confirmados (classi_fin = 1 aparece em tudo)
CREATE INDEX IF NOT EXISTS idx_confirmed
    ON sinan.evolucao_clinica (id_notif)
    WHERE classi_fin = 1;
CREATE INDEX IF NOT EXISTS idx_notif_dt_sin
    ON sinan.localizacao_caso (dt_sin_pri);
CREATE INDEX IF NOT EXISTS idx_notif_uf_res
    ON sinan.localizacao_caso (sg_uf);
CREATE INDEX IF NOT EXISTS idx_notif_municipio
    ON sinan.notificacao (id_municip);
CREATE INDEX IF NOT EXISTS idx_notif_ano_sem
    ON sinan.notificacao (nu_ano, sem_not);
CREATE INDEX IF NOT EXISTS idx_localizacao_sem_pri
    ON sinan.localizacao_caso (sem_pri, sg_uf);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts
    ON sinan.audit_log (tabela, changed_at DESC);
-- GIN pra quando precisar fazer query dentro do JSONB do audit_log
CREATE INDEX IF NOT EXISTS idx_audit_snapshot_gin
    ON sinan.audit_log USING GIN (snapshot_after);
