-- Projeto Zika SINAN 2018-2026
-- Triggers: auditoria em notificacao e evolucao_clinica + validação clínica
SET search_path TO sinan, public;


-- função compartilhada de auditoria — loga qualquer DML com snapshot JSON
CREATE OR REPLACE FUNCTION sinan.fn_audit_generico()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO sinan.audit_log
        (tabela, operacao, id_notif, snapshot_before, snapshot_after)
    VALUES (
        TG_TABLE_NAME,
        TG_OP,
        CASE TG_OP
            WHEN 'DELETE' THEN (row_to_json(OLD) ->> 'id_notif')::BIGINT
            ELSE               (row_to_json(NEW) ->> 'id_notif')::BIGINT
        END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL
             ELSE row_to_json(OLD)::JSONB
        END,
        CASE WHEN TG_OP = 'DELETE' THEN NULL
             ELSE row_to_json(NEW)::JSONB
        END
    );

    RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END;
$$;


-- auditoria em notificacao — INSERT/UPDATE/DELETE
DROP TRIGGER IF EXISTS trg_audit_notificacao ON sinan.notificacao;
CREATE TRIGGER trg_audit_notificacao
    AFTER INSERT OR UPDATE OR DELETE
    ON sinan.notificacao
    FOR EACH ROW
    EXECUTE FUNCTION sinan.fn_audit_generico();


-- auditoria em evolucao_clinica — captura mudanças de classi_fin inclusive
DROP TRIGGER IF EXISTS trg_audit_evolucao ON sinan.evolucao_clinica;
CREATE TRIGGER trg_audit_evolucao
    AFTER INSERT OR UPDATE OR DELETE
    ON sinan.evolucao_clinica
    FOR EACH ROW
    EXECUTE FUNCTION sinan.fn_audit_generico();


-- validação clínica: corrige dt_obito incoerente e criterio em descartados
CREATE OR REPLACE FUNCTION sinan.fn_valida_clinica()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    -- óbito preenchido sem evolucao de morte: força NULL e avisa
    IF NEW.evolucao NOT IN (2, 3) AND NEW.dt_obito IS NOT NULL THEN
        RAISE WARNING
            'id_notif %: dt_obito ignorada — evolucao (%) não indica óbito',
            NEW.id_notif, NEW.evolucao;
        NEW.dt_obito := NULL;
    END IF;

    -- descartado não deve ter criterio de confirmação
    IF NEW.classi_fin = 0 THEN
        NEW.criterio := NULL;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_valida_clinica ON sinan.evolucao_clinica;
CREATE TRIGGER trg_valida_clinica
    BEFORE INSERT OR UPDATE
    ON sinan.evolucao_clinica
    FOR EACH ROW
    EXECUTE FUNCTION sinan.fn_valida_clinica();
