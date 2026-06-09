# Projeto Zika SINAN 2018–2026

Banco de dados epidemiológico + pipeline ETL + modelos de previsão (NeuralProphet) e clustering (K-Means) sobre os dados de Zika Vírus do SINAN.

## Como Executar o Projeto

### Requisito de Ambiente

Use **Python 3.11**. Versões mais recentes (3.12+) têm incompatibilidades com NeuralProphet/PyTorch no Windows.

### 1. Configuração do Ambiente Virtual

```powershell
py -3.11 -m venv venv_prophet
.\venv_prophet\Scripts\activate
pip install -r requirements.txt
```

### 2. Variáveis de Ambiente

Defina as variáveis antes de rodar qualquer script. No PowerShell:

```powershell
$env:PGDATABASE="zika"
$env:PGUSER="postgres"
$env:PGPASSWORD="sua_senha"
$env:PGHOST="localhost"
$env:PGPORT="5432"
```

### 3. Ordem de Execução

**Passo 1 — Banco de dados** (executar uma vez, na ordem):

```
psql -U postgres -d zika -f src/database/ddl/01_init_schema.sql
psql -U postgres -d zika -f src/database/functions/02_functions.sql
psql -U postgres -d zika -f src/database/triggers/03_triggers.sql
psql -U postgres -d zika -f src/database/views/04_views.sql
```

**Passo 2 — ETL** (carga do CSV no banco):

```powershell
python -m src.etl.pipeline_ingestao
```

**Passo 3 — Previsão com NeuralProphet:**

```powershell
python -m src.models.forecasting_prophet
```

**Passo 4 — Clustering K-Means:**

```powershell
python -m src.models.clustering_kmeans
```

Os passos 2, 3 e 4 usam o mesmo ambiente virtual — não é necessário trocar de ambiente entre eles.

Os arquivos gerados pelos modelos são salvos em `data/processed/`.

---

## Replicando o Projeto

### Pré-requisitos

- **Python 3.11** — versões 3.12+ têm incompatibilidades com NeuralProphet/PyTorch no Windows
- **PostgreSQL 15+** — instalar com o stack padrão (pgAdmin 4 incluso)

### 1. Obter o CSV de dados

O arquivo `ZIKA_BR_2018_2026_UNIFICADO.csv` **não está no repositório** por causa do tamanho.
Baixe em: **[Google Drive](https://drive.google.com/file/d/1CqIE2XTIvZz3Ty33lQmuXJOHIuadTXiC/view)** e coloque em `data/raw/`:

```
projeto/
└── data/
    └── raw/
        └── ZIKA_BR_2018_2026_UNIFICADO.csv
```

### 2. Criar o banco de dados

No pgAdmin 4, clique com o botão direito em **Databases → Create → Database**, digite `zika` e confirme.

### 3. Executar os SQLs

No pgAdmin 4, abra o **Query Tool** conectado ao banco `zika` e execute os arquivos abaixo na ordem — cada um depende do anterior:

1. `src/database/ddl/01_init_schema.sql`
2. `src/database/functions/02_functions.sql`
3. `src/database/triggers/03_triggers.sql`
4. `src/database/views/04_views.sql`

Para abrir cada arquivo no Query Tool: **File → Open File**, selecione o `.sql` e pressione **F5** para executar.

### 4. Criar o ambiente virtual e instalar dependências

```powershell
py -3.11 -m venv venv_prophet
.\venv_prophet\Scripts\activate
pip install -r requirements.txt
```

> A instalação pode levar alguns minutos por causa do PyTorch.

### 5. Rodar o ETL

Com o venv ativo, defina a senha do banco e execute a ingestão:

```powershell
$env:PGPASSWORD="sua_senha"
python -m src.etl.pipeline_ingestao
```

### 6. Rodar os modelos

```powershell
python main.py --models
```

Os arquivos de saída são salvos em `data/processed/`.
