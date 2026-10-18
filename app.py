import numpy as np
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

def formatar_texto_heatmap(val):
    if val >= 1e9:
        return f"R$ {val / 1e9:.1f}B"
    elif val >= 1e6:
        return f"R$ {val / 1e6:.0f}M"
    elif val >= 1e3:
        return f"R$ {val / 1e3:.0f}K"
    elif val > 0:
        return f"R$ {val:.0f}"
    return "R$ 0"

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
        SELECT
            uf,
            codigo_do_municipio_ibge AS codigo_ibge,
            municipio,
            codigo_do_imovel,
            denominacao,
            at_imovel,
            gu_calc,
            itr_gu_fixo,
            itr_gu_calc
        FROM {TABLE_PATH}
        {where}
        ORDER BY municipio, denominacao
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
# CRUZAMENTOS 2x2 - FAIXA_AT x FAIXA_GU
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

        piv_cont_tabela = piv_contagem.copy()
        piv_cont_tabela["Total"] = piv_cont_tabela.sum(axis=1)
        piv_cont_tabela.loc["Total"] = piv_cont_tabela.sum(axis=0)
        st.dataframe(piv_cont_tabela.astype(int).map(formatar_inteiro), use_container_width=True)

        fig_cont = px.imshow(
            piv_contagem,
            labels=dict(x="Faixa_GU", y="Faixa_AT", color="Contagem"),
            x=piv_contagem.columns,
            y=piv_contagem.index,
            color_continuous_scale="Blues",
            text_auto=True,
            aspect="auto",
        )
        fig_cont.update_layout(height=480, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig_cont, use_container_width=True)

    # ------------------ ARRECADAÇÃO (LOG10 + TEXTO PT-BR) ------------------
    with tab_arrecadacao:
        piv_arrecadacao = (
            cruzamento.pivot(index="faixa_at", columns="faixa_gu", values="arrecadacao")
            .reindex(index=ORDEM_FAIXA_AT, columns=ORDEM_FAIXA_GU)
            .fillna(0)
        )
        piv_arrecadacao.index.name = "Faixa_AT"
        piv_arrecadacao.columns.name = "Faixa_GU"

        piv_arr_tabela = piv_arrecadacao.copy()
        piv_arr_tabela["Total"] = piv_arr_tabela.sum(axis=1)
        piv_arr_tabela.loc["Total"] = piv_arr_tabela.sum(axis=0)
        st.dataframe(piv_arr_tabela.map(moeda), use_container_width=True)

        matriz_texto = piv_arrecadacao.map(formatar_texto_heatmap).values
        piv_log = np.log10(piv_arrecadacao + 1)

        fig_arr = px.imshow(
            piv_log,
            labels=dict(x="Faixa_GU", y="Faixa_AT"),
            x=piv_arrecadacao.columns,
            y=piv_arrecadacao.index,
            color_continuous_scale="Greens",
            text_auto=False,
            aspect="auto",
        )

        fig_arr.update_traces(
            text=matriz_texto,
            texttemplate="%{text}",
            textfont=dict(size=12),
        )

        fig_arr.update_layout(
            coloraxis_showscale=False,
            height=480,
            margin=dict(l=20, r=20, t=30, b=20),
        )
        st.plotly_chart(fig_arr, use_container_width=True)

# ============================================================
# COMPARAÇÃO BRASIL (Apenas quando "Brasil" está selecionado)
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
# TABELA DETALHADA COM VALIDAÇÃO DE ESTADO/MUNICÍPIO
# ============================================================
with st.expander("Tabelas detalhadas selecione um Estado e/ou Município"):
    if st.button("Carregar tabelas", key="carregar_tabelas"):
        if uf == "Brasil":
            st.warning("Selecione um Estado e/ou Município")
        else:
            with st.spinner("Carregando tabela no BigQuery..."):
                sumario_municipio = carregar_sumario_municipio(uf, municipio, contagem, tamanho, campo_arrecadacao)

            mapeamento_colunas = {
                "uf": "UF",
                "codigo_ibge": "Código IBGE",
                "municipio": "Município",
                "codigo_do_imovel": "Código do Imóvel",
                "denominacao": "Denominação",
                "at_imovel": "Área Total (ha)",
                "gu_calc": "GU Calc (%)",
                "itr_gu_fixo": "ITR GU Fixo (R$)",
                "itr_gu_calc": "ITR GU Calc (R$)"
            }

            tabela_municipio = sumario_municipio.copy()
            if not tabela_municipio.empty:
                tabela_municipio["at_imovel"] = tabela_municipio["at_imovel"].map(lambda x: formatar_decimal(valor_numerico(x)))
                tabela_municipio["gu_calc"] = tabela_municipio["gu_calc"].map(lambda x: formatar_decimal(valor_numerico(x)))
                tabela_municipio["itr_gu_fixo"] = tabela_municipio["itr_gu_fixo"].map(moeda)
                tabela_municipio["itr_gu_calc"] = tabela_municipio["itr_gu_calc"].map(moeda)
                tabela_municipio = tabela_municipio.rename(columns=mapeamento_colunas)
                
                st.dataframe(tabela_municipio, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhum registro encontrado para os filtros selecionados.")

st.divider()
st.caption("Dashboard ITR | BigQuery | Filtros dinâmicos")
