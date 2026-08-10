import os
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from supabase import create_client, Client

# Garante que o arquivo .env seja lido do disco
load_dotenv()

# Variáveis de Ambiente
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://nvuvyebrbnoldtimkozb.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_EmfKUviMXVqMh3EhiIPD4g_GnOqQlos")

# ⚠️ COLE O SEU NOVO TOKEN GERADO NO BOTFATHER AQUI ABAIXO:
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8988706536:AAEHC5-Fwcaqbq-SnnxiUT494OeziUQSP6k")

# ID do Administrador para comandos restritos (/admin, /autorizar)
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "5242040324"))

SCRAPER_KEY = os.environ.get("SCRAPER_KEY", "")
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