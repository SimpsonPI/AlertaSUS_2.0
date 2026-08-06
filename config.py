import os
import logging
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from supabase import create_client, Client

# Configuração de Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

load_dotenv()

# Variáveis de Ambiente
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
APP_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
SCRAPER_KEY = os.environ.get("SCRAPER_KEY")
PORT = int(os.environ.get("PORT", 10000))

if not TELEGRAM_BOT_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Verifique as variáveis de ambiente no arquivo .env ou no painel do servidor!")

# Cliente Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configurações Globais
FUSO_HORARIO = ZoneInfo("America/Fortaleza")
URL_BUSCA_FMS = "https://agendamentos.sus.fms.pmt.pi.gov.br/detail_scheduling/index"

BOT_APP = None
MAIN_LOOP = None