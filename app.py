import streamlit as st
import pandas as pd
import re
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


def format_br_number(value, decimals=2):
    """Formata números com ponto de milhar e vírgula decimal."""
    if pd.isna(value):
        return "—"
    return f"{float(value):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


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


def build_filters(uf, municipio, extensao, categoria):
    clauses, params = [], []
    if categoria == "Isentos":
        clauses.append("isencao = @isencao")
        params.append(bigquery.ScalarQueryParameter("isencao", "INT64", 1))
    elif categoria == "Pagantes":
        clauses.append("isencao = @isencao")
        params.append(bigquery.ScalarQueryParameter("isencao", "INT64", 0))
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

    categoria = st.selectbox(
        "Filtro 2 — Categorias",
        ["Todos", "Isentos", "Pagantes"],
    )

    extensao = st.selectbox(
        "Filtro 3 — Extensão da propriedade",
        [
            "Todas as propriedades",
            "Propriedades com área ≥ 0,5 hectare",
            "Propriedades com área ≤ 2 hectares",
        ],
    )

    try:
        ufs = ["Brasil"] + get_distinct_values("uf")
        uf = st.selectbox("Filtro 4 — UF", ufs)
        municipios = ["Todos"]
        if uf != "Brasil":
            municipios += get_distinct_values("municipio", uf)
        municipio = st.selectbox("Filtro 5 — Município", municipios)
    except Exception as exc:
        st.error(f"Erro ao carregar opções de filtro do BigQuery: {exc}")
        st.stop()

where_sql, filter_params = build_filters(uf, municipio, extensao, categoria)
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
    fig_count.update_layout(
        xaxis={"categoryorder": "total descending"}, separators=",."
    )
    fig_count.update_traces(texttemplate="%{y:,.0f}")
    fig_revenue = px.bar(
        top_revenue, x="grupo", y="arrecadacao",
        title=f"Top 10 {group_label} por {valor_label}",
        labels={"grupo": group_label, "arrecadacao": f"{valor_label} (R$)"},
        text_auto=",.2f",
    )
    fig_revenue.update_layout(
        xaxis={"categoryorder": "total descending"}, separators=",."
    )
    fig_revenue.update_traces(texttemplate="%{y:,.2f}")
    col1, col2 = st.columns(2)
    col1.plotly_chart(fig_count, use_container_width=True)
    col2.plotly_chart(fig_revenue, use_container_width=True)
except Exception as exc:
    st.error(f"Erro ao gerar agregações: {exc}")

# Tabela cruzada e mapas de calor, agregados no BigQuery segundo os filtros.
st.markdown("---")
st.subheader("Tabela cruzada — Extensão da propriedade × Faixa de GU")
st.caption(
    "Linhas: faixa_at (categoria de extensão). Colunas: faixa_gu. "
    "O mapa de calor representa os valores da tabela cruzada."
)
crosstab_sql = f"""SELECT
                    COALESCE(CAST(faixa_at AS STRING), 'Não informado') AS faixa_at,
                    COALESCE(CAST(faixa_gu AS STRING), 'Não informado') AS faixa_gu,
                    COUNT(*) AS quantidade_imoveis,
                    SUM(itr_gu_calc) AS arrecadacao
                FROM {TABLE_PATH}{where_sql}
                GROUP BY faixa_at, faixa_gu
                ORDER BY faixa_at, faixa_gu"""

def render_crosstab(frame, value_column, value_label, decimals):
    if frame.empty:
        st.info("Não há dados para a combinação atual de filtros.")
        return
    matrix = frame.pivot_table(
        index="faixa_at",
        columns="faixa_gu",
        values=value_column,
        aggfunc="sum",
        fill_value=0,
    )
    def category_order(value):
        label = str(value).strip()
        normalized = label.casefold()
        match = re.search(r"\d+(?:[.,]\d+)?", normalized)
        numeric = float(match.group(0).replace(",", ".")) if match else float("inf")
        if normalized.startswith(("até", "ate", "menos de", "abaixo de")):
            return (0, numeric, normalized)
        if normalized.startswith(("mais de", "acima de", "superior a")):
            return (2, numeric, normalized)
        if "não informado" in normalized or "nao informado" in normalized:
            return (3, float("inf"), normalized)
        return (1, numeric, normalized)

    # Ordenação crescente pelas categorias numéricas embutidas nos rótulos.
    matrix = matrix.reindex(
        index=sorted(matrix.index, key=category_order),
        columns=sorted(matrix.columns, key=category_order),
    )
    # Totais marginais; conservar a última linha e a última coluna para ambos
    # os formatos de saída (tabela e mapa de calor).
    matrix["Total"] = matrix.sum(axis=1)
    total_row = matrix.sum(axis=0)
    total_row.name = "Total"
    matrix = pd.concat([matrix, total_row.to_frame().T])
    display_matrix = matrix.apply(
        lambda column: column.map(lambda value: format_br_number(value, decimals))
    )
    st.dataframe(display_matrix, use_container_width=True)
    if matrix.empty or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        st.info("Não há valores para construir o mapa de calor.")
        return
    heatmap = px.imshow(
        matrix,
        labels={"x": "Faixa de GU", "y": "Faixa de área (faixa_at)", "color": value_label},
        aspect="auto",
        color_continuous_scale="YlOrRd",
        text_auto=False,
    )
    heatmap_text = matrix.apply(
        lambda column: column.map(lambda value: format_br_number(value, decimals))
    )
    heatmap.update_traces(text=heatmap_text.values, texttemplate="%{text}")
    heatmap.update_layout(title=f"Mapa de calor — {value_label}")
    st.plotly_chart(heatmap, use_container_width=True)

try:
    crosstab_data = run_query(crosstab_sql, filter_params)
    if arrecadacao_col == "itr_gu_calc":
        tab_count, tab_revenue = st.tabs(["Nº de imóveis", "Arrecadação"])
        with tab_count:
            render_crosstab(
                crosstab_data, "quantidade_imoveis", "Nº de imóveis", 0
            )
        with tab_revenue:
            render_crosstab(
                crosstab_data, "arrecadacao", "Arrecadação (R$)", 2
            )
    else:
        render_crosstab(
            crosstab_data, "quantidade_imoveis", "Nº de imóveis", 0
        )
except Exception as exc:
    st.error(f"Erro ao gerar a tabela cruzada: {exc}")

st.markdown("---")
st.subheader("Tabela detalhada")
st.caption(
    "Os resultados são consultados sob demanda e exibidos em páginas de 1.000 registros. "
    "Os cinco filtros são aplicados no BigQuery."
)
total_rows = int(kpis["quantidade_imoveis"])
page_count = max(1, (total_rows + PAGE_SIZE - 1) // PAGE_SIZE)
page = st.number_input("Página", min_value=1, max_value=page_count, value=1, step=1)
offset = (int(page) - 1) * PAGE_SIZE
columns = """uf AS `UF`,
              codigo_do_municipio_ibge AS `Código_IBGE`,
              municipio AS `Município`,
              codigo_do_imovel AS `Código do Imóvel`,
              denominacao AS `Denominação`,
              at_imovel AS `Área do imóvel`,
              itr_gu_fixo AS `Arrecadação GU Fixo`,
              itr_gu_calc AS `Arrecadação GU Calculado`"""
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
    display_page_df = page_df.copy()
    id_columns = {"Código_IBGE", "Código do Imóvel"}
    for column in display_page_df.select_dtypes(include="number").columns:
        if column not in id_columns:
            display_page_df[column] = display_page_df[column].map(
                lambda value: format_br_number(value, 2)
            )
    st.dataframe(display_page_df, use_container_width=True, hide_index=True)
    st.download_button(
        "Baixar esta página em CSV",
        data=page_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"dados_itr_pagina_{int(page)}.csv",
        mime="text/csv",
    )
except Exception as exc:
    st.error(f"Erro ao carregar a página da tabela: {exc}")
