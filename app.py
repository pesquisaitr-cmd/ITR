import pandas as pd
import plotly.express as px
import streamlit as st
from google.cloud import bigquery

# ============================================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================================
st.set_page_config(
    page_title="Dashboard ITR",
    page_icon="📊",
    layout="wide",
)

PROJECT_ID = "pesquisa-itr"
DATASET_ID = "dados_itr"
TABLE_ID = "itr_pronto"
TABLE_PATH = f"`{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`"
LIMITE_TABELA_DETALHADA = 500

ARRECADACOES = {
    "ITR_GU_FIXO": "GREATEST(itr_gu_fixo, 10.00)",
    "ITR_GU_CALC": "GREATEST(itr_gu_calc, 10.00)",
}
ISENCOES = {
    "Pagantes": 0,
    "Isentos": 1,
}

ORDEM_FAIXA_AT = [
    "Até 50",
    "50+ até 200",
    "200+ até 500",
    "500+ até 1.000",
    "1.000+ até 5.000",
    "Acima de 5.000",
]
ORDEM_FAIXA_GU = [
    "Até 30",
    "30+ até 50",
    "50+ até 65",
    "65+ até 80",
    "80+",
]

# ============================================================
# FUNÇÕES DE CONEXÃO E CONSULTA
# ============================================================
@st.cache_resource
def get_client():
    return bigquery.Client(project=PROJECT_ID)

def executar_consulta(query, query_parameters=None):
    client = get_client()
    job_config = bigquery.QueryJobConfig(query_parameters=query_parameters or [])
    return client.query(query, job_config=job_config).to_dataframe()

@st.cache_data(ttl=3600, show_spinner=False)
def carregar_ufs():
    query = f"""
        SELECT DISTINCT CAST(uf AS STRING) AS uf
        FROM {TABLE_PATH}
        WHERE uf IS NOT NULL
        ORDER BY uf
    """
    df = executar_consulta(query)
    return ["Brasil"] + df["uf"].dropna().astype(str).tolist()

@st.cache_data(ttl=3600, show_spinner=False)
def carregar_municipios(uf):
    where_clause = ""
    params = []
    if uf != "Brasil":
        where_clause = "WHERE CAST(uf AS STRING) = @uf AND municipio IS NOT NULL"
        params.append(bigquery.ScalarQueryParameter("uf", "STRING", uf))
    else:
        where_clause = "WHERE municipio IS NOT NULL"

    query = f"""
        SELECT DISTINCT CAST(municipio AS STRING) AS municipio
        FROM {TABLE_PATH}
        {where_clause}
        ORDER BY municipio
    """
    df = executar_consulta(query, params)
    return ["Todos"] + df["municipio"].dropna().astype(str).tolist()

def montar_filtros(uf, municipio, contagem, tamanho):
    condicoes = []
    parametros = []

    if uf != "Brasil":
        condicoes.append("CAST(uf AS STRING) = @uf")
        parametros.append(bigquery.ScalarQueryParameter("uf", "STRING", uf))

    if municipio != "Todos":
        condicoes.append("CAST(municipio AS STRING) = @municipio")
        parametros.append(bigquery.ScalarQueryParameter("municipio", "STRING", municipio))

    if tamanho == "Menos que 0,5 hectare":
        condicoes.append("at_imovel < @area_maxima")
        parametros.append(bigquery.ScalarQueryParameter("area_maxima", "FLOAT64", 0.5))
    elif tamanho == "Até 2 hectares":
        condicoes.append("at_imovel <= @area_maxima")
        parametros.append(bigquery.ScalarQueryParameter("area_maxima", "FLOAT64", 2.0))

    if contagem != "Todos":
        condicoes.append("Isencao = @isencao")
        parametros.append(bigquery.ScalarQueryParameter("isencao", "INT64", ISENCOES[contagem]))

    return (("WHERE " + " AND ".join(condicoes)) if condicoes else "", parametros)

# ============================================================
# FORMATADORES
# ============================================================
def valor_numerico(valor, padrao=0.0):
    if valor is None or pd.isna(valor):
        return padrao
    return float(valor)

def formatar_inteiro(valor):
    return f"{int(round(valor)):,}".replace(",", ".")

def formatar_decimal(valor, casas=2):
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")

def moeda(valor):
    return f"R$ {formatar_decimal(valor)}"

def formatar_resumido_br(num):
    """Formata grandes números para exibição limpa em gráficos (ex: 1,2M, 250k)."""
    if num >= 1_000_000:
        return f"{num / 1_000_000:.2f}M".replace(".", ",")
    elif num >= 1_000:
        return f"{num / 1_000:.1f}k".replace(".", ",")
    return str(int(num))

def ordenar_faixas(df):
    df = df.copy()
    if "faixa_at" in df.columns:
        df["faixa_at"] = pd.Categorical(df["faixa_at"].astype(str), categories=ORDEM_FAIXA_AT, ordered=True)
    if "faixa_gu" in df.columns:
        df["faixa_gu"] = pd.Categorical(df["faixa_gu"].astype(str), categories=ORDEM_FAIXA_GU, ordered=True)
    return df.sort_values(["faixa_at", "faixa_gu"], na_position="last")

# ============================================================
# CONSULTAS CACHEADAS
# ============================================================
@st.cache_data(ttl=900, show_spinner=False)
def carregar_resumo(uf, municipio, contagem, tamanho, campo_arrecadacao):
    where, params = montar_filtros(uf, municipio, contagem, tamanho)
    query = f"""
        SELECT
            COUNT(*) AS quantidade,
            COUNT(DISTINCT municipio) AS municipios,
            COALESCE(SUM(area_total), 0) AS area_total,
            COALESCE(SUM({campo_arrecadacao}), 0) AS arrecadacao
        FROM {TABLE_PATH}
        {where}
    """
    return executar_consulta(query, params).iloc[0].to_dict()

@st.cache_data(ttl=900, show_spinner=False)
def carregar_cruzamento(uf, municipio, contagem, tamanho, campo_arrecadacao):
    where, params = montar_filtros(uf, municipio, contagem, tamanho)
    query = f"""
        SELECT
            CAST(faixa_at AS STRING) AS faixa_at,
            CAST(faixa_gu AS STRING) AS faixa_gu,
            COUNT(*) AS contagem,
            COALESCE(SUM({campo_arrecadacao}), 0) AS arrecadacao
        FROM {TABLE_PATH}
        {where}
        GROUP BY faixa_at, faixa_gu
        ORDER BY faixa_at, faixa_gu
    """
    return ordenar_faixas(executar_consulta(query, params))

@st.cache_data(ttl=900, show_spinner=False)
def carregar_cruzamento_uf_at(uf, municipio, contagem, tamanho, campo_arrecadacao):
    where, params = montar_filtros(uf, municipio, contagem, tamanho)
    query = f"""
        SELECT
            CAST(uf AS STRING) AS uf,
            CAST(faixa_at AS STRING) AS faixa_at,
            COUNT(*) AS contagem,
            COALESCE(SUM({campo_arrecadacao}), 0) AS arrecadacao
        FROM {TABLE_PATH}
        {where}
        GROUP BY uf, faixa_at
        ORDER BY uf, faixa_at
    """
    return executar_consulta(query, params)

@st.cache_data(ttl=900, show_spinner=False)
def carregar_resumo_uf(contagem, tamanho, campo_arrecadacao):
    where, params = montar_filtros("Brasil", "Todos", contagem, tamanho)
    query = f"""
        SELECT
            CAST(uf AS STRING) AS uf,
            COUNT(*) AS contagem,
            COALESCE(SUM({campo_arrecadacao}), 0) AS arrecadacao
        FROM {TABLE_PATH}
        {where}
        GROUP BY uf
        ORDER BY arrecadacao DESC
    """
    return executar_consulta(query, params)

@st.cache_data(ttl=900, show_spinner=False)
def carregar_sumario_municipio(uf, municipio, contagem, tamanho, campo_arrecadacao):
    where, params = montar_filtros(uf, municipio, contagem, tamanho)
    query = f"""
        WITH base AS (
            SELECT
                CAST(uf AS STRING) AS uf,
                codigo_do_municipio_ibge AS codigo_ibge,
                CAST(municipio AS STRING) AS municipio,
                area_total,
                {campo_arrecadacao} AS arrecadacao
            FROM {TABLE_PATH}
            {where}
        ),
        areas_municipios AS (
            SELECT uf, codigo_ibge, ANY_VALUE(municipio) AS municipio, ANY_VALUE(area_total) AS area_total
            FROM base GROUP BY uf, codigo_ibge
        ),
        metricas AS (
            SELECT uf, codigo_ibge, COUNT(*) AS contagem, COALESCE(SUM(arrecadacao), 0) AS arrecadacao
            FROM base GROUP BY uf, codigo_ibge
        )
        SELECT m.uf, a.municipio, m.contagem, COALESCE(a.area_total, 0) AS area_total, m.arrecadacao
        FROM metricas AS m
        LEFT JOIN areas_municipios AS a USING (uf, codigo_ibge)
        ORDER BY m.arrecadacao DESC, a.municipio
    """
    return executar_consulta(query, params)

@st.cache_data(ttl=900, show_spinner=False)
def carregar_sumario_uf(uf, municipio, contagem, tamanho, campo_arrecadacao):
    where, params = montar_filtros(uf, municipio, contagem, tamanho)
    query = f"""
        WITH base AS (
            SELECT
                CAST(uf AS STRING) AS uf,
                codigo_do_municipio_ibge AS codigo_ibge,
                CAST(municipio AS STRING) AS municipio,
                area_total,
                {campo_arrecadacao} AS arrecadacao
            FROM {TABLE_PATH}
            {where}
        ),
        areas_municipios AS (
            SELECT uf, codigo_ibge, ANY_VALUE(area_total) AS area_total
            FROM base GROUP BY uf, codigo_ibge
        ),
        metricas_uf AS (
            SELECT uf, COUNT(*) AS contagem, COALESCE(SUM(arrecadacao), 0) AS arrecadacao
            FROM base GROUP BY uf
        ),
        areas_uf AS (
            SELECT uf, COALESCE(SUM(area_total), 0) AS area_total
            FROM areas_municipios GROUP BY uf
        )
        SELECT m.uf, m.contagem, COALESCE(a.area_total, 0) AS area_total, m.arrecadacao
        FROM metricas_uf AS m
        LEFT JOIN areas_uf AS a USING (uf)
        ORDER BY m.arrecadacao DESC, m.uf
    """
    return executar_consulta(query, params)

@st.cache_data(ttl=900, show_spinner=False)
def carregar_detalhada(uf, municipio, contagem, tamanho, campo_arrecadacao):
    where, params = montar_filtros(uf, municipio, contagem, tamanho)
    query = f"""
        SELECT
            uf, codigo_do_municipio_ibge AS codigo_ibge, municipio,
            at_imovel, area_total, Isencao, gu_fixo, gu_calc, itr_gu_fixo, itr_gu_calc
        FROM {TABLE_PATH}
        {where}
        LIMIT {LIMITE_TABELA_DETALHADA}
    """
    return executar_consulta(query, params)

# ============================================================
# SIDEBAR
# ============================================================
st.title("Dashboard Análise do ITR - PROPRIEDADES")
st.caption("As métricas são calculadas conforme os filtros selecionados.")

with st.sidebar:
    st.header("Filtros")

    arrecadacao_label = st.selectbox(
        "Arrecadação",
        list(ARRECADACOES.keys()),
        format_func=lambda x: f"{x} — " + ("GU fixo" if x == "ITR_GU_FIXO" else "GU calculated"),
    )
    campo_arrecadacao = ARRECADACOES[arrecadacao_label]

    contagem = st.selectbox(
        "Elegíveis",
        ["Todos", "Pagantes", "Isentos"],
        help="Define a população incluída nas contagens e somas.",
    )

    tamanho = st.radio(
        "Tamanho da Propriedade",
        ["Todas", "Menos que 0,5 hectare", "Até 2 hectares"],
    )

    uf = st.selectbox("Selecione o Estado", carregar_ufs())
    municipios_disponiveis = carregar_municipios(uf)
    municipio = st.selectbox("Por Município", municipios_disponiveis)

st.markdown(
    f"**Filtros ativos:** Arrecadação = `{arrecadacao_label}` · "
    f"Contagem = `{contagem}` · Tamanho = `{tamanho}` · Estado = `{uf}` · Município = `{municipio}`"
)

with st.spinner("Consultando o BigQuery..."):
    resumo = carregar_resumo(uf, municipio, contagem, tamanho, campo_arrecadacao)
    cruzamento = carregar_cruzamento(uf, municipio, contagem, tamanho, campo_arrecadacao)
    cruzamento_uf_at = carregar_cruzamento_uf_at(uf, municipio, contagem, tamanho, campo_arrecadacao)

# ============================================================
# METRIC CARDS
# ============================================================
col1, col2, col3, col4 = st.columns(4)
col1.metric("Contagem de imóveis", formatar_inteiro(resumo["quantidade"]))
col2.metric("Municípios", formatar_inteiro(resumo["municipios"]))
col3.metric("Área total (ha)", formatar_decimal(valor_numerico(resumo["area_total"])))
col4.metric(f"Arrecadação — {arrecadacao_label}", moeda(valor_numerico(resumo["arrecadacao"])))

st.divider()

# ============================================================
# MATRIZ UF x FAIXA_AT
# ============================================================
st.header("Distribuição por UF e Faixa de Área (Faixa_AT)")
st.write("Visualização detalhada por Estado cruzando com as faixas de área total da propriedade.")

if cruzamento_uf_at.empty:
    st.info("Não foram encontrados dados para a tabela UF × Faixa_AT com os filtros atuais.")
else:
    tab_matriz_contagem, tab_matriz_arrecadacao = st.tabs(["Contagem", "Arrecadação"])
    cols_existentes_at = [c for c in ORDEM_FAIXA_AT if c in cruzamento_uf_at["faixa_at"].unique()]

    with tab_matriz_contagem:
        piv_uf_cont = (
            cruzamento_uf_at.pivot(index="uf", columns="faixa_at", values="contagem")
            .reindex(columns=cols_existentes_at)
            .fillna(0)
        )
        piv_uf_cont["TOTAL"] = piv_uf_cont.sum(axis=1)
        piv_uf_cont.loc["TOTAL"] = piv_uf_cont.sum(axis=0)
        piv_uf_cont.index.name = "UF"
        tabela_uf_cont_fmt = piv_uf_cont.astype(int).map(formatar_inteiro)
        st.dataframe(tabela_uf_cont_fmt, use_container_width=True)

    with tab_matriz_arrecadacao:
        piv_uf_arr = (
            cruzamento_uf_at.pivot(index="uf", columns="faixa_at", values="arrecadacao")
            .reindex(columns=cols_existentes_at)
            .fillna(0)
        )
        piv_uf_arr["TOTAL"] = piv_uf_arr.sum(axis=1)
        piv_uf_arr.loc["TOTAL"] = piv_uf_arr.sum(axis=0)
        piv_uf_arr.index.name = "UF"
        tabela_uf_arr_fmt = piv_uf_arr.map(moeda)
        st.dataframe(tabela_uf_arr_fmt, use_container_width=True)

st.divider()

# ============================================================
# CRUZAMENTOS 2x2 - FAIXA_AT x FAIXA_GU (REFINADO)
# ============================================================
st.header("Cruzamentos 2 × 2 — Faixa_AT × Faixa_GU")
st.write("Visão detalhada do cruzamento de faixas de área e grau de utilização.")

if cruzamento.empty:
    st.info("Não foram encontrados dados para os filtros selecionados.")
else:
    tab_contagem, tab_arrecadacao = st.tabs(["Contagem", "Arrecadação"])

    # ------------------ CONTAGEM ------------------
    with tab_contagem:
        piv_contagem = (
            cruzamento.pivot(index="faixa_at", columns="faixa_gu", values="contagem")
            .reindex(index=ORDEM_FAIXA_AT, columns=ORDEM_FAIXA_GU)
            .fillna(0)
        )
        piv_contagem.index.name = "Faixa_AT"
        piv_contagem.columns.name = "Faixa_GU"
        
        # Exibição Tabela com Totais
        piv_contagem_tabela = piv_contagem.copy()
        piv_contagem_tabela["Total"] = piv_contagem_tabela.sum(axis=1)
        piv_contagem_tabela.loc["Total"] = piv_contagem_tabela.sum(axis=0)
        st.dataframe(piv_contagem_tabela.astype(int).map(formatar_inteiro), use_container_width=True)

        # Gráfico Heatmap Ajustado (Rótulos Limpos + Escala de Cores Ajustada)
        df_plot_cont = cruzamento.copy()
        df_plot_cont["texto_rotulo"] = df_plot_cont["contagem"].apply(formatar_resumido_br)

        fig_cont = px.density_heatmap(
            df_plot_cont,
            x="faixa_gu",
            y="faixa_at",
            z="contagem",
            category_orders={"faixa_at": ORDEM_FAIXA_AT, "faixa_gu": ORDEM_FAIXA_GU},
            text_auto=False,
            color_continuous_scale="Blues",
            labels={"faixa_gu": "Faixa_GU", "faixa_at": "Faixa_AT", "contagem": "Contagem"},
        )
        
        # Injeção dos rótulos formatados em PT-BR
        fig_cont.update_traces(
            text=df_plot_cont.pivot(index="faixa_at", columns="faixa_gu", values="texto_rotulo")
            .reindex(index=ORDEM_FAIXA_AT, columns=ORDEM_FAIXA_GU).values,
            texttemplate="%{text}",
            textfont={"size": 13, "color": "black"},
        )
        fig_cont.update_layout(height=520, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig_cont, use_container_width=True)

    # ------------------ ARRECADAÇÃO ------------------
    with tab_arrecadacao:
        piv_arrecadacao = (
            cruzamento.pivot(index="faixa_at", columns="faixa_gu", values="arrecadacao")
            .reindex(index=ORDEM_FAIXA_AT, columns=ORDEM_FAIXA_GU)
            .fillna(0)
        )
        piv_arrecadacao.index.name = "Faixa_AT"
        piv_arrecadacao.columns.name = "Faixa_GU"
        
        # Exibição Tabela com Totais
        piv_arr_tabela = piv_arrecadacao.copy()
        piv_arr_tabela["Total"] = piv_arr_tabela.sum(axis=1)
        piv_arr_tabela.loc["Total"] = piv_arr_tabela.sum(axis=0)
        st.dataframe(piv_arr_tabela.map(moeda), use_container_width=True)

        # Heatmap de Arrecadação
        df_plot_arr = cruzamento.copy()
        df_plot_arr["texto_rotulo"] = df_plot_arr["arrecadacao"].apply(moeda)

        fig_arr = px.density_heatmap(
            df_plot_arr,
            x="faixa_gu",
            y="faixa_at",
            z="arrecadacao",
            category_orders={"faixa_at": ORDEM_FAIXA_AT, "faixa_gu": ORDEM_FAIXA_GU},
            color_continuous_scale="Greens",
            labels={"faixa_gu": "Faixa_GU", "faixa_at": "Faixa_AT", "arrecadacao": "Arrecadação"},
        )
        fig_arr.update_traces(
            text=df_plot_arr.pivot(index="faixa_at", columns="faixa_gu", values="texto_rotulo")
            .reindex(index=ORDEM_FAIXA_AT, columns=ORDEM_FAIXA_GU).values,
            texttemplate="%{text}",
            textfont={"size": 11},
        )
        fig_arr.update_layout(height=520, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig_arr, use_container_width=True)

# ============================================================
# COMPARAÇÃO UF (QUANDO BRASIL É SELECIONADO)
# ============================================================
if uf == "Brasil" and municipio == "Todos":
    st.divider()
    st.header("Brasil — comparação entre as UFs")
    por_uf = carregar_resumo_uf(contagem, tamanho, campo_arrecadacao)
    if not por_uf.empty:
        c1, c2 = st.columns(2)
        with c1:
            fig = px.bar(
                por_uf.sort_values("contagem"),
                x="contagem",
                y="uf",
                orientation="h",
                title="Contagem de imóveis por UF",
                labels={"contagem": "Contagem", "uf": "UF"},
                text_auto=True,
            )
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.bar(
                por_uf.sort_values("arrecadacao"),
                x="arrecadacao",
                y="uf",
                orientation="h",
                title=f"Arrecadação {arrecadacao_label} por UF",
                labels={"arrecadacao": "Arrecadação (R$)", "uf": "UF"},
                text_auto=".2s",
            )
            st.plotly_chart(fig, use_container_width=True)

# ============================================================
# TABELAS DETALHADAS
# ============================================================
with st.expander("Tabelas detalhadas e sumarizadas"):
    st.warning("A tabela por código IBGE é uma amostra limitada; os totais sumarizados são calculados no BigQuery.")
    if st.button("Carregar tabelas", key="carregar_tabelas"):
        with st.spinner("Carregando tabelas no BigQuery..."):
            detalhada = carregar_detalhada(uf, municipio, contagem, tamanho, campo_arrecadacao)
            sumario_municipio = carregar_sumario_municipio(uf, municipio, contagem, tamanho, campo_arrecadacao)
            sumario_uf = pd.DataFrame() if municipio != "Todos" else carregar_sumario_uf(uf, municipio, contagem, tamanho, campo_arrecadacao)

        tab_ibge, tab_municipio, tab_uf = st.tabs(["Por código IBGE", "Por município", "Por UF"])
        
        with tab_ibge:
            st.caption(f"Amostra de até {LIMITE_TABELA_DETALHADA} registros.")
            st.dataframe(detalhada, use_container_width=True, hide_index=True)

        with tab_municipio:
            tabela_municipio = sumario_municipio.copy()
            tabela_municipio["contagem"] = tabela_municipio["contagem"].map(formatar_inteiro)
            tabela_municipio["area_total"] = tabela_municipio["area_total"].map(lambda x: formatar_decimal(valor_numerico(x)))
            tabela_municipio["arrecadacao"] = tabela_municipio["arrecadacao"].map(moeda)
            tabela_municipio = tabela_municipio.rename(
                columns={
                    "uf": "UF",
                    "municipio": "Município",
                    "contagem": "Contagem",
                    "area_total": "Área total (ha)",
                    "arrecadacao": f"Arrecadação ({arrecadacao_label})",
                }
            )
            st.dataframe(tabela_municipio, use_container_width=True, hide_index=True)

        with tab_uf:
            if municipio != "Todos":
                st.info("Aba indisponível quando um município específico está selecionado.")
            else:
                tabela_uf = sumario_uf.copy()
                tabela_uf["contagem"] = tabela_uf["contagem"].map(formatar_inteiro)
                tabela_uf["area_total"] = tabela_uf["area_total"].map(lambda x: formatar_decimal(valor_numerico(x)))
                tabela_uf["arrecadacao"] = tabela_uf["arrecadacao"].map(moeda)
                tabela_uf = tabela_uf.rename(
                    columns={
                        "uf": "UF",
                        "contagem": "Contagem",
                        "area_total": "Área total (ha)",
                        "arrecadacao": f"Arrecadação ({arrecadacao_label})",
                    }
                )
                st.dataframe(tabela_uf, use_container_width=True, hide_index=True)

st.divider()
st.caption("Dashboard ITR | BigQuery | Filtros dinâmicos")
