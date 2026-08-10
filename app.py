import streamlit as st
import pandas as pd
import numpy as np
import os

# ==========================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==========================================
st.set_page_config(
    page_title="Painel ITR - Pesquisa e Estatísticas",
    page_icon="🌾",
    layout="wide"
)

st.title("🌾 Painel de Análise e Estatísticas do ITR")
st.markdown("Consulta e análise estatística de alíquotas, áreas e distribuição por UF/Município.")

# ==========================================
# 2. CARREGAMENTO DOS DADOS (LEITURA DO PARQUET)
# ==========================================
@st.cache_data
def carregar_dados():
    # 1. Se estiver no Colab, monta o Google Drive
    if IN_COLAB:
        if not os.path.exists('/content/drive'):
            drive.mount('/content/drive')
        caminho_parquet = '/content/drive/MyDrive/ENTRADAS ITR/ITR_PRONTO.parquet'
    
    # 2. Se estiver rodando no GCP / Cloud Run / Servidor Externo
    else:
        # Lê o arquivo vindo do repositório ou diretório local do container
        caminho_parquet = 'ITR_PRONTO.parquet'
        
    df = pd.read_parquet(caminho_parquet)
    return df
df = carregar_dados()
# ==========================================
# 3. FUNÇÕES ESTATÍSTICAS E PROCESSAMENTO
# ==========================================
def gerar_metricas_uf(df_input):
    """Gera contagem por UF, filtro < 2ha e matriz por faixas de área."""
    bins = [-np.inf, 50, 200, 500, 1000, 5000, np.inf]
    labels = ['Até 50', '50 até 200', '200 até 500', '500 até 1.000', '1.000 até 5.000', 'Acima de 5.000']
    
    # 1. Total de propriedades por UF
    propriedades_por_uf = df_input.groupby('UF').size().reset_index(name='Total Propriedades')

    # 2. Propriedades com AT IMÓVEL < 2 ha por UF
    menor_que_2_por_uf = (
        df_input[df_input['AT IMÓVEL'] < 2]
        .groupby('UF')
        .size()
        .reset_index(name='Qtd < 2 ha')
    )

    # 3. Tabela Pivotada por Faixa de Área
    df_temp = df_input.copy()
    df_temp['Faixa Área'] = pd.cut(df_temp['AT IMÓVEL'], bins=bins, labels=labels)
    
    agrupado = df_temp.groupby(['UF', 'Faixa Área'], observed=False).size().reset_index(name='Qtde')
    tabela_faixas = agrupado.pivot(index='UF', columns='Faixa Área', values='Qtde').fillna(0).astype(int)
    
    tabela_faixas = tabela_faixas[labels]
    tabela_faixas['TOTAL'] = tabela_faixas.sum(axis=1)

    # Consolida resumo
    resumo_uf = pd.merge(propriedades_por_uf, menor_que_2_por_uf, on='UF', how='left').fillna(0)
    resumo_uf['Qtd < 2 ha'] = resumo_uf['Qtd < 2 ha'].astype(int)

    return resumo_uf, tabela_faixas

# ==========================================
# 4. EXECUÇÃO PRINCIPAL DO DASHBOARD
# ==========================================
try:
    df = carregar_dados()

    # --- BARRA LATERAL (FILTROS) ---
    st.sidebar.header("🔍 Filtros de Pesquisa")
    
    # Filtro de UF
    if "UF" in df.columns:
        ufs = ["Todas"] + sorted(list(df["UF"].dropna().unique()))
        uf_selecionada = st.sidebar.selectbox("Selecione a UF:", ufs)
        if uf_selecionada != "Todas":
            df = df[df["UF"] == uf_selecionada]

    # Filtro de Município
    if "Municipio" in df.columns:
        municipios = ["Todos"] + sorted(list(df["Municipio"].dropna().unique()))
        municipio_selecionado = st.sidebar.selectbox("Selecione o Município:", municipios)
        if municipio_selecionado != "Todos":
            df = df[df["Municipio"] == municipio_selecionado]

    # --- INDICADORES TOPO (KPIs) ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total de Imóveis", f"{len(df):,}".replace(",", "."))
    with col2:
        if "AT IMÓVEL" in df.columns:
            st.metric("Área Total (ha)", f"{df['AT IMÓVEL'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    with col3:
        if "Alíquota_fixa" in df.columns:
            st.metric("Média Alíquota Fixa", f"{df['Alíquota_fixa'].mean() * 100:.2f}%")
    with col4:
        if "Alíquota_calc" in df.columns:
            st.metric("Média Alíquota Calc", f"{df['Alíquota_calc'].mean() * 100:.2f}%")

    st.markdown("---")

    # --- PROCESSAMENTO DAS VISÕES ---
    resumo_uf, tabela_faixas = gerar_metricas_uf(df)

    # --- ABA DE VISUALIZAÇÃO DA DISTRIBUIÇÃO ---
    st.header("📊 Distribuição de Propriedades por UF e Área")

    c1, c2 = st.columns([1, 2])
    with c1:
        st.subheader("Resumo por UF")
        st.dataframe(resumo_uf, use_container_width=True, hide_index=True)

    with c2:
        st.subheader("Propriedades < 2 ha por UF")
        st.bar_chart(resumo_uf.set_index('UF')['Qtd < 2 ha'])

    st.markdown("---")

    st.subheader("Número de Propriedades: UF por Faixa de Área (AT IMÓVEL)")
    st.dataframe(tabela_faixas, use_container_width=True)

    # Botão de download
    st.download_button(
        label="📥 Baixar Tabela por Faixas em CSV",
        data=tabela_faixas.to_csv().encode('utf-8'),
        file_name="propriedades_por_faixa_uf.csv",
        mime="text/csv"
    )

except FileNotFoundError:
    st.error("⚠️ O arquivo `ITR_PRONTO.parquet` não foi encontrado no caminho especificado do Google Drive.")
except Exception as e:
    st.error(f"⚠️ Ocorreu um erro ao carregar/processar os dados: {e}")
