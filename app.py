import streamlit as st
import pandas as pd
from supabase import create_client, Client

# 1. Configuração da Página
st.set_page_config(
    page_title="AlertaSUS 2.0 - Central de Controle",
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

# Função genérica para carregar qualquer tabela do Supabase
def carregar_tabela(nome_tabela):
    try:
        response = supabase.table(nome_tabela).select("*").execute()
        df = pd.DataFrame(response.data)
        
        # Tratamento de datas se existirem colunas de data comuns
        for col in ["created_at", "data_assinatura", "data_pagamento"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%d/%m/%Y %H:%M")
                
        return df
    except Exception as e:
        st.error(f"Erro ao carregar a tabela {nome_tabela}: {e}")
        return pd.DataFrame()

# --- TÍTULO E BOTÃO DE ATUALIZAR GERAL ---
st.title("🏥 AlertaSUS 2.0 — Central de Controle Total")

col_btn1, col_btn2 = st.columns([8, 2])
with col_btn2:
    if st.button("🔄 Atualizar Dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.markdown("---")

# --- CRIAÇÃO DAS ABAS (TABS) PARA CADA TABELA DO SUPABASE ---
aba_regulacoes, aba_assinaturas, aba_lgpd, aba_pix = st.tabs([
    "📋 Regulações (AlertaSUS_2.0)", 
    "💳 Assinaturas", 
    "🛡️ LGPD Consentimentos", 
    "💰 Pagamentos PIX"
])

# ==========================================
# ABA 1: REGULAÇÕES (AlertaSUS_2.0)
# ==========================================
with aba_regulacoes:
    st.subheader("Gerenciamento de Regulações")
    df_reg = carregar_tabela("AlertaSUS_2.0")
    
    if df_reg.empty:
        st.warning("Nenhum registro encontrado na tabela de regulações.")
    else:
        # Métricas rápidas
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Total de Registros", len(df_reg))
        kpi2.metric("Pacientes Únicos", df_reg["nome_paciente"].nunique() if "nome_paciente" in df_reg.columns else 0)
        kpi3.metric("Números de Regulação", df_reg["numero_reg"].nunique() if "numero_reg" in df_reg.columns else 0)

        # Filtros laterais ou na tela
        b1, b2 = st.columns(2)
        busca_nome = b1.text_input("Filtrar por Nome do Paciente:")
        busca_reg = b2.text_input("Filtrar por Nº Regulação:")

        df_reg_filtrado = df_reg.copy()
        if busca_nome:
            df_reg_filtrado = df_reg_filtrado[df_reg_filtrado["nome_paciente"].astype(str).str.contains(busca_nome, case=False, na=False)]
        if busca_reg:
            df_reg_filtrado = df_reg_filtrado[df_reg_filtrado["numero_reg"].astype(str).str.contains(busca_reg, case=False, na=False)]

        st.dataframe(df_reg_filtrado, use_container_width=True, hide_index=True)

# ==========================================
# ABA 2: ASSINATURAS
# ==========================================
with aba_assinaturas:
    st.subheader("Gerenciamento de Assinaturas")
    df_ass = carregar_tabela("assinaturas")
    
    if df_ass.empty:
        st.info("A tabela de assinaturas está vazia ou sem registros no momento.")
    else:
        st.metric("Total de Assinaturas", len(df_ass))
        st.dataframe(df_ass, use_container_width=True, hide_index=True)

# ==========================================
# ABA 3: LGPD CONSENTIMENTOS
# ==========================================
with aba_lgpd:
    st.subheader("Auditoria de Consentimentos LGPD")
    df_lgpd = carregar_tabela("lgpd_consentimentos")
    
    if df_lgpd.empty:
        st.info("Nenhum registro de consentimento LGPD encontrado.")
    else:
        st.metric("Total de Consentimentos Registrados", len(df_lgpd))
        st.dataframe(df_lgpd, use_container_width=True, hide_index=True)

# ==========================================
# ABA 4: PAGAMENTOS PIX
# ==========================================
with aba_pix:
    st.subheader("Histórico e Controle de Pagamentos PIX")
    df_pix = carregar_tabela("pagamentos_pix")
    
    if df_pix.empty:
        st.info("Nenhum pagamento PIX registrado na tabela.")
    else:
        st.metric("Total de Transações PIX", len(df_pix))
        st.dataframe(df_pix, use_container_width=True, hide_index=True)