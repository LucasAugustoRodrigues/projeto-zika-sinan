# CLAUDE.md — Projeto Zika SINAN 2018–2026

Arquivo de contexto para o Claude Code. Leia este arquivo no início de cada sessão
para retomar o projeto sem perder contexto.

---

## 1. Descrição do Projeto

Projeto acadêmico de modelagem e estatística (2º bimestre). Constrói um pipeline
completo de dados epidemiológicos sobre o Zika Vírus no Brasil, usando os registros
do SINAN (Sistema de Informação de Agravos de Notificação) de 2018 a 2026.

**Tecnologias:** Python 3.11, PostgreSQL 15+, pandas, psycopg2, SQLAlchemy,
NeuralProphet, scikit-learn, matplotlib.

**Fonte dos dados:** `data/raw/ZIKA_BR_2018_2026_UNIFICADO.csv`
(arquivo unificado gerado pelo professor Pedro Girotto a partir dos DBC do DATASUS).

---

## 2. Status dos Deliverables

### Deliverable 1 — Banco de Dados e ETL ✅ Concluído

- DDL completo em `src/database/ddl/01_init_schema.sql`:
  schema `sinan` com 8 tabelas (dim_uf, dim_municipio, dim_unidade_saude,
  paciente, notificacao, evolucao_clinica, localizacao_caso, audit_log, etl_run_log),
  constraints, FKs e 9 índices.
- Pipeline ETL em `src/etl/pipeline_ingestao.py`:
  lê o CSV em chunks de 10.000 linhas, carrega dimensões primeiro,
  respeita a ordem de FKs e registra execução em `etl_run_log`.
- **ERD visual salvo em `docs/ERD_sinan.png`** ✅

### Deliverable 2 — Funções SQL ✅ Concluído

Arquivo: `src/database/functions/02_functions.sql`

| Função | O que faz |
|---|---|
| `sinan.decode_age(nu_idade_n)` | Converte campo bruto SINAN para anos decimais |
| `sinan.atraso_notificacao(id_notif)` | Dias entre dt_sin_pri e dt_notific |
| `sinan.faixa_etaria(age_years)` | Classifica em 6 faixas etárias |
| `sinan.resumo_epidemiologico(uf, ano)` | Retorna TABLE com KPIs por UF/ano |
| `sinan.detect_duplicatas()` | Detecta fichas duplicadas por chave combinada |
| `sinan.insert_notificacao_validada(...)` | Insert com validações clínicas antes do commit |

### Deliverable 3 — Triggers ✅ Concluído

Arquivo: `src/database/triggers/03_triggers.sql`

- `trg_audit_notificacao` — auditoria de **INSERT OR UPDATE OR DELETE** em `notificacao`
- `trg_audit_evolucao` — auditoria de INSERT/UPDATE/DELETE em `evolucao_clinica`
- `trg_valida_clinica` — BEFORE INSERT/UPDATE em `evolucao_clinica`:
  força `dt_obito = NULL` se evolucao não indica óbito; zera `criterio` em descartados.

### Deliverable 4 — Views Analíticas ✅ Concluído

Arquivo: `src/database/views/04_views.sql`

| View | Uso |
|---|---|
| `sinan.vw_casos_zika_analise` | View master para ML — apenas classi_fin=1 |
| `sinan.vw_serie_temporal_semanal` | Série semanal por UF — base do Prophet |
| `sinan.vw_casos_uf_ano` | Confirmados por UF e ano — base do clustering |
| `sinan.vw_piramide_etaria` | Pirâmide etária por faixa e sexo |
| `sinan.vw_vigilancia_gestantes` | Gestantes confirmadas — filtro cs_gestant IN (1,2,3) |
| `sinan.vw_kpi_cards` | Uma linha com KPIs globais do projeto |

### Deliverable 5 — Modelos Estatísticos ✅ Concluído (scripts + notebook)

- **NeuralProphet** (`src/models/forecasting_prophet.py`):
  lê `vw_serie_temporal_semanal`, agrega em série nacional, treina NeuralProphet
  com `yearly_seasonality=True` e `quantiles=[0.025, 0.975]`, prevê 52 semanas.
  Saída: `data/processed/forecast_nacional.csv` e `forecast_plot_nacional.png`.

- **K-Means** (`src/models/clustering_kmeans.py`):
  agrega municípios por 5 features (total_casos, perc_gestantes, perc_obitos,
  media_atraso_dias, media_age_anos), normaliza com StandardScaler, escolhe k
  pelo silhouette com fallback para k=4 se cluster menor < 5% do total.
  Saída: `data/processed/clustering_municipios.csv` e `clustering_elbow.png`.

- **EDA** (`notebooks/01_exploratory_analysis.ipynb`):
  implementado com 4 seções autocontidas (Curva Epidêmica §1.2, Mapa de Calor UF×Ano §1.3,
  Pirâmide Etária §1.4, Gestantes e Óbitos §1.5). **Precisa ser executado para gerar outputs.**

### Orquestrador ✅ Concluído

`main.py` — argparse com `--etl`, `--models`, `--all`; executa ETL → NeuralProphet → K-Means
em sequência com log de tempo e exit code 1 em falha.

### Pendente para entrega

- **Executar o notebook** e salvar com outputs visíveis (avaliador verá as células executadas).
- **Análise formal de tendência por UF** — opcional, mencionada no enunciado.

---

## 3. Estrutura de Arquivos

```
projeto/
├── data/
│   ├── raw/                          # CSV fonte (não versionado pelo .gitignore)
│   └── processed/                    # Outputs dos modelos (não versionado)
├── docs/
│   ├── CLAUDE.md                     # Este arquivo
│   ├── STATUS_PROJETO.md             # Checklist detalhado de deliverables
│   └── ERD_sinan.png                 # Diagrama entidade-relacionamento (D1)
├── notebooks/
│   └── 01_exploratory_analysis.ipynb # EDA — implementado, precisa ser executado
├── src/
│   ├── database/
│   │   ├── ddl/01_init_schema.sql    # Schema completo com 8 tabelas
│   │   ├── functions/02_functions.sql
│   │   ├── triggers/03_triggers.sql  # INSERT OR UPDATE OR DELETE em notificacao
│   │   └── views/04_views.sql
│   ├── etl/
│   │   ├── __init__.py
│   │   └── pipeline_ingestao.py      # ETL principal
│   └── models/
│       ├── __init__.py
│       ├── forecasting_prophet.py    # NeuralProphet (série semanal nacional)
│       └── clustering_kmeans.py      # K-Means por município
├── .gitignore
├── README.md
├── requirements.txt
├── main.py                           # Orquestrador completo (--etl/--models/--all)
└── venv_prophet/                     # Não versionado
```

---

## 4. Configuração do Ambiente

**Python:** 3.11 obrigatório (NeuralProphet/PyTorch incompatível com 3.12+ no Windows).

**Ambiente virtual:**
```powershell
py -3.11 -m venv venv_prophet
.\venv_prophet\Scripts\activate
pip install -r requirements.txt
```

**Banco de dados:**
- SGBD: PostgreSQL 15+
- Database: `zika`
- Schema principal: `sinan`
- Usuário padrão nos scripts: `postgres` / senha definida via env var

**Variáveis de ambiente (PowerShell):**
```powershell
$env:PGDATABASE="zika"
$env:PGUSER="postgres"
$env:PGPASSWORD="sua_senha"
$env:PGHOST="localhost"
$env:PGPORT="5432"
```

Os defaults dos scripts assumem essas variáveis. A senha `lucas01` está hardcoded
como fallback em `DB_PARAMS`/`DB_URL` — trocar antes de versionar.

---

## 5. Problemas Conhecidos e Soluções Aplicadas

### DOENCA_TRA com valores 0 e 9
**Problema:** CHECK constraint aceita apenas 1, 2 ou NULL. CSV tinha valores 0 (sem doença) e 9 (ignorado).
**Solução:** `_nullable_int(df["DOENCA_TRA"], {0, 9})` em `transform()` do ETL.

### Semana 53 no ISO week
**Problema:** `pd.to_datetime(..., format="%G-%V-%u")` lança ValueError para semana 53
em anos que não têm essa semana (ex: 2025).
**Solução:** filtrar `sem_pri.between(1, 52)` antes do `to_datetime`, mais `errors="coerce"` + `dropna`.

### Stan crash no Windows (código 3221225785)
**Problema:** Prophet original usava Stan/cmdstanpy como otimizador, que crashava
no Windows com exit code 3221225785 (access violation).
**Solução:** migrar para NeuralProphet (usa PyTorch, sem Stan).

### NeuralProphet — AttributeError: 'Series' object has no attribute 'view'
**Problema:** incompatibilidade do NeuralProphet com Pandas 2.1+ no tratamento
interno de Series como tensores PyTorch.
**Solução:**
```python
serie["ds"] = pd.to_datetime(serie["ds"])
serie = serie.reset_index(drop=True)
m.fit(serie, freq="W-MON")   # âncora explícita na segunda-feira
```

### pd.read_sql com parâmetros nomeados (:nome)
**Problema:** Pandas 2.1 não suporta a sintaxe `:nome` em queries SQL passadas
diretamente como string para `pd.read_sql`.
**Solução:** constante hardcoded diretamente na query (`HAVING COUNT(*) >= 10`).

### K-Means k=2 com clusters desbalanceados
**Problema:** silhouette score favorecia k=2 quando havia outliers extremos,
gerando um cluster com 2 municípios e outro com 425.
**Solução:** `_validate_k()` — se menor cluster < 5% do total, usa `K_DEFAULT=4`.

### Jupyter no Windows com Long Path
**Problema:** kernel do Jupyter pode falhar em criar arquivos temporários quando
o caminho combinado (perfil + runtime) ultrapassa 260 caracteres.
**Solução recomendada:** abrir o `.ipynb` diretamente no VS Code com extensão Jupyter.
Alternativa: `New-Item -ItemType Junction -Path "C:\zika" -Target "<caminho completo>"`

---

## 6. Próximos Passos para Entrega

1. **Executar o notebook e salvar com outputs** (único pendente obrigatório):
   ```powershell
   .\venv_prophet\Scripts\activate
   $env:PGDATABASE="zika"; $env:PGUSER="postgres"; $env:PGPASSWORD="lucas01"; $env:PGHOST="localhost"; $env:PGPORT="5432"
   # Abrir notebooks\01_exploratory_analysis.ipynb no VS Code e executar todas as células
   ```

2. **Aplicar o trigger atualizado no banco** (INSERT adicionado ao trg_audit_notificacao):
   ```sql
   -- rodar no pgAdmin ou psql
   DROP TRIGGER IF EXISTS trg_audit_notificacao ON sinan.notificacao;
   CREATE TRIGGER trg_audit_notificacao
       AFTER INSERT OR UPDATE OR DELETE
       ON sinan.notificacao
       FOR EACH ROW
       EXECUTE FUNCTION sinan.fn_audit_generico();
   ```

3. **Gerar outputs dos modelos** (se ainda não existirem em `data/processed/`):
   ```powershell
   python main.py --all
   ```

4. **Análise de tendência por UF** — opcional, seção extra no notebook ou script separado.

---

## 7. Comandos Úteis para Retomar

```powershell
# ativar ambiente
.\venv_prophet\Scripts\activate

# definir variáveis (ajustar senha)
$env:PGDATABASE="zika"; $env:PGUSER="postgres"; $env:PGPASSWORD="lucas01"; $env:PGHOST="localhost"; $env:PGPORT="5432"

# rodar pipeline completo
python main.py --all

# rodar ETL separado
python -m src.etl.pipeline_ingestao

# rodar modelos separados
python -m src.models.forecasting_prophet
python -m src.models.clustering_kmeans

# aplicar SQLs no banco (ordem obrigatória)
psql -U postgres -d zika -f src/database/ddl/01_init_schema.sql
psql -U postgres -d zika -f src/database/functions/02_functions.sql
psql -U postgres -d zika -f src/database/triggers/03_triggers.sql
psql -U postgres -d zika -f src/database/views/04_views.sql

# verificar logs de execução do ETL
psql -U postgres -d zika -c "SELECT * FROM sinan.etl_run_log ORDER BY id DESC LIMIT 5;"

# checar contagem de registros por tabela
psql -U postgres -d zika -c "
  SELECT 'notificacao' AS tabela, COUNT(*) FROM sinan.notificacao
  UNION ALL
  SELECT 'paciente',     COUNT(*) FROM sinan.paciente
  UNION ALL
  SELECT 'evolucao',     COUNT(*) FROM sinan.evolucao_clinica;"
```
