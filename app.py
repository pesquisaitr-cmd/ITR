import streamlit as st
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


def build_filters(uf, municipio, area_min, area_max):
    clauses, params = ["at_imovel >= @area_min", "at_imovel <= @area_max"], [
        bigquery.ScalarQueryParameter("area_min", "FLOAT64", area_min),
        bigquery.ScalarQueryParameter("area_max", "FLOAT64", area_max),
    ]
    if uf != "Brasil":
        clauses.append("uf = @uf")
        params.append(bigquery.ScalarQueryParameter("uf", "STRING", uf))
    if municipio != "Todos":
        clauses.append("municipio = @municipio")
        params.append(bigquery.ScalarQueryParameter("municipio", "STRING", municipio))
    return " WHERE " + " AND ".join(clauses), params


with st.sidebar:
    st.header("🔍 Filtros de Pesquisa")
    arrecadacao_label = st.selectbox(
        "Filtro 1 — Arrecadação", list(ARRECADACOES.keys())
    )
    arrecadacao_col = ARRECADACOES[arrecadacao_label]

    st.markdown("**Filtro 2 — Extensão da propriedade (hectares)**")
    area_col1, area_col2 = st.columns(2)
    area_min = area_col1.number_input(
        "Mínimo", min_value=0.0, value=0.5, step=0.1, format="%.1f"
    )
    area_max = area_col2.number_input(
        "Máximo", min_value=0.0, value=2.0, step=0.1, format="%.1f"
    )
    if area_min > area_max:
        st.error("A extensão mínima deve ser menor ou igual à máxima.")
        st.stop()

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

where_sql, filter_params = build_filters(uf, municipio, area_min, area_max)
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
