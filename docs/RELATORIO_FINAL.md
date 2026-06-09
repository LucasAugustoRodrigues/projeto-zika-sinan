# Relatório Final — Banco de Dados e Análise Estatística Epidemiológica
## Zika Vírus — SINAN 2018–2026

**Disciplina:** Banco de Dados / Modelagem Estatística  
**Tecnologia:** PostgreSQL 15+, Python 3.11  
**Dataset:** ZIKA_BR_2018_2026_UNIFICADO.csv — 236.398 notificações · 43 colunas · 27 UFs  
**Fonte:** SINAN — Sistema de Informação de Agravos de Notificação (DataSUS/MS)

---

## 1. Descrição do Projeto e Contexto Epidemiológico

O Zika vírus tornou-se emergência de saúde pública no Brasil entre 2015 e 2016, período em que a associação com microcefalia neonatal e síndrome de Guillain-Barré mobilizou sistemas de vigilância em todo o país. A partir de 2017 os casos entraram em declínio, mas o vírus não desapareceu: circulações residuais têm sido registradas anualmente, com variação regional expressiva entre os estados.

O SINAN (Sistema de Informação de Agravos de Notificação) registra compulsoriamente todas as notificações de doenças no Brasil. A base disponibilizada cobre de 2018 a 2026 e reúne 236.398 fichas com 43 campos cada, incluindo dados demográficos do paciente, datas de notificação e início de sintomas, classificação clínica final, critério diagnóstico, unidade notificadora e localização geográfica do caso e da residência.

O objetivo do projeto foi transformar esse CSV bruto em um banco de dados relacional normalizado no PostgreSQL, aplicar automações via funções e triggers, construir views prontas para visualização e conduzir análise estatística com modelos de previsão e agrupamento.

---

## 2. Arquitetura do Banco de Dados

### 2.1 Modelo Relacional

O schema `sinan` agrupa nove tabelas organizadas em três camadas funcionais.

As **tabelas de dimensão** armazenam entidades de referência que não mudam com o tempo: `dim_uf` (27 unidades federativas com sigla, nome e região), `dim_municipio` (municípios brasileiros com código IBGE 6/7 dígitos e vínculo à UF) e `dim_unidade_saude` (unidades notificadoras identificadas por código CNES).

As **tabelas de fatos** constituem o núcleo do modelo. `paciente` guarda atributos demográficos — sexo, raça, escolaridade, gestação, ocupação e idade decodificada em anos decimais — sem qualquer referência à notificação em si, o que permite reusar o mesmo registro de paciente em futuras extensões. `notificacao` é a tabela central: cada linha representa uma ficha, com datas, semana epidemiológica, UF e município notificadores, além de chave estrangeira para o paciente. `evolucao_clinica` guarda o desfecho clínico (classificação final, critério diagnóstico, data de óbito, duplicidade) em relação 1:1 com a notificação, via chave primária compartilhada. `localizacao_caso` registra os três locais que o SINAN distingue — notificação (em `notificacao`), residência e prováveis local e país de infecção.

As **tabelas de controle** são `audit_log`, populada automaticamente pelos triggers com snapshot JSONB de cada operação, e `etl_run_log`, que registra cada execução do pipeline com contadores de linhas lidas, inseridas e rejeitadas.

### 2.2 Decisões de Design

A separação entre `paciente` e `notificacao` é intencional: o SINAN mistura dados clínicos e demográficos na mesma ficha, mas modelar o paciente como entidade independente isola atributos que não deveriam se repetir a cada notificação. Na prática, como o dataset não contém identificadores únicos de paciente, cada linha do CSV gera um novo registro na tabela `paciente` — a separação é estrutural, não de deduplicação.

A tabela `evolucao_clinica` tem chave primária idêntica à de `notificacao` (`id_notif`), não uma chave surrogate própria. Isso impõe a relação 1:1 no nível do banco, elimina um JOIN desnecessário em consultas e torna a integridade referencial mais direta.

O campo `age_years` em `paciente` foi calculado no ETL a partir de `NU_IDADE_N`, campo proprietário do SINAN cujo primeiro dígito codifica a unidade (1=horas, 2=dias, 3=meses, 4=anos). Manter tanto o campo original quanto a versão decodificada permite auditoria posterior da transformação.

O `audit_log` não tem foreign key para `notificacao`. Essa foi uma decisão deliberada: se uma notificação for excluída, o log de auditoria desse delete deve sobreviver — uma FK com ON DELETE CASCADE eliminaria exatamente o registro que deveria ser preservado.

Nove índices cobrem os padrões de acesso mais frequentes: índice parcial em `evolucao_clinica` filtrando apenas `classi_fin = 1` (casos confirmados aparecem em praticamente todas as queries analíticas), índices em `dt_sin_pri`, `sg_uf`, `nu_ano` + `sem_not`, e um índice GIN no campo JSONB do `audit_log` para buscas dentro do snapshot.

---

## 3. Pipeline ETL

### 3.1 Fluxo de Carga

O script `pipeline_ingestao.py` executa em duas passagens sobre o CSV. Na primeira, lê o arquivo inteiro em memória apenas para extrair e carregar as três tabelas de dimensão — necessário porque as dimensões precisam existir antes de qualquer INSERT nas tabelas de fatos (restrição de foreign key). Na segunda passagem, relê o mesmo CSV em chunks de 10.000 linhas, transformando e inserindo cada bloco em transação atômica com rollback individual em caso de erro.

A ordem de inserção dentro de cada chunk segue a hierarquia de FKs: `paciente` primeiro (sem dependências), depois `notificacao` (depende de `paciente` e das dimensões), e em seguida `evolucao_clinica` e `localizacao_caso` em paralelo (ambos dependem apenas de `notificacao`).

### 3.2 Tratamentos Aplicados

O campo `NU_IDADE_N` foi decodificado vetorialmente com operações pandas antes de qualquer acesso ao banco, calculando `age_unit`, `age_value` e `age_years` por operações aritméticas sobre a série.

Datas foram tratadas com `pd.to_datetime(..., errors='coerce')` após substituição de valores inválidos do SINAN (`"0000-00-00"`, `"0"`, string vazia). Semanas epidemiológicas vieram no formato `YYYYWW` e foram reduzidas ao número da semana por `% 100`, com filtro `BETWEEN 1 AND 53`.

Vários campos categóricos continham o código 9 (ignorado) que o CHECK constraint do banco não aceita — foram convertidos para NULL por `_nullable_int(series, ignore={9})`. O campo `DOENCA_TRA` apresentava adicionalmente o código 0 (sem doença), também incompatível com o constraint `IN (1, 2)`, tratado da mesma forma.

Linhas com FK obrigatória ausente (data de notificação nula, semana inválida, UF ou município inválidos) foram descartadas antes do INSERT e contabilizadas em `linhas_rejeitadas` no log.

### 3.3 Registro de Execução

Cada execução do ETL abre um registro em `sinan.etl_run_log` com status `RUNNING` e o atualiza para `SUCCESS` ou `FAILED` ao término, incluindo contadores precisos de linhas lidas, inseridas e rejeitadas. Em caso de falha catastrófica o pipeline registra o stack trace completo no campo `detalhes_erro` antes de encerrar com exit code 1.

---

## 4. Funções e Triggers

### 4.1 Funções SQL

**`decode_age(nu_idade_n)`** converte o campo proprietário `NU_IDADE_N` do SINAN para anos decimais. Um valor como `4034` significa 34 anos; `3006` significa 6 meses (0.5 anos); `2045` significa 45 dias (0.123 anos). A função extrai a unidade pelo quociente inteiro por 1000 e o valor pelo resto, aplicando o divisor correspondente.

**`atraso_notificacao(id_notif)`** retorna a diferença em dias entre `dt_sin_pri` (início dos sintomas) e `dt_notific` (data de notificação). Esse indicador é relevante para avaliar a oportunidade da vigilância epidemiológica — um atraso médio alto sugere subnotificação tardia ou dificuldade de acesso ao sistema de saúde.

**`faixa_etaria(age_years)`** classifica a idade em seis faixas usadas nas análises: Menor de 1 ano, Criança (1–11), Adolescente (12–17), Adulto jovem (18–29), Adulto (30–59) e Idoso (60+).

**`resumo_epidemiologico(uf, ano)`** retorna uma tabela com os principais indicadores por UF e ano: total de confirmados, total de gestantes confirmadas, atraso médio de notificação e número de óbitos. Funciona como relatório em uma linha por chamada, útil para consultas parametrizadas.

**`detect_duplicatas()`** identifica fichas com a mesma combinação de data de notificação, município, sexo, idade e data de início de sintomas — chave que representa um mesmo evento clínico notificado mais de uma vez. O SINAN historicamente acumula duplicatas por reenvio de arquivos entre estados e o Ministério da Saúde.

**`insert_notificacao_validada(...)`** encapsula o INSERT de uma notificação completa com três validações clínicas antes do commit: sintomas não podem ser posteriores à notificação, data de óbito só pode estar preenchida se a evolução indica morte (código 2 ou 3), e a semana epidemiológica deve estar no intervalo válido de 1 a 53.

### 4.2 Triggers

**`trg_audit_notificacao`** e **`trg_audit_evolucao`** são triggers AFTER disparados em INSERT, UPDATE e DELETE nas tabelas `notificacao` e `evolucao_clinica`, respectivamente. Ambos executam a mesma função genérica `fn_audit_generico`, que grava em `audit_log` o nome da tabela, a operação realizada, o `id_notif` envolvido, um snapshot JSONB do estado anterior (`snapshot_before`) e um snapshot JSONB do estado posterior (`snapshot_after`). Para INSERTs, `snapshot_before` é NULL — não havia estado anterior. Para DELETEs, `snapshot_after` é NULL. O resultado é um histórico completo e consultável de qualquer modificação no banco.

**`trg_valida_clinica`** é um trigger BEFORE INSERT OR UPDATE em `evolucao_clinica` que corrige incoerências clínicas antes que o dado seja persistido. Se `dt_obito` estiver preenchida mas a evolução não indicar óbito, a data é zerada e um WARNING é emitido no log do servidor. Se a classificação final for 0 (descartado), o campo `criterio` é zerado — um caso descartado não pode ter critério de confirmação associado.

---

## 5. Views Analíticas

**`vw_casos_zika_analise`** é a view mestre para modelos de machine learning. Reúne em uma única consulta todos os atributos relevantes de `notificacao`, `paciente`, `evolucao_clinica` e `localizacao_caso`, filtrando apenas casos confirmados (`classi_fin = 1`). Inclui campos calculados como `atraso_notif_dias`, `flag_gestante` e `flag_obito` para facilitar feature engineering.

**`vw_serie_temporal_semanal`** agrega casos confirmados por ano, semana epidemiológica e UF de residência. É a base de dados do modelo NeuralProphet — basta um `GROUP BY nu_ano, sem_pri` para obter a série nacional.

**`vw_casos_uf_ano`** consolida, por UF e ano, o total de casos confirmados, gestantes confirmadas e óbitos. Alimenta o modelo K-Means e o mapa de calor do EDA.

**`vw_piramide_etaria`** conta casos confirmados cruzando faixa etária (calculada pela função `faixa_etaria`) e sexo, já na granularidade necessária para plotar uma pirâmide demográfica.

**`vw_vigilancia_gestantes`** lista individualmente todas as gestantes com Zika confirmado (`cs_gestant IN (1, 2, 3)`), com UF, município, data de início dos sintomas e desfecho clínico. Essa view é particularmente relevante para a vigilância de microcefalia e outros desfechos associados à infecção durante a gravidez.

**`vw_kpi_cards`** retorna uma única linha com os indicadores globais do projeto: total de confirmados, total de gestantes confirmadas, total de óbitos, percentual de casos autóctones, atraso médio de notificação em dias e período de cobertura. Projetada para alimentar cards de resumo em dashboards.

---

## 6. Modelos Estatísticos

### 6.1 Previsão de Casos — NeuralProphet

A série temporal utilizada é a agregação nacional semanal de casos confirmados, obtida de `vw_serie_temporal_semanal`. O modelo escolhido foi o NeuralProphet — substituto baseado em PyTorch do Prophet original do Facebook — com sazonalidade anual habilitada (`yearly_seasonality=True`) e sem sazonalidade semanal ou diária (não há sub-semana nos dados do SINAN). Intervalos de confiança a 95% foram gerados via `quantiles=[0.025, 0.975]`.

O modelo foi treinado sobre a série histórica completa (2018–2026), com semanas âncoras nas segundas-feiras (`freq="W-MON"`), e produziu uma previsão de 52 semanas à frente. Os resultados foram salvos em `data/processed/forecast_nacional.csv` com colunas `ds`, `yhat`, `yhat_lower` e `yhat_upper`, e em `forecast_plot_nacional.png` com o gráfico histórico + previsão com banda de confiança.

A sazonalidade anual capturada pelo modelo reflete o padrão epidemiológico do Aedes aegypti, vetor do Zika vírus: picos no verão austral (janeiro–março), período de maior atividade vetorial, e vales no inverno. A previsão quantifica esse padrão e projeta sua continuidade nos 12 meses seguintes ao horizonte dos dados.

### 6.2 Agrupamento de Municípios — K-Means

O objetivo do clustering foi identificar perfis epidemiológicos distintos entre os municípios brasileiros com base em cinco variáveis: `total_casos` (carga absoluta da doença), `perc_gestantes` (% de gestantes entre os casos), `perc_obitos` (% de óbitos), `media_atraso_dias` (oportunidade da vigilância) e `media_age_anos` (perfil etário dos casos). Apenas municípios com pelo menos 10 casos confirmados foram incluídos, para evitar que municípios com poucos registros distorcessem as métricas percentuais.

As features foram normalizadas com `StandardScaler` antes do agrupamento. O número ótimo de clusters foi determinado pelo maior coeficiente de silhouette entre k=2 e k=8. Um mecanismo de fallback garante que, se o k escolhido gerar algum cluster com menos de 5% dos municípios totais — situação típica quando há outliers extremos puxando k=2 —, o modelo recorre a k=4 como valor padrão.

Os resultados são salvos em `data/processed/clustering_municipios.csv` com o cluster atribuído a cada município, e em `clustering_elbow.png` com o gráfico de inércia e silhouette para todas as opções de k testadas.

Os clusters tenderam a separar municípios segundo três eixos principais: magnitude da epidemia (grandes centros urbanos vs. municípios de menor porte), perfil de risco gestacional (municípios com alta proporção de gestantes, relevantes para vigilância de microcefalia) e qualidade da vigilância (municípios com atraso de notificação baixo indicam sistemas de saúde mais responsivos). A interpretação precisa dos clusters depende do k selecionado em cada execução, que pode variar conforme a composição do banco de dados.

---

## 7. EDA — Principais Achados Epidemiológicos

A análise exploratória foi estruturada em seis seções no notebook `01_exploratory_analysis.ipynb`, cada uma autocontida e conectada diretamente ao banco via views.

**Curva epidêmica (§1.2).** Os subgráficos por ano revelam o padrão de sazonalidade do Zika no Brasil pós-epidemia: picos concentrados nas primeiras semanas de cada ano (verão austral), correspondendo ao período de maior densidade do vetor, seguidos de queda expressiva a partir da semana epidemiológica 15–20. Os anos mais próximos de 2024–2026 tendem a apresentar volumes menores que 2018–2019, refletindo a imunidade populacional adquirida durante a epidemia de 2016 e o controle vetorial intensificado nas regiões mais atingidas.

**Distribuição por UF e ano (§1.3).** O mapa de calor normalizado por linha evidencia que a concentração de casos não é homogênea nem no espaço nem no tempo. Estados do Nordeste e Sudeste respondem pela maior parcela histórica, mas a intensidade relativa se redistribui ao longo dos anos — algumas UFs que dominavam em 2018 perdem participação progressivamente, enquanto outras apresentam picos pontuais em anos específicos, possivelmente associados a surtos locais.

**Pirâmide etária (§1.4).** A pirâmide dos casos confirmados é assimétrica: o grupo feminino supera o masculino em praticamente todas as faixas etárias, com diferença mais marcada nas faixas de adulto jovem (18–29 anos) e adulto (30–59 anos). Esse padrão é consistente com a literatura — mulheres em idade fértil buscam mais ativamente atendimento médico, especialmente durante a gestação, e há maior sensibilidade diagnóstica nesse grupo pelo risco de transmissão vertical. A faixa infantil apresenta proporções menores, sugerindo subnotificação ou menor suscetibilidade clínica nessa faixa.

**Gestantes e desfechos clínicos (§1.5).** A série trimestral de gestantes confirmadas acompanha a curva epidêmica geral, com concentração nos primeiros trimestres de cada ano. O gráfico de desfechos mostra que a cura é o desfecho amplamente predominante — óbitos por Zika são raros no conjunto de dados, o que é epidemiologicamente esperado para uma arbovirose cujo principal risco de mortalidade direta é baixo (o maior impacto se dá via microcefalia, não capturada como desfecho na ficha de notificação padrão).

**Tendência por UF (§1.6).** A análise de tendência, com índice base 100 no primeiro ano de dados de cada UF, quantifica quais estados exibiram trajetória de crescimento ou queda sustentada ao longo do período. UFs com crescimento no índice normalizado indicam ou aumento real de casos ou melhoria no sistema de notificação (com aumento de diagnósticos registrados). UFs com queda consistente sugerem controle efetivo, esgotamento de suscetíveis ou redução genuína da circulação viral. A média anual de variação percentual complementa essa leitura ao suavizar flutuações pontuais.

---

## 8. Dificuldades Técnicas e Soluções

**Campo `DOENCA_TRA` com valores fora do domínio.** O CHECK constraint da tabela aceita apenas os valores 1, 2 ou NULL. O CSV do SINAN continha os códigos 0 (sem doença associada) e 9 (ignorado), que violam essa restrição. Solução: `_nullable_int(series, ignore={0, 9})` converte ambos os códigos para NULL antes do INSERT.

**Semana epidemiológica 53.** O parser `pd.to_datetime(format="%G-%V-%u")` lança `ValueError` para a semana 53 em anos que não possuem essa semana no calendário ISO. Solução: filtrar `sem_pri.between(1, 52)` antes da conversão, com `errors="coerce"` + `dropna` como segunda camada de segurança.

**Crash do Stan no Windows.** O Prophet original usa Stan/cmdstanpy como otimizador, que encerrava o processo no Windows com código de saída 3221225785 (access violation no runtime C++). Solução: migrar para NeuralProphet, que usa PyTorch como backend, sem dependência de Stan.

**Incompatibilidade do NeuralProphet com Pandas 2.1+.** O NeuralProphet tenta converter internamente uma `pd.Series` para tensor PyTorch via `.view()`, operação que o Pandas 2.x não suporta. Solução: forçar `pd.to_datetime` na coluna `ds` e `reset_index(drop=True)` antes de chamar `m.fit()`, garantindo que a série está no formato esperado pelo modelo.

**Sintaxe de parâmetros nomeados no `pd.read_sql`.** O Pandas 2.1 não interpreta a sintaxe `:nome` em queries SQL passadas como string direta. Solução: usar constantes literais diretamente na query em vez de parâmetros nomeados (`HAVING COUNT(*) >= 10` hardcoded).

**K-Means com k=2 e clusters desbalanceados.** O silhouette score frequentemente favorece k=2 quando há municípios com volume de casos muito superior à mediana, gerando um cluster unitário de outliers e um cluster com o restante. Solução: `_validate_k()` rejeita qualquer k que produza um cluster com menos de 5% do total de municípios, aplicando fallback para k=4.

**Long Path no Windows para o Jupyter.** O caminho completo do projeto somado aos diretórios temporários do kernel Jupyter pode ultrapassar o limite de 260 caracteres do Windows, causando falha silenciosa ao iniciar o kernel. Solução recomendada: abrir o notebook diretamente no VS Code com a extensão Jupyter, que gerencia os kernels de forma diferente e não apresenta essa limitação.

---

## 9. Como Reproduzir o Projeto

**Pré-requisitos:** Python 3.11 (versões 3.12+ são incompatíveis com NeuralProphet no Windows) e PostgreSQL 15+.

**Dados:** o arquivo `ZIKA_BR_2018_2026_UNIFICADO.csv` não está no repositório por tamanho. Baixe em: [Google Drive](https://drive.google.com/file/d/1CqIE2XTIvZz3Ty33lQmuXJOHIuadTXiC/view) e coloque em `data/raw/`.

**Banco de dados:** criar o database `zika` no pgAdmin, depois executar os quatro scripts SQL na ordem via Query Tool:

1. `src/database/ddl/01_init_schema.sql` — schema, tabelas, índices
2. `src/database/functions/02_functions.sql` — funções auxiliares
3. `src/database/triggers/03_triggers.sql` — triggers de auditoria e validação
4. `src/database/views/04_views.sql` — views analíticas

**Ambiente Python:**

```powershell
py -3.11 -m venv venv_prophet
.\venv_prophet\Scripts\activate
pip install -r requirements.txt
```

**Execução:**

```powershell
$env:PGPASSWORD="sua_senha"
python -m src.etl.pipeline_ingestao   # carga do CSV no banco
python main.py --models               # NeuralProphet + K-Means
```

Os arquivos de saída dos modelos são gravados em `data/processed/`. O notebook `notebooks/01_exploratory_analysis.ipynb` deve ser aberto e executado no VS Code para gerar os gráficos do EDA.
