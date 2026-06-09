-- Projeto Zika SINAN 2018-2026
-- Funções auxiliares: decode, classificação, validação e resumo epidemiológico
SET search_path TO sinan, public;


-- converte NU_IDADE_N bruto (ex: 4034 = 34 anos) para anos decimais
CREATE OR REPLACE FUNCTION sinan.decode_age(nu_idade_n SMALLINT)
RETURNS NUMERIC(6,3)
LANGUAGE plpgsql IMMUTABLE STRICT
AS $$
DECLARE
    v_unit  SMALLINT;
    v_value SMALLINT;
BEGIN
    v_unit  := nu_idade_n / 1000;
    v_value := nu_idade_n % 1000;

    RETURN CASE v_unit
        WHEN 4 THEN v_value::NUMERIC
        WHEN 3 THEN ROUND(v_value / 12.0,  3)
        WHEN 2 THEN ROUND(v_value / 365.0, 3)
        WHEN 1 THEN ROUND(v_value / 8760.0, 3)
        ELSE NULL
    END;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$;


-- dias entre início dos sintomas e registro da notificação
CREATE OR REPLACE FUNCTION sinan.atraso_notificacao(p_id_notif BIGINT)
RETURNS INTEGER
LANGUAGE sql STABLE
AS $$
    SELECT (n.dt_notific - lc.dt_sin_pri)::INTEGER
    FROM   sinan.notificacao     n
    JOIN   sinan.localizacao_caso lc USING (id_notif)
    WHERE  n.id_notif   = p_id_notif
      AND  n.dt_notific IS NOT NULL
      AND  lc.dt_sin_pri IS NOT NULL;
$$;


-- classifica age_years nas faixas usadas nas análises epidemiológicas
CREATE OR REPLACE FUNCTION sinan.faixa_etaria(age_years NUMERIC)
RETURNS VARCHAR
LANGUAGE sql IMMUTABLE
AS $$
    SELECT CASE
        WHEN age_years IS NULL   THEN NULL
        WHEN age_years <  1      THEN 'Menor de 1 ano'
        WHEN age_years <  12     THEN 'Criança'
        WHEN age_years <  18     THEN 'Adolescente'
        WHEN age_years <  30     THEN 'Adulto jovem'
        WHEN age_years <  60     THEN 'Adulto'
        ELSE                          'Idoso'
    END;
$$;


-- resumo por UF e ano: confirmados, gestantes, atraso médio e óbitos
CREATE OR REPLACE FUNCTION sinan.resumo_epidemiologico(
    p_uf  SMALLINT,
    p_ano SMALLINT
)
RETURNS TABLE (
    uf                 SMALLINT,
    ano                SMALLINT,
    total_confirmados  BIGINT,
    total_gestantes    BIGINT,
    media_atraso_dias  NUMERIC(6,2),
    obitos             BIGINT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        n.sg_uf_not                                             AS uf,
        n.nu_ano                                                AS ano,
        COUNT(*)                                                AS total_confirmados,
        COUNT(*) FILTER (WHERE p.cs_gestant IN (1,2,3))        AS total_gestantes,
        ROUND(AVG(n.dt_notific - lc.dt_sin_pri)::NUMERIC, 2)   AS media_atraso_dias,
        COUNT(*) FILTER (WHERE ec.evolucao = 2)                 AS obitos
    FROM  sinan.notificacao      n
    JOIN  sinan.evolucao_clinica ec USING (id_notif)
    JOIN  sinan.localizacao_caso lc USING (id_notif)
    JOIN  sinan.paciente         p  ON p.id_paciente = n.id_paciente
    WHERE ec.classi_fin   = 1
      AND n.sg_uf_not     = p_uf
      AND n.nu_ano        = p_ano
    GROUP BY n.sg_uf_not, n.nu_ano;
$$;


-- detecta fichas com mesma combinação chave — possíveis duplicatas do SINAN
CREATE OR REPLACE FUNCTION sinan.detect_duplicatas()
RETURNS TABLE (
    id_notif    BIGINT,
    dt_notific  DATE,
    id_municip  INTEGER,
    cs_sexo     CHAR(1),
    nu_idade_n  SMALLINT,
    dt_sin_pri  DATE,
    total_dupes BIGINT
)
LANGUAGE sql STABLE
AS $$
    WITH grupos AS (
        SELECT
            n.dt_notific,
            n.id_municip,
            p.cs_sexo,
            p.nu_idade_n,
            lc.dt_sin_pri,
            COUNT(*) AS total_dupes
        FROM  sinan.notificacao      n
        JOIN  sinan.paciente         p  ON p.id_paciente = n.id_paciente
        JOIN  sinan.localizacao_caso lc USING (id_notif)
        GROUP BY n.dt_notific, n.id_municip, p.cs_sexo, p.nu_idade_n, lc.dt_sin_pri
        HAVING COUNT(*) > 1
    )
    SELECT
        n.id_notif,
        g.dt_notific,
        g.id_municip,
        g.cs_sexo,
        g.nu_idade_n,
        g.dt_sin_pri,
        g.total_dupes
    FROM  sinan.notificacao      n
    JOIN  sinan.paciente         p  ON p.id_paciente = n.id_paciente
    JOIN  sinan.localizacao_caso lc USING (id_notif)
    JOIN  grupos                 g  ON  g.dt_notific = n.dt_notific
                                    AND g.id_municip = n.id_municip
                                    AND g.cs_sexo    = p.cs_sexo
                                    AND (g.nu_idade_n IS NOT DISTINCT FROM p.nu_idade_n)
                                    AND (g.dt_sin_pri IS NOT DISTINCT FROM lc.dt_sin_pri)
    ORDER BY g.total_dupes DESC, n.id_notif;
$$;


-- insere uma notificação com validações clínicas antes do commit
CREATE OR REPLACE FUNCTION sinan.insert_notificacao_validada(
    p_dt_notific  DATE,
    p_sem_not     SMALLINT,
    p_nu_ano      SMALLINT,
    p_sg_uf_not   SMALLINT,
    p_id_municip  INTEGER,
    p_id_paciente BIGINT,
    p_classi_fin  SMALLINT,
    p_evolucao    SMALLINT,
    p_dt_obito    DATE,
    p_dt_sin_pri  DATE
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_id_notif BIGINT;
BEGIN
    -- sintomas não podem ser posteriores à notificação
    IF p_dt_sin_pri IS NOT NULL AND p_dt_sin_pri > p_dt_notific THEN
        RAISE EXCEPTION
            'dt_sin_pri (%) posterior a dt_notific (%) — dado inválido',
            p_dt_sin_pri, p_dt_notific;
    END IF;

    -- óbito só faz sentido quando evolucao indica morte (2) ou outra ocorrência (3)
    IF p_dt_obito IS NOT NULL AND p_evolucao NOT IN (2, 3) THEN
        RAISE EXCEPTION
            'dt_obito preenchida mas evolucao = % não indica óbito',
            p_evolucao;
    END IF;

    IF p_sem_not NOT BETWEEN 1 AND 53 THEN
        RAISE EXCEPTION
            'sem_not = % fora do intervalo válido (1–53)', p_sem_not;
    END IF;

    INSERT INTO sinan.notificacao
        (dt_notific, sem_not, nu_ano, sg_uf_not, id_municip, id_paciente)
    VALUES
        (p_dt_notific, p_sem_not, p_nu_ano, p_sg_uf_not, p_id_municip, p_id_paciente)
    RETURNING id_notif INTO v_id_notif;

    INSERT INTO sinan.evolucao_clinica (id_notif, classi_fin, evolucao, dt_obito)
    VALUES (v_id_notif, p_classi_fin, p_evolucao, p_dt_obito);

    INSERT INTO sinan.localizacao_caso (id_notif, dt_sin_pri, sem_pri)
    VALUES (
        v_id_notif,
        p_dt_sin_pri,
        EXTRACT(WEEK FROM p_dt_sin_pri)::SMALLINT
    );

    RETURN v_id_notif;
END;
$$;
