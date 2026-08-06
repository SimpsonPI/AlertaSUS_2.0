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
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://nvuvyebrbnoldtimkozb.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_EmfKUviMXVqMh3EhiIPD4g_GnOqQlos")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8988706536:AAGDw7uw8Ttm04H8DcIeT0ZwfiaXWXEY6Us")
SCRAPER_KEY = os.environ.get("SCRAPER_KEY", "")  # Adicionado para aturar a importacao do scraper.py
PORT = int(os.environ.get("PORT", 10000))

# URL Base do Formulário WebApp no GitHub Pages
URL_FORMULARIO_PAGES = "https://simpsonpi.github.io/alerta-sus-bot/"

if not TELEGRAM_BOT_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Verifique as variáveis de ambiente no arquivo .env ou no painel do servidor!")

# Cliente Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configurações Globais
FUSO_HORARIO = ZoneInfo("America/Fortaleza")
URL_BUSCA_FMS = "https://agendamentos.sus.fms.pmt.pi.gov.br/detail_scheduling/index"

BOT_APP = None
MAIN_LOOP = None