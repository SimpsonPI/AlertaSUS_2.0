import streamlit as st
import pandas as pd
from datetime import datetime
from supabase import create_client, Client

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(
    page_title="Painel de Controle Privado — AlertaSUS 2.0",
    page_icon="🔒",
    layout="wide"
)

st.title("🔒 Painel de Gestão Interna — AlertaSUS 2.0")
st.caption("Visão privada do administrador com dados cadastrais e de prioridade no SUS.")

# 2. CONEXÃO COM O SUPABASE
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# 3. CARREGAMENTO DOS DADOS (Tabela: AlertaSUS_2.0)
@st.cache_data(ttl=30)  # Atualiza os dados a cada 30 segundos
def carregar_dados():
    res = supabase.table("AlertaSUS_2.0").select("*").execute()
    return pd.DataFrame(res.data)

df = carregar_dados()

# 4. TRATAMENTO E EXIBIÇÃO
if not df.empty:
    # Garante a existência das colunas essenciais com os nomes exatos do Supabase
    colunas_obrigatorias = [
        'numero_reg', 'id_do_chat', 'nome_paciente', 
        'celular', 'e-mail', 'data_nascimento', 'status_anterior'
    ]
    for col in colunas_obrigatorias:
        if col not in df.columns:
            df[col] = None

    # Função para calcular idade
    def calcular_idade(data):
        if pd.isnull(data):
            return None
        hoje = pd.Timestamp.now()
        return hoje.year - data.year - ((hoje.month, hoje.day) < (data.month, data.day))

    # Tratamento da data de nascimento e cálculo da idade
    if 'data_nascimento' in df.columns:
        df['data_nascimento'] = pd.to_datetime(df['data_nascimento'], errors='coerce')
        df['data_nasc_formatada'] = df['data_nascimento'].dt.strftime('%d/%m/%Y').fillna('Não informada')
        df['idade'] = df['data_nascimento'].apply(calcular_idade)

    # Classificação de prioridades no SUS por idade
    def definir_prioridade(idade):
        if pd.isnull(idade):
            return "Sem data registrada"
        elif idade >= 80:
            return "🔴 Super Prioridade (80+)"
        elif idade >= 60:
            return "🟡 Prioridade (60+)"
        else:
            return "🟢 Geral (<60)"

    df['prioridade_sus'] = df['idade'].apply(definir_prioridade)

    # --- MÉTRICAS E CARDS DEDICADOS ---
    col1, col2, col3, col4 = st.columns(4)

    total_cadastros = len(df)
    prioritarios_count = len(df[df['idade'] >= 60])
    com_email_count = df['e-mail'].dropna().str.strip().ne('').sum() if 'e-mail' in df.columns else 0
    
    media_idade_val = df['idade'].dropna()
    media_idade = f"{round(media_idade_val.mean(), 1)} anos" if not media_idade_val.empty else "N/A"

    col1.metric("👥 Total de Usuários", total_cadastros)
    col2.metric("👴 Prioritários (60+)", prioritarios_count)
    col3.metric("📧 Com E-mail Cadastrado", com_email_count)
    col4.metric("📊 Média de Idade", media_idade)

    st.divider()

    # --- FILTROS DE BUSCA E TABELA ---
    st.subheader("📋 Registros de Usuários")

    busca = st.text_input("🔍 Filtrar por Nome, Telefone, E-mail, Regulação ou Telegram ID:")

    df_exibicao = df.copy()

    if busca:
        mask = (
            df_exibicao['nome_paciente'].astype(str).str.contains(busca, case=False, na=False) |
            df_exibicao['celular'].astype(str).str.contains(busca, case=False, na=False) |
            df_exibicao['e-mail'].astype(str).str.contains(busca, case=False, na=False) |
            df_exibicao['id_do_chat'].astype(str).str.contains(busca, case=False, na=False) |
            df_exibicao['numero_reg'].astype(str).str.contains(busca, case=False, na=False)
        )
        df_exibicao = df_exibicao[mask]

    # Mapeamento atualizado com as colunas reais do seu Supabase
    colunas_visiveis = [
        'numero_reg',           # Número da Regulação
        'id_do_chat',           # ID do Telegram
        'nome_paciente',        # Nome completo
        'celular',              # Celular / WhatsApp
        'e-mail',               # E-mail
        'data_nasc_formatada',  # Data formatada (DD/MM/AAAA)
        'idade',                # Idade calculada
        'status_anterior'       # Categoria / Prioridade SUS
    ]

    st.dataframe(
        df_exibicao[colunas_visiveis],
        column_config={
            "numero_reg": "ID Regulação",
            "id_do_chat": "ID Telegram",
            "nome_paciente": "Nome Completo",
            "celular": "Celular / WhatsApp",
            "e-mail": "E-mail",
            "data_nasc_formatada": "Data de Nasc.",
            "idade": st.column_config.NumberColumn("Idade", format="%d anos"),
            "status_anterior": "Categoria SUS"
        },
        use_container_width=True,
        hide_index=True
    )

    # Botão de exportação
    csv_data = df_exibicao[colunas_visiveis].to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Baixar Dados Filtrados (CSV)",
        data=csv_data,
        file_name=f"relatorio_alertasus_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )

else:
    st.warning("A tabela 'AlertaSUS_2.0' está conectada, mas não possui nenhum registro cadastrado ainda.")