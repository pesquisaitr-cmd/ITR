import streamlit as st
import pandas as pd
from google.cloud import bigquery
import plotly.express as px

# -----------------------------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Dashboard ITR",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Painel de Análise - ITR (Imposto Territorial Rural)")

# -----------------------------------------------------------------------------
# BANNER DE TESTE DE DEPLOY (REMOVER APÓS CONFIRMAR O BUILD)
# -----------------------------------------------------------------------------
st.error("🚀 TESTE DE DEPLOY: SE VOCÊ ESTÁ VENDO ESTA MENSAGEM, O CLOUD BUILD ATUALIZOU O CÓDIGO CORRETAMENTE!")

# -----------------------------------------------------------------------------
# CLIENTE BIGQUERY E CARREGAMENTO DE DADOS (COM CACHE)
# -----------------------------------------------------------------------------
@st.cache_resource
def get_bigquery_client():
    return bigquery.Client(project="pesquisa-itr", location="southamerica-east1")

@st.cache_data(ttl=3600)
def load_data():
    client = get_bigquery_client()
    query = """
        SELECT 
            codigo_do_municipio_ibge,
            uf,
            municipio,
            at_imovel,
            tipo_arrecadacao,
            numero_imoveis,
            area_total,
            arrecadacao
        FROM `pesquisa-itr.dados_itr.itr_pronto`
    """
    query_job = client.query(query, location="southamerica-east1")
    return query_job.to_dataframe()
with st.spinner("Carregando dados do BigQuery..."):
    try:
        df_raw = load_data()
    except Exception as e:
        st.error(f"Erro ao carregar dados do BigQuery: {e}")
        st.stop()

# -----------------------------------------------------------------------------
# BARRA LATERAL - FILTROS
# -----------------------------------------------------------------------------
st.sidebar.header("🔍 Filtros de Pesquisa")

# 1. Filtro de Estado (UF)
lista_ufs = ["Brasil"] + sorted(list(df_raw["uf"].dropna().unique()))
estado_selecionado = st.sidebar.selectbox("Selecione o Estado (UF)", lista_ufs)

# 2. Filtro de Município (Dinâmico com base no Estado)
if estado_selecionado == "Brasil":
    municipios_disponiveis = ["Todos"]
else:
    df_uf = df_raw[df_raw["uf"] == estado_selecionado]
    municipios_disponiveis = ["Todos"] + sorted(list(df_uf["municipio"].dropna().unique()))

municipio_selecionado = st.sidebar.selectbox("Selecione o Município", municipios_disponiveis)

# 3. Filtro de Tamanho da Propriedade
lista_tamanhos = ["Todas"] + sorted(list(df_raw["tamanho_propriedade"].dropna().unique()))
tamanho_selecionado = st.sidebar.selectbox("Tamanho da Propriedade", lista_tamanhos)

# 4. Filtro de Tipo de Arrecadação
lista_arrecadacao = sorted(list(df_raw["tipo_arrecadacao"].dropna().unique()))
if lista_arrecadacao:
    arrecadacao_selecionada = st.sidebar.selectbox("Tipo de Arrecadação", lista_arrecadacao)
else:
    arrecadacao_selecionada = None

# -----------------------------------------------------------------------------
# APLICAÇÃO DOS FILTROS AO DATAFRAME
# -----------------------------------------------------------------------------
df_filtrado = df_raw.copy()

if estado_selecionado != "Brasil":
    df_filtrado = df_filtrado[df_filtrado["uf"] == estado_selecionado]

if municipio_selecionado != "Todos":
    df_filtrado = df_filtrado[df_filtrado["municipio"] == municipio_selecionado]

if tamanho_selecionado != "Todas":
    df_filtrado = df_filtrado[df_filtrado["tamanho_propriedade"] == tamanho_selecionado]

if arrecadacao_selecionada:
    df_filtrado = df_filtrado[df_filtrado["tipo_arrecadacao"] == arrecadacao_selecionada]

# -----------------------------------------------------------------------------
# CARTÕES DE MÉTRICAS (KPIs)
# -----------------------------------------------------------------------------
kpi1, kpi2, kpi3 = st.columns(3)

total_imoveis = df_filtrado["numero_imoveis"].sum()
total_area = df_filtrado["area_total"].sum()
total_arrecadacao = df_filtrado["arrecadacao"].sum()

kpi1.metric("Nº Total de Imóveis", f"{total_imoveis:,.0f}".replace(",", "."))
kpi2.metric("Área Total (ha)", f"{total_area:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
kpi3.metric("Arrecadação Total (R$)", f"R$ {total_arrecadacao:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

st.markdown("---")

# -----------------------------------------------------------------------------
# GRÁFICOS DINÂMICOS (TOP 10 ESTADOS OU TOP 10 MUNICÍPIOS)
# -----------------------------------------------------------------------------
st.subheader("📈 Análises Comparativas (Top 10)")

if estado_selecionado == "Brasil":
    coluna_agrupamento = "uf"
    label_eixo = "Estado (UF)"
    titulo_imoveis = "Top 10 Estados por Número de Imóveis"
    titulo_arrecadacao = f"Top 10 Estados por Arrecadação ({arrecadacao_selecionada if arrecadacao_selecionada else ''})"
else:
    coluna_agrupamento = "municipio"
    label_eixo = "Município"
    titulo_imoveis = f"Top 10 Municípios em {estado_selecionado} por Número de Imóveis"
    titulo_arrecadacao = f"Top 10 Municípios em {estado_selecionado} por Arrecadação ({arrecadacao_selecionada if arrecadacao_selecionada else ''})"

# 1. Agregação e Gráfico de Número de Imóveis
df_top_imoveis = (
    df_filtrado.groupby(coluna_agrupamento)["numero_imoveis"]
    .sum()
    .reset_index()
    .sort_values(by="numero_imoveis", ascending=False)
    .head(10)
)

fig_imoveis = px.bar(
    df_top_imoveis,
    x=coluna_agrupamento,
    y="numero_imoveis",
    title=titulo_imoveis,
    labels={coluna_agrupamento: label_eixo, "numero_imoveis": "Nº de Imóveis"},
    text_auto=True
)
fig_imoveis.update_layout(xaxis={'categoryorder': 'total descending'})

# 2. Agregação e Gráfico de Arrecadação
df_top_arrecadacao = (
    df_filtrado.groupby(coluna_agrupamento)["arrecadacao"]
    .sum()
    .reset_index()
    .sort_values(by="arrecadacao", ascending=False)
    .head(10)
)

fig_arrecadacao = px.bar(
    df_top_arrecadacao,
    x=coluna_agrupamento,
    y="arrecadacao",
    title=titulo_arrecadacao,
    labels={coluna_agrupamento: label_eixo, "arrecadacao": "Arrecadação (R$)"},
    text_auto=',.2f'
)
fig_arrecadacao.update_layout(xaxis={'categoryorder': 'total descending'})

col_graf1, col_graf2 = st.columns(2)
with col_graf1:
    st.plotly_chart(fig_imoveis, use_container_width=True)
with col_graf2:
    st.plotly_chart(fig_arrecadacao, use_container_width=True)

st.markdown("---")

# -----------------------------------------------------------------------------
# TABELA DETALHADA E VALIDAÇÃO DE FILTRO
# -----------------------------------------------------------------------------
with st.expander("Tabelas detalhadas selecione um Estado e/ou Município"):
    if estado_selecionado == "Brasil":
        st.warning("⚠️ Por favor, selecione um Estado (UF) e/ou Município específico no painel lateral para visualizar os dados detalhados.")
    else:
        st.dataframe(
            df_filtrado,
            use_container_width=True
        )
