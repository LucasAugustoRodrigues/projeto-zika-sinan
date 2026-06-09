# Status do Projeto — Zika SINAN 2018–2026

**Atualizado em:** 2026-05-30  
**Referência:** `contexto/Projeto_ Banco de Dados e Análise Estatística Epidemiológica— Zika Vírus (SINAN 2018–2026).pdf`

---

## Checklist de Deliverables

### Deliverable 1 — Modelagem e Carga (ETL)

| Item exigido pelo enunciado | Status | Arquivo |
|---|:---:|---|
| Esquema relacional no PostgreSQL (8 tabelas, FKs, índices) | ✅ | `src/database/ddl/01_init_schema.sql` |
| Script Python de ETL com carga em chunks | ✅ | `src/etl/pipeline_ingestao.py` |
| Log de execução do ETL (`etl_run_log`) | ✅ | tabela `sinan.etl_run_log` |
| **ERD visual (diagrama entidade-relacionamento)** | ❌ | **não existe** |

**O que falta:**  
Nenhum arquivo de diagrama ERD foi criado (`.png`, `.svg`, `.pdf` ou arquivo de ferramenta como dbdiagram.io/DrawIO). O enunciado pede explicitamente "Projetar o esquema relacional (ERD)". O esquema existe no banco e no DDL, mas não há representação visual exportável para entrega.

---

### Deliverable 2 — Funções SQL

| Função | Propósito | Status |
|---|---|:---:|
| `sinan.decode_age(nu_idade_n)` | Converte campo bruto para anos decimais | ✅ |
| `sinan.atraso_notificacao(id_notif)` | Dias entre sintomas e notificação | ✅ |
| `sinan.faixa_etaria(age_years)` | Classifica em 6 faixas etárias | ✅ |
| `sinan.resumo_epidemiologico(uf, ano)` | KPIs por UF e ano | ✅ |
| `sinan.detect_duplicatas()` | Detecta fichas duplicadas | ✅ |
| `sinan.insert_notificacao_validada(...)` | Insert com validações clínicas | ✅ |

**Status: ✅ Completo** — todas as funções exigidas estão implementadas em `src/database/functions/02_functions.sql`.

---

### Deliverable 3 — Triggers

| Item exigido pelo enunciado | Status | Detalhe |
|---|:---:|---|
| Auditoria com snapshot JSONB (before/after) | ✅ | `fn_audit_generico` usa `row_to_json()::JSONB` |
| Auditoria INSERT/UPDATE/DELETE em `evolucao_clinica` | ✅ | `trg_audit_evolucao` |
| Auditoria UPDATE/DELETE em `notificacao` | ✅ | `trg_audit_notificacao` |
| Auditoria INSERT em `notificacao` | ⚠️ | Não coberto pelo trigger (decisão de design: INSERT rastreado via ETL) |
| Validação clínica BEFORE INSERT/UPDATE | ✅ | `trg_valida_clinica` em `evolucao_clinica` |

**Status: ✅ Substancialmente completo** — o snapshot JSONB antes/depois está implementado. A única ressalva é que `trg_audit_notificacao` cobre apenas UPDATE/DELETE, não INSERT; o comentário no código justifica isso com o rastreamento via `etl_run_log`, mas o enunciado especifica "INSERT/UPDATE/DELETE". Se necessário, basta adicionar `OR INSERT` na definição do trigger (2 linhas).

Arquivo: `src/database/triggers/03_triggers.sql`

---

### Deliverable 4 — Views para Dashboard

| View | Propósito | Status |
|---|---|:---:|
| `sinan.vw_casos_zika_analise` | View master para ML (classi_fin=1) | ✅ |
| `sinan.vw_serie_temporal_semanal` | Série semanal por UF — base do Prophet | ✅ |
| `sinan.vw_casos_uf_ano` | Confirmados por UF e ano | ✅ |
| `sinan.vw_piramide_etaria` | Pirâmide etária por faixa e sexo | ✅ |
| `sinan.vw_vigilancia_gestantes` | Gestantes confirmadas | ✅ |
| `sinan.vw_kpi_cards` | KPIs globais (uma linha) | ✅ |

**Status: ✅ Completo** — todas as views exigidas estão implementadas em `src/database/views/04_views.sql`.

---

### Deliverable 5 — Análise Estatística

| Item exigido pelo enunciado | Status | Arquivo |
|---|:---:|---|
| Previsão de casos — Prophet/NeuralProphet | ✅ | `src/models/forecasting_prophet.py` |
| Agrupamento de municípios — K-Means | ✅ | `src/models/clustering_kmeans.py` |
| Sazonalidade (yearly_seasonality no modelo) | ✅ | embutido no NeuralProphet |
| Curva epidêmica por semana/ano (EDA) | ✅ | `notebooks/01_exploratory_analysis.ipynb` §1.2 |
| Distribuição por UF ao longo do tempo (EDA) | ✅ | notebook §1.3 — mapa de calor |
| Pirâmide etária (EDA) | ✅ | notebook §1.4 |
| Vigilância de gestantes e desfechos (EDA) | ✅ | notebook §1.5 |
| **Análise formal de tendência por UF** | ⚠️ | não implementada |
| **Notebook executado com outputs salvos** | ⚠️ | ver nota abaixo sobre Long Path |

**O que falta:**  
O enunciado menciona "tendência por UF". O mapa de calor do notebook mostra a distribuição temporal, mas não há análise formal de tendência (ex: regressão linear por UF, variação percentual ano a ano, ou teste de Mann-Kendall). Isso pode ser adicionado como uma seção extra no notebook ou como script separado.

O notebook existe em `notebooks/01_exploratory_analysis.ipynb` e está estruturado com células autocontidas, mas ainda não foi executado (sem outputs salvos) devido ao problema de Long Path descrito abaixo.

---

## Nota: Problema do Jupyter no Windows com Long Path

**Sintoma:**  
Ao abrir o notebook pelo Jupyter Lab/Notebook no Windows, pode ocorrer `FileNotFoundError` ou falha silenciosa ao criar o kernel, especialmente ao executar células. O caminho completo do arquivo é:

```
C:\Users\Lucas\Faculdade\Pedro_Girotto\Modelagem_E_Estatistica\2bi\projeto\notebooks\01_exploratory_analysis.ipynb
```

Esse caminho tem ~113 caracteres, dentro do limite de 260 do Windows. O problema real costuma ser nos **arquivos temporários do kernel** que o Jupyter cria em subdiretórios com nomes longos (ex: `jupyter/runtime/kernel-<uuid>.json`), que combinados com o perfil do usuário podem superar 260 caracteres.

**Diagnóstico:**  
Executar `jupyter notebook --debug` e verificar se aparece `FileNotFoundError` ou `OSError: [WinError 206]` no log.

**Soluções (em ordem de preferência):**

1. **Habilitar Long Paths no Windows (recomendado):**
   ```
   gpedit.msc → Configuração do Computador → Modelos Administrativos
     → Sistema → Sistema de Arquivos
     → Habilitar caminhos Win32 longos → Habilitado
   ```
   Ou via PowerShell (requer admin):
   ```powershell
   Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1
   ```
   Reiniciar após a alteração.

2. **Usar VS Code com extensão Jupyter:**  
   O VS Code gerencia os kernels de forma diferente e raramente tem esse problema. Abrir o `.ipynb` diretamente no VS Code com a extensão Jupyter instalada.

3. **Criar um junction point para encurtar o caminho:**
   ```powershell
   New-Item -ItemType Junction -Path "C:\zika" -Target "C:\Users\Lucas\Faculdade\Pedro_Girotto\Modelagem_E_Estatistica\2bi\projeto"
   ```
   Depois abrir o notebook via `C:\zika\notebooks\...`

---

## Próximos Passos Priorizados

### 1. Resolver Long Path e executar o notebook (urgente para entrega)
Aplicar uma das soluções acima. Depois:
```powershell
.\venv_prophet\Scripts\activate
$env:PGDATABASE="zika"; $env:PGUSER="postgres"; $env:PGPASSWORD="lucas01"; $env:PGHOST="localhost"; $env:PGPORT="5432"
jupyter lab notebooks\01_exploratory_analysis.ipynb
```
Executar todas as células e salvar com os outputs visíveis — isso é o que o avaliador verá.

### 2. Gerar outputs dos modelos (se ainda não existirem)
```powershell
python main.py --all
```
Verifica que `data/processed/forecast_nacional.csv`, `forecast_plot_nacional.png`, `clustering_municipios.csv` e `clustering_elbow.png` estão presentes.

### 3. Criar o ERD visual — D1 (pendente obrigatório)
Opções:
- **dbdiagram.io** (online, gratuito): colar o DDL, exportar PNG/PDF
- **DBeaver**: conectar ao banco → clicar com botão direito no schema `sinan` → "View Diagram" → exportar
- **pgAdmin 4**: Tools → ERD Tool → adicionar as tabelas do schema `sinan`

O ERD deve mostrar as 8 tabelas com colunas-chave e as foreign keys. Salvar em `docs/ERD_sinan.png` (ou `.pdf`).

### 4. Adicionar INSERT ao trigger de notificação — D3 (2 linhas)
Se o avaliador for criterioso com "INSERT/UPDATE/DELETE":
```sql
-- em src/database/triggers/03_triggers.sql, linha 36-40
DROP TRIGGER IF EXISTS trg_audit_notificacao ON sinan.notificacao;
CREATE TRIGGER trg_audit_notificacao
    AFTER INSERT OR UPDATE OR DELETE   -- adicionar INSERT
    ON sinan.notificacao
    FOR EACH ROW
    EXECUTE FUNCTION sinan.fn_audit_generico();
```

### 5. Adicionar análise de tendência por UF — D5 (opcional mas recomendado)
Seção extra no notebook ou script `src/models/tendencia_uf.py`:
- Calcular variação percentual anual de casos por UF (`vw_casos_uf_ano`)
- Identificar UFs com tendência de crescimento vs. queda
- Visualização: gráfico de linhas normalizadas por UF, ou tabela com taxa de variação média

### 6. Atualizar CLAUDE.md
Marcar D5 como ✅ completo e adicionar o ERD à estrutura de arquivos quando for criado.
