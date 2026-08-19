import os
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from supabase import create_client, Client

# Carrega estritamente o arquivo .env
load_dotenv()

# Variáveis de Ambiente sem valores padrão sensíveis no código
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# IDs de Administração
raw_admin_id = os.getenv("ADMIN_CHAT_ID", "").strip()
ADMIN_CHAT_ID = int(raw_admin_id) if raw_admin_id.isdigit() else None

raw_admin_ids = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = [int(x.strip()) for x in raw_admin_ids.split(",") if x.strip().isdigit()]

SCRAPER_KEY = os.getenv("SCRAPER_KEY", "")
PORT = int(os.getenv("PORT", 10000))

# URL Base do Formulário WebApp no GitHub Pages
URL_FORMULARIO_PAGES = "https://simpsonpi.github.io/alerta-sus-bot/"

# Validação das variáveis obrigatórias
if not TELEGRAM_BOT_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("⚠️ ERRO CRÍTICO: Variáveis TELEGRAM_BOT_TOKEN, SUPABASE_URL ou SUPABASE_KEY não configuradas no arquivo .env!")

# Cliente Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configurações Globais
FUSO_HORARIO = ZoneInfo("America/Fortaleza")
URL_BUSCA_FMS = "https://agendamentos.sus.fms.pmt.pi.gov.br/detail_scheduling/index"

BOT_APP = None
MAIN_LOOP = None