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
    layout="wide",
)

st.title("📊 Painel de Análise - ITR (Imposto Territorial Rural)")

# -----------------------------------------------------------------------------
# BIGQUERY E CARREGAMENTO DOS DADOS
# -----------------------------------------------------------------------------
PROJECT_ID = "pesquisa-itr"
LOCATION = "southamerica-east1"
TABLE_PATH = "`pesquisa-itr.dados_itr.itr_pronto`"


@st.cache_resource
def get_bigquery_client():
    return bigquery.Client(project=PROJECT_ID, location=LOCATION)


@st.cache_data(ttl=3600)
def load_data():
    client = get_bigquery_client()

    query = f"""
        SELECT
            uf,
            codigo_do_municipio_ibge,
            municipio,
            codigo_do_imovel,
            denominacao,
            at_imovel,
            area_total,
            isencao,
            faixa_at,
            floresta,
            pastagem,
            silvicultura,
            lavouras,
            lavoura_aptid_o_boa,
            lavoura_aptid_o_regular,
            lavoura_aptid_o_restrita,
            faixa_gu,
            gu_fixo,
            gu_calc,
            aliquota_fixa,
            aliquota_calc,
            itr_gu_fixo,
            itr_gu_calc
        FROM {TABLE_PATH}
        LIMIT 5000
        """

    query_job = client.query(query, location=LOCATION)
    query_job.result(timeout=120)

    df = query_job.to_dataframe(
        create_bqstorage_client=False
    )

    return df

    # Garante que as colunas numéricas possam ser agregadas mesmo quando
    # alguma linha vier nula ou com tipo diferente da origem externa.
    numeric_columns = [
        "at_imovel",
        "area_total",
        "isencao",
        "floresta",
        "pastagem",
        "silvicultura",
        "lavouras",
        "lavoura_aptid_o_boa",
        "lavoura_aptid_o_regular",
        "lavoura_aptid_o_restrita",
        "gu_fixo",
        "gu_calc",
        "aliquota_fixa",
        "aliquota_calc",
        "itr_gu_fixo",
        "itr_gu_calc",
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    return df


with st.spinner("Carregando dados do BigQuery..."):
    try:
        df_raw = load_data()
    except Exception as e:
        st.error(f"Erro ao carregar dados do BigQuery: {e}")
        st.stop()

# -----------------------------------------------------------------------------
# FILTROS
# -----------------------------------------------------------------------------
st.sidebar.header("🔍 Filtros de Pesquisa")

lista_ufs = ["Brasil"] + sorted(df_raw["uf"].dropna().astype(str).unique().tolist())
estado_selecionado = st.sidebar.selectbox(
    "Selecione o Estado (UF)", lista_ufs
)

if estado_selecionado == "Brasil":
    municipios_disponiveis = ["Todos"]
else:
    df_uf = df_raw[df_raw["uf"].astype(str) == estado_selecionado]
    municipios_disponiveis = ["Todos"] + sorted(
        df_uf["municipio"].dropna().astype(str).unique().tolist()
    )

municipio_selecionado = st.sidebar.selectbox(
    "Selecione o Município", municipios_disponiveis
)

lista_faixas_at = ["Todas"] + sorted(
    df_raw["faixa_at"].dropna().astype(str).unique().tolist()
)
faixa_at_selecionada = st.sidebar.selectbox(
    "Faixa de área do imóvel", lista_faixas_at
)

lista_faixas_gu = ["Todas"] + sorted(
    df_raw["faixa_gu"].dropna().astype(str).unique().tolist()
)
faixa_gu_selecionada = st.sidebar.selectbox(
    "Faixa de GU", lista_faixas_gu
)

# -----------------------------------------------------------------------------
# APLICAÇÃO DOS FILTROS
# -----------------------------------------------------------------------------
df_filtrado = df_raw.copy()

if estado_selecionado != "Brasil":
    df_filtrado = df_filtrado[
        df_filtrado["uf"].astype(str) == estado_selecionado
    ]

if municipio_selecionado != "Todos":
    df_filtrado = df_filtrado[
        df_filtrado["municipio"].astype(str) == municipio_selecionado
    ]

if faixa_at_selecionada != "Todas":
    df_filtrado = df_filtrado[
        df_filtrado["faixa_at"].astype(str) == faixa_at_selecionada
    ]

if faixa_gu_selecionada != "Todas":
    df_filtrado = df_filtrado[
        df_filtrado["faixa_gu"].astype(str) == faixa_gu_selecionada
    ]

# -----------------------------------------------------------------------------
# KPIs
# -----------------------------------------------------------------------------
quantidade_imoveis = len(df_filtrado)
total_area = df_filtrado["area_total"].sum(min_count=1)
total_itr_gu_calc = df_filtrado["itr_gu_calc"].sum(min_count=1)

if pd.isna(total_area):
    total_area = 0.0
if pd.isna(total_itr_gu_calc):
    total_itr_gu_calc = 0.0

kpi1, kpi2, kpi3 = st.columns(3)
kpi1.metric(
    "Nº de imóveis",
    f"{quantidade_imoveis:,.0f}".replace(",", "."),
)
kpi2.metric(
    "Área total (ha)",
    f"{total_area:,.2f}".replace(",", "X")
    .replace(".", ",")
    .replace("X", "."),
)
kpi3.metric(
    "ITR GU calculado (R$)",
    f"R$ {total_itr_gu_calc:,.2f}".replace(",", "X")
    .replace(".", ",")
    .replace("X", "."),
)

st.markdown("---")

# -----------------------------------------------------------------------------
# GRÁFICOS TOP 10
# -----------------------------------------------------------------------------
st.subheader("📈 Análises Comparativas (Top 10)")

if estado_selecionado == "Brasil":
    coluna_agrupamento = "uf"
    label_eixo = "Estado (UF)"
    titulo_imoveis = "Top 10 Estados por número de imóveis"
    titulo_itr = "Top 10 Estados por ITR GU calculado"
else:
    coluna_agrupamento = "municipio"
    label_eixo = "Município"
    titulo_imoveis = (
        f"Top 10 Municípios em {estado_selecionado} por número de imóveis"
    )
    titulo_itr = (
        f"Top 10 Municípios em {estado_selecionado} por ITR GU calculado"
    )

# Cada linha da tabela representa um imóvel; por isso, a contagem correta é
# size(), e não a soma de uma coluna numero_imoveis que não existe na origem.
df_top_imoveis = (
    df_filtrado.groupby(coluna_agrupamento, dropna=False)
    .size()
    .reset_index(name="quantidade_imoveis")
    .sort_values("quantidade_imoveis", ascending=False)
    .head(10)
)

fig_imoveis = px.bar(
    df_top_imoveis,
    x=coluna_agrupamento,
    y="quantidade_imoveis",
    title=titulo_imoveis,
    labels={
        coluna_agrupamento: label_eixo,
        "quantidade_imoveis": "Nº de imóveis",
    },
    text_auto=True,
)
fig_imoveis.update_layout(xaxis={"categoryorder": "total descending"})

df_top_itr = (
    df_filtrado.groupby(coluna_agrupamento, dropna=False)["itr_gu_calc"]
    .sum(min_count=1)
    .reset_index()
    .sort_values("itr_gu_calc", ascending=False)
    .head(10)
)

fig_itr = px.bar(
    df_top_itr,
    x=coluna_agrupamento,
    y="itr_gu_calc",
    title=titulo_itr,
    labels={
        coluna_agrupamento: label_eixo,
        "itr_gu_calc": "ITR GU calculado (R$)",
    },
    text_auto=",.2f",
)
fig_itr.update_layout(xaxis={"categoryorder": "total descending"})

col_graf1, col_graf2 = st.columns(2)
with col_graf1:
    st.plotly_chart(fig_imoveis, use_container_width=True)
with col_graf2:
    st.plotly_chart(fig_itr, use_container_width=True)

st.markdown("---")

# -----------------------------------------------------------------------------
# TABELA DETALHADA - UMA ÚNICA TABELA, SEM ABAS
# -----------------------------------------------------------------------------
st.subheader("Tabela detalhada e validação dos filtros")
st.write(f"Registros após os filtros: **{len(df_filtrado):,}**".replace(",", "."))

st.dataframe(
    df_filtrado,
    use_container_width=True,
    hide_index=True,
)

st.download_button(
    "Baixar dados filtrados em CSV",
    data=df_filtrado.to_csv(index=False).encode("utf-8-sig"),
    file_name="dados_itr_filtrados.csv",
    mime="text/csv",
)
