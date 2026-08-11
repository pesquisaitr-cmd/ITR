import pandas as pd
import plotly.express as px
import streamlit as st
from google.cloud import bigquery

# Configuração da página
st.set_page_config(
    page_title="Painel de Análise ITR", page_icon="📊", layout="wide"
)

# Configuração do BigQuery
PROJECT_ID = "pesquisa-itr"
TABLE_PATH = f"`{PROJECT_ID}.dados_itr.itr_pronto`"


@st.cache_resource
def get_client():
    return bigquery.Client(project="pesquisa-itr")


@st.cache_data(ttl=3600)
def carregar_ufs():
    client = get_client()
    query = f"SELECT DISTINCT uf FROM {TABLE_PATH} WHERE uf IS NOT NULL ORDER BY uf"
    ufs = client.query(query).to_dataframe()["uf"].tolist()
    return ["Brasil (Todos)"] + ufs


@st.cache_data(ttl=3600)
def carregar_dados_uf(uf_selecionada, filtro_area):
    client = get_client()

    condicoes = []
    query_parameters = []

    # Se NÃO for Brasil, filtra pela UF específica selecionada
    if uf_selecionada != "Brasil (Todos)":
        condicoes.append("uf = @uf")
        query_parameters.append(
            bigquery.ScalarQueryParameter("uf", "STRING", uf_selecionada)
        )

    # Filtro de área (< 2 ha)
    if filtro_area == "Menor que 2 hectares (< 2 ha)":
        condicoes.append("at_imovel < 2.0")

    # Monta a cláusula WHERE dinamicamente
    where_clause = ""
    if condicoes:
        where_clause = "WHERE " + " AND ".join(condicoes)

    query = f"""
        SELECT
            uf,
            codigo_do_municipio_ibge AS codigo_ibge,
            municipio,
            at_imovel,
            area_total,
            faixa_at,
            faixa_gu,
            gu_fixo,
            gu_calc,
            aliquota_fixa,
            aliquota_calc,
            itr_gu_fixo,
            itr_gu_calc
        FROM {TABLE_PATH}
        {where_clause}
    """

    job_config = bigquery.QueryJobConfig(query_parameters=query_parameters)
    return client.query(query, job_config=job_config).to_dataframe()


# --- INTERFACE E BARRA LATERAL ---
st.title("🌾 Painel Relatório ITR")

lista_ufs = carregar_ufs()
uf_selecionada = st.sidebar.selectbox("Selecione o Estado (UF):", lista_ufs)

filtro_area = st.sidebar.radio(
    "Tamanho da Propriedade:",
    ["Todas as propriedades", "Menor que 2 hectares (< 2 ha)"],
)

aba = st.sidebar.radio(
    "Escolha o Relatório:",
    [
        "1. Resumo Geral por UF",
        "2. Análise do Grau de Utilização (GU)",
        "3. Comparativo de Alíquotas e Imposto",
    ],
)

if uf_selecionada:
    with st.spinner(f"Carregando dados de {uf_selecionada}..."):
        df = carregar_dados_uf(uf_selecionada, filtro_area)

    # --- RELATÓRIO 1: RESUMO GERAL ---
    if aba == "1. Resumo Geral por UF":
        st.header(f"📊 Relatório 1: Visão Geral - {uf_selecionada}")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total de Imóveis", f"{len(df):,}")
        col2.metric("Municípios Atendidos", df["municipio"].nunique())
        col3.metric("Área Total (ha)", f"{df['area_total'].sum():,.2f}")
        col4.metric(
            "ITR Calculado Total (R$)", f"R$ {df['itr_gu_calc'].sum():,.2f}"
        )

        st.markdown("---")

        # Ranking de Municípios por Arrecadação
        top_muni = (
            df.groupby("municipio")["itr_gu_calc"]
            .sum()
            .reset_index()
            .sort_values(by="itr_gu_calc", ascending=False)
            .head(10)
        )

        fig_muni = px.bar(
            top_muni,
            x="itr_gu_calc",
            y="municipio",
            orientation="h",
            title="Top 10 Municípios com Maior ITR Calculado",
            labels={"itr_gu_calc": "ITR Calculado (R$)", "municipio": "Município"},
        )
        st.plotly_chart(fig_muni, use_container_width=True)

    # --- RELATÓRIO 2: ANÁLISE DE GRAU DE UTILIZAÇÃO ---
    elif aba == "2. Análise do Grau de Utilização (GU)":
        st.header(f"🚜 Relatório 2: Distribuição por Grau de Utilização (GU)")

        col1, col2 = st.columns(2)

        with col1:
            gu_counts = df["faixa_gu"].value_counts().reset_index()
            gu_counts.columns = ["Faixa GU", "Quantidade"]
            fig_pie = px.pie(
                gu_counts,
                names="Faixa GU",
                values="Quantidade",
                title="Distribuição dos Imóveis por Faixa de GU",
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with col2:
            at_counts = df["faixa_at"].value_counts().reset_index()
            at_counts.columns = ["Faixa Área Total", "Quantidade"]
            fig_bar = px.bar(
                at_counts,
                x="Faixa Área Total",
                y="Quantidade",
                title="Distribuição dos Imóveis por Tamanho de Área (AT)",
            )
            st.plotly_chart(fig_bar, use_container_width=True)

    # --- RELATÓRIO 3: COMPARATIVO DE ALÍQUOTAS ---
    elif aba == "3. Comparativo de Alíquotas e Imposto":
        st.header(f"💰 Relatório 3: Comparativo de Alíquotas (Fixo vs Calculado)")

        col1, col2 = st.columns(2)
        col1.metric("Média Alíquota Fixa", f"{df['aliquota_fixa'].mean():.2f}%")
        col2.metric("Média Alíquota Calc", f"{df['aliquota_calc'].mean():.2f}%")

        st.markdown("---")

        fig_comp = px.scatter(
            df.sample(min(1000, len(df))),
            x="aliquota_fixa",
            y="aliquota_calc",
            color="faixa_at",
            hover_data=["municipio"],
            title="Dispersão: Alíquota Fixa vs Alíquota Calculada (Amostra 1.000)",
            labels={
                "aliquota_fixa": "Alíquota Fixa (%)",
                "aliquota_calc": "Alíquota Calculada (%)",
            },
        )
        st.plotly_chart(fig_comp, use_container_width=True)

    # Tabela detalhada opcional no rodapé
    with st.expander("Ver Tabela de Dados Detalhada"):
        st.dataframe(df, use_container_width=True)
