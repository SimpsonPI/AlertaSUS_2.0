import streamlit as st

st.title("Painel Ativado com Sucesso!")
st.write("Este é o seu novo dashboard Streamlit.")
opcao = st.selectbox("Escolha uma opção:", ["Opção A", "Opção B"])
st.write(f"Você selecionou: {opcao}")
import streamlit as st
import pandas as pd
from supabase import create_client, Client

# 1. Configuração da Página
st.set_page_config(
    page_title="AlertaSUS 2.0 - Painel",
    page_icon="🏥",
    layout="wide"
)

# 2. Conexão com o Supabase
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_supabase()
except Exception as e:
    st.error(f"Erro ao conectar no Supabase: {e}")
    st.stop()

# 3. Busca e Tratamento dos Dados
@st.cache_data(ttl=30)
def carregar_dados():
    # Substitua 'regulacoes' abaixo caso o nome da tabela no menu esquerdo do Supabase seja outro
    response = supabase.table("AlertaSUS_2.0").select("*").execute()
    df = pd.DataFrame(response.data)

    if not df.empty:
        # Formatação das datas para o padrão brasileiro DD/MM/AAAA
        if "data_nascimento" in df.columns:
            df["data_nascimento"] = pd.to_datetime(df["data_nascimento"], errors="coerce").dt.strftime("%d/%m/%Y")
        
        if "created_at" in df.columns:
            df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M")

    return df

# --- TÍTULO E BOTÃO DE ATUALIZAR ---
st.title("🏥 AlertaSUS 2.0 — Painel de Pacientes")

col_btn1, col_btn2 = st.columns([8, 2])
with col_btn2:
    if st.button("🔄 Atualizar Dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

df = carregar_dados()

if df.empty:
    st.warning("Nenhum registro encontrado ou a tabela está sem permissão de leitura (RLS).")
else:
    # --- INDICADORES (KPIs) ---
    st.markdown("---")
    kpi1, kpi2, kpi3 = st.columns(3)
    
    kpi1.metric("Total de Registros", len(df))
    kpi2.metric("Pacientes Únicos", df["nome_paciente"].nunique() if "nome_paciente" in df.columns else 0)
    kpi3.metric("Números de Regulação", df["numero_reg"].nunique() if "numero_reg" in df.columns else 0)

    # --- FILTROS DE BUSCA ---
    st.sidebar.header("🔍 Filtros")
    busca_nome = st.sidebar.text_input("Buscar por Nome do Paciente:")
    busca_reg = st.sidebar.text_input("Buscar por Nº Regulação:")

    df_filtrado = df.copy()

    if busca_nome:
        df_filtrado = df_filtrado[df_filtrado["nome_paciente"].astype(str).str.contains(busca_nome, case=False, na=False)]

    if busca_reg:
        df_filtrado = df_filtrado[df_filtrado["numero_reg"].astype(str).str.contains(busca_reg, case=False, na=False)]

    # --- ORGANIZAÇÃO DA TABELA EXIBIDA ---
    st.markdown("---")
    st.subheader("📋 Lista de Regulações Cadastradas")

    # Organiza a ordem das colunas para melhor leitura
    colunas_ordem = ["id", "nome_paciente", "numero_reg", "data_nascimento", "status_anterior", "celular", "email", "created_at"]
    colunas_existentes = [col for col in colunas_ordem if col in df_filtrado.columns]

    st.dataframe(
        df_filtrado[colunas_existentes],
        use_container_width=True,
        hide_index=True
    )