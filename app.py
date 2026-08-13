import pandas as pd
import plotly.express as px
import streamlit as st
from google.cloud import bigquery


# ============================================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================================
st.set_page_config(
    page_title="Painel de Análise ITR",
    page_icon="📊",
    layout="wide",
)


# ============================================================
# CONFIGURAÇÃO DO BIGQUERY
# ============================================================
PROJECT_ID = "pesquisa-itr"
DATASET_ID = "dados_itr"
TABLE_ID = "itr_pronto"
TABLE_PATH = f"`{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`"

# Limite de segurança para a tabela detalhada.
# A tabela completa nunca é carregada no Streamlit.
LIMITE_TABELA_DETALHADA = 500


@st.cache_resource
def get_client():
    """Cria uma única conexão BigQuery reutilizável pelo aplicativo."""
    return bigquery.Client(project=PROJECT_ID)


def executar_consulta(query, query_parameters=None):
    """Executa uma consulta parametrizada e devolve um DataFrame."""
    client = get_client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=query_parameters or []
    )
    return client.query(query, job_config=job_config).to_dataframe()


def montar_filtros(uf_selecionada, filtro_area):
    """Monta os filtros SQL e os parâmetros usados em todas as consultas."""
    condicoes = []
    parametros = []

    if uf_selecionada != "Brasil (Todos)":
        condicoes.append("uf = @uf")
        parametros.append(
            bigquery.ScalarQueryParameter(
                "uf",
                "STRING",
                uf_selecionada,
            )
        )

    if filtro_area == "Menor que 2 hectares (< 2 ha)":
        condicoes.append("at_imovel < @area_maxima")
        parametros.append(
            bigquery.ScalarQueryParameter(
                "area_maxima",
                "FLOAT64",
                2.0,
            )
        )

    if condicoes:
        where_clause = "WHERE " + " AND ".join(condicoes)
    else:
        where_clause = ""

    return where_clause, parametros


# ============================================================
# CONSULTAS CACHEADAS
# ============================================================
@st.cache_data(ttl=3600, show_spinner=False)
def carregar_ufs():
    """Carrega somente a lista de UFs, em vez de consultar toda a tabela."""
    query = f"""
        SELECT DISTINCT uf
        FROM {TABLE_PATH}
        WHERE uf IS NOT NULL
        ORDER BY uf
    """

    df_ufs = executar_consulta(query)
    ufs = df_ufs["uf"].dropna().astype(str).tolist()
    return ["Brasil (Todos)"] + ufs


@st.cache_data(ttl=900, show_spinner=False)
def carregar_resumo(uf_selecionada, filtro_area):
    """Calcula os cartões do resumo diretamente no BigQuery."""
    where_clause, parametros = montar_filtros(
        uf_selecionada,
        filtro_area,
    )

    query = f"""
        SELECT
            COUNT(*) AS total_imoveis,
            COUNT(DISTINCT municipio) AS municipios_atendidos,
            COALESCE(SUM(area_total), 0) AS area_total,
            COALESCE(SUM(itr_gu_calc), 0) AS itr_calculado_total
        FROM {TABLE_PATH}
        {where_clause}
    """

    return executar_consulta(query, parametros).iloc[0].to_dict()


@st.cache_data(ttl=900, show_spinner=False)
def carregar_top_municipios(uf_selecionada, filtro_area):
    """Calcula o ranking dos dez municípios diretamente no BigQuery."""
    where_clause, parametros = montar_filtros(
        uf_selecionada,
        filtro_area,
    )

    query = f"""
        SELECT
            municipio,
            COALESCE(SUM(itr_gu_calc), 0) AS itr_gu_calc
        FROM {TABLE_PATH}
        {where_clause}
        GROUP BY municipio
        ORDER BY itr_gu_calc DESC
        LIMIT 10
    """

    return executar_consulta(query, parametros)


@st.cache_data(ttl=900, show_spinner=False)
def carregar_distribuicao_gu(uf_selecionada, filtro_area):
    """Calcula a distribuição das faixas de grau de utilização."""
    where_clause, parametros = montar_filtros(
        uf_selecionada,
        filtro_area,
    )

    query = f"""
        SELECT
            faixa_gu,
            COUNT(*) AS quantidade
        FROM {TABLE_PATH}
        {where_clause}
        GROUP BY faixa_gu
        ORDER BY quantidade DESC
    """

    return executar_consulta(query, parametros)


@st.cache_data(ttl=900, show_spinner=False)
def carregar_distribuicao_area(uf_selecionada, filtro_area):
    """Calcula a distribuição das faixas de área total."""
    where_clause, parametros = montar_filtros(
        uf_selecionada,
        filtro_area,
    )

    query = f"""
        SELECT
            faixa_at,
            COUNT(*) AS quantidade
        FROM {TABLE_PATH}
        {where_clause}
        GROUP BY faixa_at
        ORDER BY quantidade DESC
    """

    return executar_consulta(query, parametros)


@st.cache_data(ttl=900, show_spinner=False)
def carregar_medias_aliquotas(uf_selecionada, filtro_area):
    """Calcula as médias das alíquotas no BigQuery."""
    where_clause, parametros = montar_filtros(
        uf_selecionada,
        filtro_area,
    )

    query = f"""
        SELECT
            AVG(aliquota_fixa) AS media_aliquota_fixa,
            AVG(aliquota_calc) AS media_aliquota_calc
        FROM {TABLE_PATH}
        {where_clause}
    """

    return executar_consulta(query, parametros).iloc[0].to_dict()


@st.cache_data(ttl=900, show_spinner=False)
def carregar_amostra_aliquotas(uf_selecionada, filtro_area):
    """Carrega no máximo 1.000 linhas para o gráfico de dispersão.

    A amostra é obtida no BigQuery por meio de uma condição determinística,
    evitando baixar milhões de registros para o servidor Streamlit.
    """
    where_clause, parametros = montar_filtros(
        uf_selecionada,
        filtro_area,
    )

    if where_clause:
        where_clause += " AND "
    else:
        where_clause = "WHERE "

    query = f"""
        SELECT
            codigo_do_municipio_ibge AS codigo_ibge,
            municipio,
            faixa_at,
            aliquota_fixa,
            aliquota_calc
        FROM {TABLE_PATH}
        {where_clause}
            MOD(
                ABS(
                    FARM_FINGERPRINT(
                        CONCAT(
                            COALESCE(CAST(codigo_do_municipio_ibge AS STRING), ''),
                            '|',
                            COALESCE(municipio, ''),
                            '|',
                            COALESCE(CAST(at_imovel AS STRING), '')
                        )
                    )
                ),
                100
            ) < 10
        LIMIT 1000
    """

    return executar_consulta(query, parametros)


@st.cache_data(ttl=900, show_spinner=False)
def carregar_tabela_detalhada(uf_selecionada, filtro_area):
    """Carrega apenas uma amostra limitada da tabela detalhada."""
    where_clause, parametros = montar_filtros(
        uf_selecionada,
        filtro_area,
    )

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
        LIMIT {LIMITE_TABELA_DETALHADA}
    """

    return executar_consulta(query, parametros)


# ============================================================
# FUNÇÕES AUXILIARES DE APRESENTAÇÃO
# ============================================================
def valor_numerico(valor, padrao=0.0):
    """Converte valores BigQuery para float com tratamento de nulos."""
    if valor is None or pd.isna(valor):
        return padrao
    return float(valor)


def formatar_inteiro(valor):
    return f"{int(valor):,}".replace(",", ".")


def formatar_decimal(valor, casas=2):
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


# ============================================================
# INTERFACE
# ============================================================
st.title("🌾 Painel Relatório ITR")
st.caption(
    "As métricas e os gráficos são agregados no BigQuery. "
    "O aplicativo não carrega os 5 milhões de registros para a memória do Streamlit."
)

with st.sidebar:
    st.header("Filtros")

    lista_ufs = carregar_ufs()
    uf_selecionada = st.selectbox(
        "Selecione o Estado (UF):",
        lista_ufs,
    )

    filtro_area = st.radio(
        "Tamanho da Propriedade:",
        [
            "Todas as propriedades",
            "Menor que 2 hectares (< 2 ha)",
        ],
    )

    aba = st.radio(
        "Escolha o Relatório:",
        [
            "1. Resumo Geral por UF",
            "2. Análise do Grau de Utilização (GU)",
            "3. Comparativo de Alíquotas e Imposto",
        ],
    )

if uf_selecionada:
    # --------------------------------------------------------
    # RELATÓRIO 1: RESUMO GERAL
    # --------------------------------------------------------
    if aba == "1. Resumo Geral por UF":
        st.header(f"📊 Relatório 1: Visão Geral - {uf_selecionada}")

        with st.spinner("Calculando resumo no BigQuery..."):
            resumo = carregar_resumo(
                uf_selecionada,
                filtro_area,
            )
            top_muni = carregar_top_municipios(
                uf_selecionada,
                filtro_area,
            )

        total_imoveis = valor_numerico(resumo.get("total_imoveis"))
        municipios_atendidos = valor_numerico(
            resumo.get("municipios_atendidos")
        )
        area_total = valor_numerico(resumo.get("area_total"))
        itr_calculado_total = valor_numerico(
            resumo.get("itr_calculado_total")
        )

        col1, col2, col3, col4 = st.columns(4)
        col1.metric(
            "Total de Imóveis",
            formatar_inteiro(total_imoveis),
        )
        col2.metric(
            "Municípios Atendidos",
            formatar_inteiro(municipios_atendidos),
        )
        col3.metric(
            "Área Total (ha)",
            formatar_decimal(area_total),
        )
        col4.metric(
            "ITR Calculado Total (R$)",
            f"R$ {formatar_decimal(itr_calculado_total)}",
        )

        st.markdown("---")

        if top_muni.empty:
            st.info("Não foram encontrados dados para os filtros selecionados.")
        else:
            fig_muni = px.bar(
                top_muni.sort_values("itr_gu_calc"),
                x="itr_gu_calc",
                y="municipio",
                orientation="h",
                title="Top 10 Municípios com Maior ITR Calculado",
                labels={
                    "itr_gu_calc": "ITR Calculado (R$)",
                    "municipio": "Município",
                },
                text_auto=".2s",
            )
            fig_muni.update_layout(
                yaxis={"categoryorder": "total ascending"},
                height=500,
            )
            st.plotly_chart(
                fig_muni,
                use_container_width=True,
            )

    # --------------------------------------------------------
    # RELATÓRIO 2: GRAU DE UTILIZAÇÃO
    # --------------------------------------------------------
    elif aba == "2. Análise do Grau de Utilização (GU)":
        st.header(
            "🚜 Relatório 2: Distribuição por Grau de Utilização (GU)"
        )

        with st.spinner("Calculando distribuições no BigQuery..."):
            gu_counts = carregar_distribuicao_gu(
                uf_selecionada,
                filtro_area,
            )
            at_counts = carregar_distribuicao_area(
                uf_selecionada,
                filtro_area,
            )

        if gu_counts.empty and at_counts.empty:
            st.info("Não foram encontrados dados para os filtros selecionados.")
        else:
            col1, col2 = st.columns(2)

            with col1:
                if gu_counts.empty:
                    st.info("Não há dados de faixa GU para os filtros selecionados.")
                else:
                    fig_pie = px.pie(
                        gu_counts,
                        names="faixa_gu",
                        values="quantidade",
                        title="Distribuição dos Imóveis por Faixa de GU",
                        hole=0.30,
                    )
                    st.plotly_chart(
                        fig_pie,
                        use_container_width=True,
                    )

            with col2:
                if at_counts.empty:
                    st.info("Não há dados de faixa de área para os filtros selecionados.")
                else:
                    fig_bar = px.bar(
                        at_counts,
                        x="faixa_at",
                        y="quantidade",
                        title="Distribuição dos Imóveis por Tamanho de Área (AT)",
                        labels={
                            "faixa_at": "Faixa Área Total",
                            "quantidade": "Quantidade",
                        },
                        text_auto=True,
                    )
                    fig_bar.update_layout(height=500)
                    st.plotly_chart(
                        fig_bar,
                        use_container_width=True,
                    )

    # --------------------------------------------------------
    # RELATÓRIO 3: ALÍQUOTAS E IMPOSTO
    # --------------------------------------------------------
    elif aba == "3. Comparativo de Alíquotas e Imposto":
        st.header(
            "💰 Relatório 3: Comparativo de Alíquotas "
            "(Fixo vs Calculado)"
        )

        with st.spinner("Calculando alíquotas no BigQuery..."):
            medias = carregar_medias_aliquotas(
                uf_selecionada,
                filtro_area,
            )
            df_amostra = carregar_amostra_aliquotas(
                uf_selecionada,
                filtro_area,
            )

        media_fixa = valor_numerico(
            medias.get("media_aliquota_fixa")
        )
        media_calculada = valor_numerico(
            medias.get("media_aliquota_calc")
        )

        col1, col2 = st.columns(2)
        col1.metric(
            "Média Alíquota Fixa",
            f"{formatar_decimal(media_fixa)}%",
        )
        col2.metric(
            "Média Alíquota Calculada",
            f"{formatar_decimal(media_calculada)}%",
        )

        st.markdown("---")

        if df_amostra.empty:
            st.info("Não foram encontrados dados para os filtros selecionados.")
        else:
            fig_comp = px.scatter(
                df_amostra,
                x="aliquota_fixa",
                y="aliquota_calc",
                color="faixa_at",
                hover_data=["municipio", "codigo_ibge"],
                title="Dispersão: Alíquota Fixa vs Alíquota Calculada",
                labels={
                    "aliquota_fixa": "Alíquota Fixa (%)",
                    "aliquota_calc": "Alíquota Calculada (%)",
                    "faixa_at": "Faixa de Área",
                },
                opacity=0.70,
            )
            fig_comp.update_layout(height=600)
            st.plotly_chart(
                fig_comp,
                use_container_width=True,
            )

            st.caption(
                f"O gráfico utiliza uma amostra de até {len(df_amostra):,} "
                "registros obtida diretamente no BigQuery."
            )

    # --------------------------------------------------------
    # TABELA DETALHADA LIMITADA
    # --------------------------------------------------------
    with st.expander(
        f"Ver amostra da tabela detalhada "
        f"(máximo de {LIMITE_TABELA_DETALHADA} registros)"
    ):
        st.warning(
            "Para preservar o desempenho, esta seção exibe somente uma "
            f"amostra de até {LIMITE_TABELA_DETALHADA} registros."
        )

        if st.button("Carregar tabela detalhada", key="carregar_detalhada"):
            with st.spinner("Carregando amostra da tabela detalhada..."):
                df_detalhada = carregar_tabela_detalhada(
                    uf_selecionada,
                    filtro_area,
                )
            st.dataframe(
                df_detalhada,
                use_container_width=True,
                hide_index=True,
            )
else:
    st.info("Selecione uma UF para iniciar a análise.")


# ============================================================
# RODAPÉ
# ============================================================
st.markdown("---")
st.caption(
    "Dashboard ITR | Consultas agregadas e cacheadas no BigQuery | "
    "Versão otimizada"
)
# Fim do arquivo
