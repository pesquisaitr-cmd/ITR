import pandas as pd
import plotly.express as px
import streamlit as st
from google.cloud import bigquery


# ============================================================
# CONFIGURAÇÃO
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

# Os valores dos campos abaixo são definidos pelo código, e não pelo usuário;
# portanto, são seguros para interpolação nas consultas SQL.
ARRECADACOES = {
    "ITR_GU_FIXO": "itr_gu_fixo",
    "ITR_GU_CALC": "itr_gu_calc",
}
ISENCOES = {
    "Não Isentos": 0,
    "Isentos": 1,
}


@st.cache_resource
def get_client():
    return bigquery.Client(project=PROJECT_ID)


def executar_consulta(query, query_parameters=None):
    client = get_client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=query_parameters or []
    )
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


def montar_filtros(uf, contagem, tamanho):
    """Gera WHERE e parâmetros para todos os relatórios."""
    condicoes = []
    parametros = []

    if uf != "Brasil":
        condicoes.append("CAST(uf AS STRING) = @uf")
        parametros.append(bigquery.ScalarQueryParameter("uf", "STRING", uf))

    # O requisito é AT IMOVEL <= 2; mantém nulos fora do recorte.
    if tamanho == "Menor que 2 hectares":
        condicoes.append("at_imovel <= @area_maxima")
        parametros.append(
            bigquery.ScalarQueryParameter("area_maxima", "FLOAT64", 2.0)
        )

    if contagem != "Todos":
        condicoes.append("Isencao = @isencao")
        parametros.append(
            bigquery.ScalarQueryParameter(
                "isencao", "INT64", ISENCOES[contagem]
            )
        )

    return (
        ("WHERE " + " AND ".join(condicoes)) if condicoes else "",
        parametros,
    )


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


# Ordem semântica das faixas. O BigQuery trata esses rótulos como texto,
# portanto ORDER BY faixa_at/faixa_gu não garante a ordem numérica desejada.
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


def ordenar_faixas(df):
    """Ordena Faixa_AT e Faixa_GU pela ordem numérica dos intervalos."""
    df = df.copy()
    if "faixa_at" in df.columns:
        df["faixa_at"] = pd.Categorical(
            df["faixa_at"].astype(str),
            categories=ORDEM_FAIXA_AT,
            ordered=True,
        )
    if "faixa_gu" in df.columns:
        df["faixa_gu"] = pd.Categorical(
            df["faixa_gu"].astype(str),
            categories=ORDEM_FAIXA_GU,
            ordered=True,
        )
    return df.sort_values(["faixa_at", "faixa_gu"], na_position="last")


@st.cache_data(ttl=900, show_spinner=False)
def carregar_resumo(uf, contagem, tamanho, campo_arrecadacao):
    where, params = montar_filtros(uf, contagem, tamanho)
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
def carregar_cruzamento(uf, contagem, tamanho, campo_arrecadacao):
    where, params = montar_filtros(uf, contagem, tamanho)
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
def carregar_resumo_uf(contagem, tamanho, campo_arrecadacao):
    where, params = montar_filtros("Brasil", contagem, tamanho)
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
def carregar_detalhada(uf, contagem, tamanho, campo_arrecadacao):
    where, params = montar_filtros(uf, contagem, tamanho)
    query = f"""
        SELECT
            uf,
            codigo_do_municipio_ibge AS codigo_ibge,
            municipio,
            at_imovel,
            area_total,
            Isencao,
            gu_fixo,
            gu_calc,
            itr_gu_fixo,
            itr_gu_calc
        FROM {TABLE_PATH}
        {where}
        LIMIT {LIMITE_TABELA_DETALHADA}
    """
    return executar_consulta(query, params)


# ============================================================
# SIDEBAR / FILTROS
# ============================================================
st.title("Dashboard de Análise do ITR")
st.caption(
    "As métricas são calculadas no BigQuery conforme os filtros selecionados."
)

with st.sidebar:
    st.header("Filtros")

    arrecadacao_label = st.selectbox(
        "Arrecadação",
        list(ARRECADACOES.keys()),
        format_func=lambda x: f"{x} — " + (
            "GU fixo" if x == "ITR_GU_FIXO" else "GU calculado"
        ),
    )
    campo_arrecadacao = ARRECADACOES[arrecadacao_label]

    contagem = st.selectbox(
        "Contagem",
        ["Todos", "Não Isentos", "Isentos"],
        help="Define a população incluída nas contagens e somas.",
    )
    tamanho = st.radio(
        "Tamanho da Propriedade",
        ["Todas", "Menor que 2 hectares"],
    )
    uf = st.selectbox("Selecione o Estado", carregar_ufs())

st.markdown(
    f"**Filtros ativos:** Arrecadação = `{arrecadacao_label}` · "
    f"Contagem = `{contagem}` · Tamanho = `{tamanho}` · Estado = `{uf}`"
)

with st.spinner("Consultando o BigQuery..."):
    resumo = carregar_resumo(uf, contagem, tamanho, campo_arrecadacao)
    cruzamento = carregar_cruzamento(
        uf, contagem, tamanho, campo_arrecadacao
    )

# ============================================================
# CARTÕES DE RESUMO
# ============================================================
col1, col2, col3, col4 = st.columns(4)
col1.metric("Contagem de imóveis", formatar_inteiro(resumo["quantidade"]))
col2.metric("Municípios", formatar_inteiro(resumo["municipios"]))
col3.metric("Área total (ha)", formatar_decimal(valor_numerico(resumo["area_total"])))
col4.metric(
    f"Arrecadação — {arrecadacao_label}",
    moeda(valor_numerico(resumo["arrecadacao"])),
)

st.divider()
st.header("Cruzamentos 2 × 2 — Faixa_AT × Faixa_GU")
st.write(
    f"A tabela apresenta a **contagem** e a **arrecadação {arrecadacao_label}** "
    "para cada combinação de faixa de área e faixa de grau de utilização."
)

if cruzamento.empty:
    st.info("Não foram encontrados dados para os filtros selecionados.")
else:
    # Tabela analítica principal, com duas medidas para cada combinação.
    tabela = ordenar_faixas(cruzamento.copy())
    tabela["arrecadacao"] = tabela["arrecadacao"].map(moeda)
    tabela["contagem"] = tabela["contagem"].map(formatar_inteiro)
    tabela = tabela.rename(
        columns={
            "faixa_at": "Faixa_AT",
            "faixa_gu": "Faixa_GU",
            "contagem": "Contagem",
            "arrecadacao": f"Arrecadação ({arrecadacao_label})",
        }
    )
    st.dataframe(tabela, use_container_width=True, hide_index=True)

    tab_contagem, tab_arrecadacao = st.tabs(["Contagem", "Arrecadação"])
    with tab_contagem:
        piv_contagem = cruzamento.pivot(
            index="faixa_at", columns="faixa_gu", values="contagem"
        ).reindex(index=ORDEM_FAIXA_AT, columns=ORDEM_FAIXA_GU).fillna(0)
        piv_contagem.index = piv_contagem.index.astype(object)
        piv_contagem.columns = piv_contagem.columns.astype(object)
        piv_contagem.index.name = "Faixa_AT"
        piv_contagem.columns.name = "Faixa_GU"
        # Totais marginais: primeiro o total de cada linha e, depois, a linha total.
        piv_contagem["Total"] = piv_contagem.sum(axis=1)
        piv_contagem.loc["Total"] = piv_contagem.sum(axis=0)
        # Envia somente strings/valores simples ao frontend; Styler pode gerar
        # JSON inválido em algumas versões do Streamlit/Pandas.
        tabela_contagem = piv_contagem.astype(int).map(formatar_inteiro)
        st.dataframe(tabela_contagem, use_container_width=True)
        fig = px.density_heatmap(
            cruzamento,
            x="faixa_gu",
            y="faixa_at",
            z="contagem",
            category_orders={"faixa_at": ORDEM_FAIXA_AT, "faixa_gu": ORDEM_FAIXA_GU},
            text_auto=True,
            color_continuous_scale="Blues",
            labels={"faixa_gu": "Faixa_GU", "faixa_at": "Faixa_AT", "contagem": "Contagem"},
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)

    with tab_arrecadacao:
        piv_arrecadacao = cruzamento.pivot(
            index="faixa_at", columns="faixa_gu", values="arrecadacao"
        ).reindex(index=ORDEM_FAIXA_AT, columns=ORDEM_FAIXA_GU).fillna(0)
        piv_arrecadacao.index = piv_arrecadacao.index.astype(object)
        piv_arrecadacao.columns = piv_arrecadacao.columns.astype(object)
        piv_arrecadacao.index.name = "Faixa_AT"
        piv_arrecadacao.columns.name = "Faixa_GU"
        # Totais marginais: total da arrecadação por Faixa_AT, por Faixa_GU
        # e total geral no canto inferior direito.
        piv_arrecadacao["Total"] = piv_arrecadacao.sum(axis=1)
        piv_arrecadacao.loc["Total"] = piv_arrecadacao.sum(axis=0)
        tabela_arrecadacao = piv_arrecadacao.map(moeda)
        st.dataframe(tabela_arrecadacao, use_container_width=True)
        fig = px.density_heatmap(
            cruzamento,
            x="faixa_gu",
            y="faixa_at",
            z="arrecadacao",
            category_orders={"faixa_at": ORDEM_FAIXA_AT, "faixa_gu": ORDEM_FAIXA_GU},
            text_auto=".2s",
            color_continuous_scale="Greens",
            labels={"faixa_gu": "Faixa_GU", "faixa_at": "Faixa_AT", "arrecadacao": "Arrecadação"},
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)

# ============================================================
# VISÃO POR UF — útil especialmente quando Brasil está selecionado
# ============================================================
if uf == "Brasil":
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
# AMOSTRA DETALHADA
# ============================================================
with st.expander(f"Ver amostra detalhada — máximo de {LIMITE_TABELA_DETALHADA} registros"):
    st.warning(
        "A amostra é limitada para preservar o desempenho; os totais são calculados no BigQuery."
    )
    if st.button("Carregar tabela detalhada"):
        with st.spinner("Carregando amostra..."):
            detalhada = carregar_detalhada(
                uf, contagem, tamanho, campo_arrecadacao
            )
        st.dataframe(detalhada, use_container_width=True, hide_index=True)

st.divider()
st.caption("Dashboard ITR | BigQuery | filtros aplicados às métricas e aos cruzamentos")
