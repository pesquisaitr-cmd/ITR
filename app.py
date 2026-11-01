import streamlit as st
import pandas as pd
from google.cloud import bigquery
import plotly.express as px

# -----------------------------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Dashboard ITR", page_icon="📊", layout="wide")
st.title("📊 Painel de Análise - ITR (Imposto Territorial Rural)")

PROJECT_ID = "pesquisa-itr"
LOCATION = "southamerica-east1"
TABLE_PATH = "`pesquisa-itr.dados_itr.itr_pronto`"
PAGE_SIZE = 1000

ARRECADACOES = {
    "ITR GU fixo": "itr_gu_fixo",
    "ITR GU calculado": "itr_gu_calc",
}


@st.cache_resource
def get_bigquery_client():
    return bigquery.Client(project=PROJECT_ID, location=LOCATION)


def run_query(sql, parameters=None):
    """Executa consulta parametrizada no BigQuery e retorna apenas seu resultado."""
    config = bigquery.QueryJobConfig(query_parameters=parameters or [])
    return get_bigquery_client().query(
        sql, job_config=config, location=LOCATION
    ).to_dataframe()


@st.cache_data(ttl=3600)
def get_distinct_values(column, uf=None):
    allowed = {"uf", "municipio"}
    if column not in allowed:
        raise ValueError("Coluna de filtro não permitida")
    sql = f"SELECT DISTINCT CAST({column} AS STRING) AS valor FROM {TABLE_PATH}"
    params = []
    if uf is not None:
        sql += " WHERE uf = @uf"
        params.append(bigquery.ScalarQueryParameter("uf", "STRING", uf))
    sql += " ORDER BY valor"
    result = run_query(sql, params)
    return result["valor"].dropna().astype(str).tolist()


def build_filters(uf, municipio, extensao):
    clauses, params = [], []
    if extensao == "Propriedades com área ≥ 0,5 hectare":
        clauses.append("at_imovel >= @area")
        params.append(bigquery.ScalarQueryParameter("area", "FLOAT64", 0.5))
    elif extensao == "Propriedades com área ≤ 2 hectares":
        clauses.append("at_imovel <= @area")
        params.append(bigquery.ScalarQueryParameter("area", "FLOAT64", 2.0))
    if uf != "Brasil":
        clauses.append("uf = @uf")
        params.append(bigquery.ScalarQueryParameter("uf", "STRING", uf))
    if municipio != "Todos":
        clauses.append("municipio = @municipio")
        params.append(bigquery.ScalarQueryParameter("municipio", "STRING", municipio))
    where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where_sql, params


with st.sidebar:
    st.header("🔍 Filtros de Pesquisa")
    arrecadacao_label = st.selectbox(
        "Filtro 1 — Arrecadação", list(ARRECADACOES.keys())
    )
    arrecadacao_col = ARRECADACOES[arrecadacao_label]

    extensao = st.selectbox(
        "Filtro 2 — Extensão da propriedade",
        [
            "Todas as propriedades",
            "Propriedades com área ≥ 0,5 hectare",
            "Propriedades com área ≤ 2 hectares",
        ],
    )

    try:
        ufs = ["Brasil"] + get_distinct_values("uf")
        uf = st.selectbox("Filtro 3 — UF", ufs)
        municipios = ["Todos"]
        if uf != "Brasil":
            municipios += get_distinct_values("municipio", uf)
        municipio = st.selectbox("Filtro 4 — Município", municipios)
    except Exception as exc:
        st.error(f"Erro ao carregar opções de filtro do BigQuery: {exc}")
        st.stop()

where_sql, filter_params = build_filters(uf, municipio, extensao)
valor_label = "ITR GU fixo" if arrecadacao_col == "itr_gu_fixo" else "ITR GU calculado"

# KPIs calculados no BigQuery.
try:
    kpis = run_query(
        f"""SELECT COUNT(*) AS quantidade_imoveis,
                   COALESCE(SUM(area_total), 0) AS total_area,
                   COALESCE(SUM({arrecadacao_col}), 0) AS total_arrecadacao
            FROM {TABLE_PATH}{where_sql}""",
        filter_params,
    ).iloc[0]
except Exception as exc:
    st.error(f"Erro ao consultar o BigQuery: {exc}")
    st.stop()

kpi1, kpi2, kpi3 = st.columns(3)
kpi1.metric("Nº de imóveis", f"{int(kpis['quantidade_imoveis']):,}".replace(",", "."))
kpi2.metric("Área total (ha)", f"{float(kpis['total_area']):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
kpi3.metric(valor_label + " (R$)", "R$ " + f"{float(kpis['total_arrecadacao']):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
st.markdown("---")

# Gráficos agregados no BigQuery, limitados ao Top 10.
st.subheader("📈 Análises Comparativas (Top 10)")
group_col = "uf" if uf == "Brasil" else "municipio"
group_label = "Estados (UF)" if uf == "Brasil" else "Municípios"
chart_sql = f"""SELECT {group_col} AS grupo,
                         COUNT(*) AS quantidade_imoveis,
                         SUM({arrecadacao_col}) AS arrecadacao
                  FROM {TABLE_PATH}{where_sql}
                  GROUP BY grupo"""
try:
    summary = run_query(chart_sql, filter_params)
    top_count = summary.nlargest(10, "quantidade_imoveis")
    top_revenue = summary.nlargest(10, "arrecadacao")
    fig_count = px.bar(
        top_count, x="grupo", y="quantidade_imoveis",
        title=f"Top 10 {group_label} por número de imóveis",
        labels={"grupo": group_label, "quantidade_imoveis": "Nº de imóveis"},
        text_auto=True,
    )
    fig_count.update_layout(xaxis={"categoryorder": "total descending"})
    fig_revenue = px.bar(
        top_revenue, x="grupo", y="arrecadacao",
        title=f"Top 10 {group_label} por {valor_label}",
        labels={"grupo": group_label, "arrecadacao": f"{valor_label} (R$)"},
        text_auto=",.2f",
    )
    fig_revenue.update_layout(xaxis={"categoryorder": "total descending"})
    col1, col2 = st.columns(2)
    col1.plotly_chart(fig_count, use_container_width=True)
    col2.plotly_chart(fig_revenue, use_container_width=True)
except Exception as exc:
    st.error(f"Erro ao gerar agregações: {exc}")

# Tabela cruzada e mapas de calor, agregados no BigQuery segundo os filtros.
st.markdown("---")
st.subheader("Tabela cruzada — Extensão da propriedade × Faixa de GU")
st.caption(
    "Linhas: at_imovel (hectares). Colunas: faixa_gu. "
    "O mapa de calor representa os valores da tabela cruzada."
)
crosstab_sql = f"""SELECT
                    CAST(at_imovel AS STRING) AS at_imovel,
                    COALESCE(CAST(faixa_gu AS STRING), 'Não informado') AS faixa_gu,
                    COUNT(*) AS quantidade_imoveis,
                    SUM(itr_gu_calc) AS arrecadacao
                FROM {TABLE_PATH}{where_sql}
                GROUP BY at_imovel, faixa_gu
                ORDER BY SAFE_CAST(at_imovel AS FLOAT64), faixa_gu"""

def render_crosstab(frame, value_column, value_label, number_format):
    if frame.empty:
        st.info("Não há dados para a combinação atual de filtros.")
        return
    matrix = frame.pivot_table(
        index="at_imovel",
        columns="faixa_gu",
        values=value_column,
        aggfunc="sum",
        fill_value=0,
    )
    matrix = matrix.sort_index(
        key=lambda idx: pd.to_numeric(idx, errors="coerce").fillna(float("inf"))
    )
    st.dataframe(matrix, use_container_width=True)
    if matrix.empty or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        st.info("Não há valores para construir o mapa de calor.")
        return
    heatmap = px.imshow(
        matrix,
        labels={"x": "Faixa de GU", "y": "at_imovel (ha)", "color": value_label},
        aspect="auto",
        color_continuous_scale="YlOrRd",
        text_auto=number_format,
    )
    heatmap.update_layout(title=f"Mapa de calor — {value_label}")
    st.plotly_chart(heatmap, use_container_width=True)

try:
    crosstab_data = run_query(crosstab_sql, filter_params)
    if arrecadacao_col == "itr_gu_calc":
        tab_count, tab_revenue = st.tabs(["Nº de imóveis", "Arrecadação"])
        with tab_count:
            render_crosstab(
                crosstab_data, "quantidade_imoveis", "Nº de imóveis", ",d"
            )
        with tab_revenue:
            render_crosstab(
                crosstab_data, "arrecadacao", "Arrecadação (R$)", ",.2f"
            )
    else:
        render_crosstab(
            crosstab_data, "quantidade_imoveis", "Nº de imóveis", ",d"
        )
except Exception as exc:
    st.error(f"Erro ao gerar a tabela cruzada: {exc}")

st.markdown("---")
st.subheader("Tabela detalhada")
st.caption(
    "Os resultados são consultados sob demanda e exibidos em páginas de 1.000 registros. "
    "Os quatro filtros são aplicados no BigQuery."
)
total_rows = int(kpis["quantidade_imoveis"])
page_count = max(1, (total_rows + PAGE_SIZE - 1) // PAGE_SIZE)
page = st.number_input("Página", min_value=1, max_value=page_count, value=1, step=1)
offset = (int(page) - 1) * PAGE_SIZE
columns = "uf, codigo_do_municipio_ibge, municipio, codigo_do_imovel, denominacao, at_imovel, area_total, isencao, faixa_at, floresta, pastagem, silvicultura, lavouras, lavoura_aptid_o_boa, lavoura_aptid_o_regular, lavoura_aptid_o_restrita, faixa_gu, gu_fixo, gu_calc, aliquota_fixa, aliquota_calc, itr_gu_fixo, itr_gu_calc"
page_params = list(filter_params) + [
    bigquery.ScalarQueryParameter("page_size", "INT64", PAGE_SIZE),
    bigquery.ScalarQueryParameter("offset", "INT64", offset),
]
try:
    page_df = run_query(
        f"SELECT {columns} FROM {TABLE_PATH}{where_sql} "
        "ORDER BY codigo_do_imovel LIMIT @page_size OFFSET @offset",
        page_params,
    )
    st.write(
        f"Registros correspondentes: **{total_rows:,}** · Página **{int(page)}** de **{page_count}**".replace(",", ".")
    )
    st.dataframe(page_df, use_container_width=True, hide_index=True)
    st.download_button(
        "Baixar esta página em CSV",
        data=page_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"dados_itr_pagina_{int(page)}.csv",
        mime="text/csv",
    )
except Exception as exc:
    st.error(f"Erro ao carregar a página da tabela: {exc}")
