-- Projeto Zika SINAN 2018-2026
-- Views analíticas: ML, série temporal, KPIs e vigilância
SET search_path TO sinan, public;


-- view master usada nos modelos de ML — apenas confirmados (classi_fin = 1)
CREATE OR REPLACE VIEW sinan.vw_casos_zika_analise AS
SELECT
    n.id_notif,
    n.arquivo_origem,
    n.nu_ano,
    n.sem_not,
    n.dt_notific,
    n.sg_uf_not,
    n.id_municip,

    p.cs_sexo,
    p.age_years,
    p.cs_raca,
    p.cs_escol_n,
    p.cs_gestant,
    p.id_ocupa_n,
    sinan.faixa_etaria(p.age_years)             AS faixa_etaria,

    ec.classi_fin,
    ec.criterio,
    ec.evolucao,
    ec.dt_obito,
    ec.doenca_tra,

    lc.dt_sin_pri,
    lc.sem_pri,
    lc.sg_uf                                    AS sg_uf_res,
    lc.id_mn_resi,
    lc.tpautocto,

    du.sigla                                    AS sigla_uf_res,
    dm.nome_municipio                           AS nome_municipio_res,

    (n.dt_notific - lc.dt_sin_pri)::INTEGER     AS atraso_notif_dias,
    (p.cs_gestant IN (1,2,3))                   AS flag_gestante,
    (ec.evolucao = 2)                           AS flag_obito
FROM  sinan.notificacao      n
JOIN  sinan.paciente         p  ON p.id_paciente = n.id_paciente
JOIN  sinan.evolucao_clinica ec USING (id_notif)
JOIN  sinan.localizacao_caso lc USING (id_notif)
LEFT JOIN sinan.dim_uf       du ON du.sg_uf = lc.sg_uf
LEFT JOIN sinan.dim_municipio dm ON dm.id_municipio = lc.id_mn_resi
WHERE ec.classi_fin = 1;


-- série temporal semanal por UF de residência — base para Prophet
CREATE OR REPLACE VIEW sinan.vw_serie_temporal_semanal AS
SELECT
    n.nu_ano,
    lc.sem_pri,
    lc.sg_uf,
    du.sigla  AS sigla_uf,
    COUNT(*)  AS total_casos
FROM  sinan.notificacao      n
JOIN  sinan.evolucao_clinica ec USING (id_notif)
JOIN  sinan.localizacao_caso lc USING (id_notif)
LEFT JOIN sinan.dim_uf       du ON du.sg_uf = lc.sg_uf
WHERE ec.classi_fin  = 1
  AND lc.dt_sin_pri IS NOT NULL
  AND lc.sem_pri    IS NOT NULL
GROUP BY n.nu_ano, lc.sem_pri, lc.sg_uf, du.sigla
ORDER BY n.nu_ano, lc.sem_pri, lc.sg_uf;


-- confirmados por UF e ano com gestantes e óbitos — base para clustering
CREATE OR REPLACE VIEW sinan.vw_casos_uf_ano AS
SELECT
    du.sg_uf,
    du.sigla    AS sigla_uf,
    du.nome_uf,
    du.regiao,
    n.nu_ano,
    COUNT(*)                                            AS total_casos,
    COUNT(*) FILTER (WHERE p.cs_gestant IN (1,2,3))    AS total_gestantes,
    COUNT(*) FILTER (WHERE ec.evolucao = 2)             AS total_obitos
FROM  sinan.notificacao      n
JOIN  sinan.evolucao_clinica ec USING (id_notif)
JOIN  sinan.paciente         p  ON p.id_paciente = n.id_paciente
JOIN  sinan.dim_uf           du ON du.sg_uf = n.sg_uf_not
WHERE ec.classi_fin = 1
GROUP BY du.sg_uf, du.sigla, du.nome_uf, du.regiao, n.nu_ano
ORDER BY n.nu_ano, du.sg_uf;


-- pirâmide etária dos casos confirmados por sexo
CREATE OR REPLACE VIEW sinan.vw_piramide_etaria AS
SELECT
    sinan.faixa_etaria(p.age_years) AS faixa_etaria,
    p.cs_sexo,
    COUNT(*)                        AS total
FROM  sinan.notificacao      n
JOIN  sinan.paciente         p  ON p.id_paciente = n.id_paciente
JOIN  sinan.evolucao_clinica ec USING (id_notif)
WHERE ec.classi_fin = 1
  AND p.cs_sexo IN ('M', 'F')
  AND p.age_years IS NOT NULL
GROUP BY sinan.faixa_etaria(p.age_years), p.cs_sexo
ORDER BY faixa_etaria, p.cs_sexo;


-- vigilância de gestantes confirmadas — relevante para microcefalia
CREATE OR REPLACE VIEW sinan.vw_vigilancia_gestantes AS
SELECT
    n.id_notif,
    n.dt_notific,
    lc.dt_sin_pri,
    lc.sg_uf,
    du.sigla    AS sigla_uf,
    lc.id_mn_resi,
    p.cs_gestant,
    p.age_years,
    ec.evolucao,
    (ec.evolucao = 2) AS flag_obito
FROM  sinan.notificacao      n
JOIN  sinan.paciente         p  ON p.id_paciente = n.id_paciente
JOIN  sinan.evolucao_clinica ec USING (id_notif)
JOIN  sinan.localizacao_caso lc USING (id_notif)
LEFT JOIN sinan.dim_uf       du ON du.sg_uf = lc.sg_uf
WHERE ec.classi_fin     = 1
  AND p.cs_gestant IN (1, 2, 3)
ORDER BY lc.dt_sin_pri DESC;


-- KPIs globais do projeto — uma linha com os principais indicadores
CREATE OR REPLACE VIEW sinan.vw_kpi_cards AS
SELECT
    COUNT(*) FILTER (WHERE ec.classi_fin = 1)
        AS total_confirmados,

    COUNT(*) FILTER (WHERE ec.classi_fin = 1 AND p.cs_gestant IN (1,2,3))
        AS total_gestantes_confirmadas,

    COUNT(*) FILTER (WHERE ec.classi_fin = 1 AND ec.evolucao = 2)
        AS total_obitos,

    ROUND(
        100.0 * COUNT(*) FILTER (WHERE ec.classi_fin = 1 AND lc.tpautocto = 1)
              / NULLIF(COUNT(*) FILTER (WHERE ec.classi_fin = 1), 0),
        2
    )   AS perc_autoctone,

    ROUND(
        AVG(
            CASE
                WHEN ec.classi_fin = 1
                 AND n.dt_notific  IS NOT NULL
                 AND lc.dt_sin_pri IS NOT NULL
                THEN (n.dt_notific - lc.dt_sin_pri)::NUMERIC
            END
        ),
        2
    )   AS media_atraso_dias,

    MIN(n.nu_ano)::TEXT || ' – ' || MAX(n.nu_ano)::TEXT
        AS anos_cobertura

FROM  sinan.notificacao      n
JOIN  sinan.evolucao_clinica ec USING (id_notif)
JOIN  sinan.paciente         p  ON p.id_paciente = n.id_paciente
JOIN  sinan.localizacao_caso lc USING (id_notif);
