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
# CLIENTE BIGQUERY E CARREGAMENTO DE DADOS (COM CACHE)
# -----------------------------------------------------------------------------
@st.cache_resource
def get_bigquery_client():
    return bigquery.Client(
        project="pesquisa-itr",
        location="southamerica-east1"
    )

@st.cache_data(ttl=3600)
def load_data():
    client = get_bigquery_client()

    # Consulta ajustada exatamente para as colunas reais da tabela itr_pronto
    query = """
        SELECT 
            codigo_do_municipio_ibge,
            uf,
            municipio,
            at_imovel,
            area_total,
            itr_gu_fixo,
            itr_gu_calc
        FROM `pesquisa-itr.dados_itr.itr_pronto`
    """

    query_job = client.query(
        query,
        location="southamerica-east1"
    )
    df = query_job.to_dataframe()

    # Tratamentos e métricas derivadas
    df["numero_imoveis"] = 1  # Cada linha representa um imóvel/registro
    df["itr_gu_fixo"] = pd.to_numeric(df["itr_gu_fixo"], errors="coerce").fillna(0)
    df["itr_gu_calc"] = pd.to_numeric(df["itr_gu_calc"], errors="coerce").fillna(0)
    df["arrecadacao"] = df["itr_gu_fixo"] + df["itr_gu_calc"]
    df["at_imovel"] = pd.to_numeric(df["at_imovel"], errors="coerce").fillna(0)
    df["area_total"] = pd.to_numeric(df["area_total"], errors="coerce").fillna(0)

    return df

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
lista_ufs = ["Brasil"] + sorted(list(df_raw["uf"].dropna().astype(str).unique()))
estado_selecionado = st.sidebar.selectbox("Selecione o Estado (UF)", lista_ufs)

# 2. Filtro de Município (Dinâmico com base no Estado)
if estado_selecionado == "Brasil":
    municipios_disponiveis = ["Todos"]
else:
    df_uf = df_raw[df_raw["uf"].astype(str) == estado_selecionado]
    municipios_disponiveis = ["Todos"] + sorted(list(df_uf["municipio"].dropna().astype(str).unique()))

municipio_selecionado = st.sidebar.selectbox("Selecione o Município", municipios_disponiveis)

# -----------------------------------------------------------------------------
# APLICAÇÃO DOS FILTROS AO DATAFRAME
# -----------------------------------------------------------------------------
df_filtrado = df_raw.copy()

if estado_selecionado != "Brasil":
    df_filtrado = df_filtrado[df_filtrado["uf"].astype(str) == estado_selecionado]

if municipio_selecionado != "Todos":
    df_filtrado = df_filtrado[df_filtrado["municipio"].astype(str) == municipio_selecionado]

# -----------------------------------------------------------------------------
# CARTÕES DE MÉTRICAS (KPIs)
# -----------------------------------------------------------------------------
kpi1, kpi2, kpi3 = st.columns(3)

total_imoveis = df_filtrado["numero_imoveis"].sum()
total_area = df_filtrado["total_area"].sum()
total_arrecadacao = df_filtrado["arrecadacao"].sum()

kpi1.metric("Nº Total de Imóveis", f"{total_imoveis:,.0f}".replace(",", "."))
kpi2.metric("Área Total (ha)", f"{total_area:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
kpi3.metric("Arrecadacao Total (R$)", f"R$ {total_arrecadacao:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

st.markdown("---")

# -----------------------------------------------------------------------------
# GRÁFICOS DINÂMICOS (TOP 10 ESTADOS OU TOP 10 MUNICÍPIOS)
# -----------------------------------------------------------------------------
st.subheader("📈 Análises Comparativas (Top 10)")

if estado_selecionado == "Brasil":
    coluna_agrupamento = "uf"
    label_eixo = "Estado (UF)"
    titulo_imoveis = "Top 10 Estados por Número de Imóveis"
    titulo_arrecadacao = "Top 10 Estados por Arrecadação"
else:
    coluna_agrupamento = "municipio"
    label_eixo = "Município"
    titulo_imoveis = f"Top 10 Municípios em {estado_selecionado} por Número de Imóveis"
    titulo_arrecadacao = f"Top 10 Municípios em {estado_selecionado} por Arrecadação"

# 1. Agregação e Gráfico de Número de Imóveis
df_top_imoveis = (
    df_filtrado.groupby(coluna_agrupamento)["numero_imoveis"]
    .sum()
    .reset_index()
    .sort_values(by="numero_imoveis", ascending=False)
    .head(10)
)
df_top_imoveis[coluna_agrupamento] = df_top_imoveis[coluna_agrupamento].astype(str)

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
df_top_arrecadacao[coluna_agrupamento] = df_top_arrecadacao[coluna_agrupamento].astype(str)

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
with st.expander("Tabela detalhada e validação de filtro", expanded=True):
    if estado_selecionado == "Brasil":
        st.info("Selecione um Estado (UF) para visualizar os dados detalhados.")
    else:
        st.write(f"Quantidade de registros após os filtros: **{len(df_filtrado):,}**".replace(",", "."))
        st.dataframe(df_filtrado, use_container_width=True, hide_index=True)
