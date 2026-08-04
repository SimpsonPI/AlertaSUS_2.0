# Atualizacao do bot
import os
import re
import json
import logging
import traceback
import threading
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from datetime import time, datetime
from zoneinfo import ZoneInfo
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client, Client
from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.helpers import escape_markdown
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# Configuração de Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

load_dotenv()

# Variáveis de Ambiente
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
APP_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

if not TELEGRAM_BOT_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Verifique as variáveis de ambiente no arquivo .env ou no painel do servidor!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Fuso Horário de Teresina / Piauí (UTC-3)
FUSO_HORARIO = ZoneInfo("America/Fortaleza")

# Endpoint oficial de busca da FMS Teresina
URL_BUSCA_FMS = "https://agendamentos.sus.fms.pmt.pi.gov.br/detail_scheduling/index"

# Referências Globais para comunicação entre Threads (Servidor Web <-> Telegram Bot)
BOT_APP = None
MAIN_LOOP = None


# ==========================================
# MÓDULO DE CONSULTA FMS TERESINA (SCRAPER)
# ==========================================
def _extrair_valor_campo_fms(soup: BeautifulSoup, rotulo: str) -> str | None:
    rotulo_normalizado = rotulo.strip().lower()
    for titulo in soup.find_all("h4"):
        if titulo.get_text(strip=True).lower() != rotulo_normalizado:
            continue
        paragrafo = titulo.find_next_sibling("p")
        if paragrafo:
            valor = paragrafo.get_text(strip=True)
            if valor:
                return valor
    return None


async def consultar_status_fms(numero_reg: str) -> dict:
    # Subtitua SUA_API_KEY_AQUI pela chave que você gerou no painel da ScraperAPI
    # Lê a chave configurada no Railway com segurança
    # 1. Lê a chave das variáveis do Railway com segurança
    SCRAPER_KEY = os.getenv("SCRAPER_KEY")

    if not SCRAPER_KEY:
        logging.error("A variável de ambiente SCRAPER_KEY não foi configurada.")
        return {"sucesso": False, "mensagem": "Erro de configuração no servidor."}

    # 2. Monta a URL do portal FMS
    url_fms_target = f"{URL_BUSCA_FMS}?number_id={numero_reg}"

    # 3. Monta a URL da ScraperAPI diretamente (sem a codificação automática do httpx)
    scraper_url = f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={url_fms_target}&country_code=br"

    try:
        async with httpx.AsyncClient( follow_redirects=True, timeout=30.0) as client:
            resposta = await client.get(scraper_url)

            if resposta.status_code != 200:
                logging.error(f"Erro HTTP {resposta.status_code} na ScraperAPI.")
                return {"sucesso": False, "mensagem": f"Erro HTTP {resposta.status_code}"}

            # O seu código de extração com BeautifulSoup continua normal aqui abaixo...

            from bs4 import BeautifulSoup

# ... dentro da sua função de consulta ...

            # Parse do HTML retornado
            soup = BeautifulSoup(resposta.text, "html.parser")

            # 1. Validação: Verifica se a página retornou "Nenhum registro encontrado" ou similar
            texto_pagina = soup.get_text().lower()
            if "nenhum registro" in texto_pagina or "não encontrado" in texto_pagina:
                return {
                    "sucesso": False,
                    "mensagem": f"⚠️ A regulação *{numero_reg}* não foi encontrada no portal da FMS."
                }

            # 2. Extração segura dos campos (evita quebra por falta de tag)
            try:
                # Exemplo de busca de elementos (ajuste os seletores conforme suas variáveis)
                tabela = soup.find("table")
                if not tabela:
                    logging.warning(f"Tabela não encontrada no HTML para a regulação {numero_reg}.")
                    return {
                        "sucesso": False, 
                        "mensagem": "⚠️ Não foi possível extrair a tabela de dados da FMS."
                    }

                # Se a tabela existe, realiza o parsing normalmente
                # (Mantenha aqui a sua lógica de leitura das linhas/colunas)

            except (AttributeError, IndexError) as err:
                logging.error(f"Erro ao ler estrutura da tabela: {err}")
                return {
                    "sucesso": False,
                    "mensagem": "Erro ao formatar os dados da regulação."
                }
            texto_pagina = soup.get_text()

            if "Verifique se o ID ou da solicitação" in texto_pagina:
                return {
                    "sucesso": True,
                    "encontrado": False,
                    "posicao_fila": "Não encontrada",
                    "previsao_atendimento": "Não informada",
                    "status_resumido": "Não encontrado / Incorreto"
                }

            card = soup.find("div", class_="card-body") or soup

            alertas = [re.sub(r"\s+", " ", a.get_text(" ", strip=True)) for a in card.find_all("div", class_=re.compile(r"alert"))]
            alerta_texto = "\n".join(alertas) if alertas else None

            campos = {}
            for h4 in card.find_all("h4", class_="card-title"):
                rotulo = h4.get_text(strip=True)
                if not rotulo or "_" in rotulo:
                    continue

                p = h4.find_next_sibling("p")
                if not p and h4.parent:
                    p = h4.parent.find("p", class_="card-text")

                if p:
                    valor = re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip()
                    if valor:
                        campos[rotulo] = valor

            situacao = campos.get("Situação") or _extrair_valor_campo_fms(soup, "Situação") or "Informada no portal"
            posicao_fila = campos.get("Posição da Fila") or _extrair_valor_campo_fms(soup, "Posição da Fila") or "Não informada"
            previsao_atendimento = campos.get("Previsão de atendimento") or _extrair_valor_campo_fms(soup, "Previsão de atendimento") or "Não informada"

            partes_resumo = []
            for k, v in campos.items():
                partes_resumo.append(f"{k}: {v}")
            if alerta_texto:
                partes_resumo.append(f"Alerta: {alerta_texto}")

            status_resumido = " | ".join(partes_resumo) if partes_resumo else f"Fila: {posicao_fila} | Previsão: {previsao_atendimento}"

            return {
                "sucesso": True,
                "encontrado": True,
                "situacao": situacao,
                "posicao_fila": posicao_fila,
                "previsao_atendimento": previsao_atendimento,
                "alerta_fms": alerta_texto,
                "campos": campos,
                "status_resumido": status_resumido
            }

    except httpx.TimeoutException:
        logging.warning(f"Timeout ao conectar no portal da FMS (Reg {numero_reg}).")
        return {"sucesso": False, "mensagem": "Tempo limite de conexão excedido ao acessar a FMS."}
    except Exception as e:
        logging.error(f"Falha ao conectar no portal da FMS (Reg {numero_reg}): {e}")
        return {"sucesso": False, "mensagem": str(e)}


def nome_paciente_exibicao(nome: str | None) -> str:
    if not nome or not nome.strip() or nome.strip() == "Aguardando consulta":
        return "Não informado"
    return nome.strip()


def montar_mensagem_regulacao(
    numero_reg: str,
    resultado: dict,
    nome_paciente: str | None = None,
    data_nascimento: str | None = None,
    email: str | None = None,
    titulo: str = "🏥 *SITUAÇÃO DA REGULAÇÃO*",
) -> str:
    nome_esc = escape_markdown(nome_paciente_exibicao(nome_paciente), version=1)
    numero_esc = escape_markdown(numero_reg, version=1)
    linhas = [titulo, "", f"👤 *Paciente:* *{nome_esc}*"]

    dt_exibicao = data_nascimento.strip() if data_nascimento else "Não informada"
    dt_esc = escape_markdown(dt_exibicao, version=1)
    linhas.append(f"🎂 *Data de Nascimento:* *{dt_esc}*")

    if email:
        email_esc = escape_markdown(email.strip(), version=1)
        linhas.append(f"📧 *E-mail:* *{email_esc}*")

    if resultado.get("encontrado", True):
        linhas.append(f"🆔 *ID de Regulação:* `{numero_esc}`")

        situacao = resultado.get("situacao")
        if situacao:
            linhas.append(f"📌 *Situação:* *{escape_markdown(situacao, version=1)}*")

        alerta = resultado.get("alerta_fms")
        if alerta:
            linhas.append(f"🚨 *Aviso FMS:* _{escape_markdown(alerta, version=1)}_")

        campos = resultado.get("campos", {})
        for rotulo, valor in campos.items():
            rotulo_lower = rotulo.lower()
            if rotulo_lower in ["situação", "id de regulação"]:
                continue
            rot_esc = escape_markdown(str(rotulo), version=1)
            val_esc = escape_markdown(str(valor), version=1)
            linhas.append(f"• *{rot_esc}:* {val_esc}")
    else:
        linhas.extend([
            f"🆔 *ID de Regulação:* `{numero_esc}`",
            "Verifique se o ID ou número de regulação informado no comprovante está correto!",
        ])

    return "\n".join(linhas)
def validar_dados_cadastrais(
    numero_reg: str, 
    nome_paciente: str | None, 
    data_nascimento: str | None, 
    email: str | None
) -> tuple[bool, str]:
    # 1. Validação do Número de Regulação
    reg_limpo = str(numero_reg).strip() if numero_reg else ""
    if not reg_limpo or not reg_limpo.isalnum():
        return False, "⚠️ O número de regulação é obrigatório e deve conter apenas letras e números."

    # 2. Validação do Nome do Paciente
    nome_limpo = str(nome_paciente).strip() if nome_paciente else ""
    if not nome_limpo or len(nome_limpo) < 3:
        return False, "⚠️ Informe o nome completo do paciente."
    if not re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ\s]+$", nome_limpo):
        return False, "⚠️ O nome do paciente deve conter apenas letras e espaços."

    # 3. Validação da Data de Nascimento
    data_limpa = str(data_nascimento).strip() if data_nascimento else ""
    pattern_data = r"^(0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/\d{4}$"
    
    if not re.match(pattern_data, data_limpa):
        return False, "⚠️ Data de nascimento inválida. Utilize o formato DD/MM/AAAA."
    
    try:
        data_obj = datetime.strptime(data_limpa, "%d/%m/%Y")
        if data_obj > datetime.now():
            return False, "⚠️ A data de nascimento não pode estar no futuro."
    except ValueError:
        return False, "⚠️ Data de nascimento inválida no calendário."

    # 4. Validação do E-mail (OPCIONAL)
    if email and email.strip():
        email_limpo = email.strip()
        pattern_email = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(pattern_email, email_limpo):
            return False, "⚠️ O e-mail digitado é inválido. Deixe em branco se não quiser informar."

    return True, "Dados válidos"

async def executar_cadastro_regulacao(
    chat_id: int,
    numero_reg: str,
    nome_paciente: str | None,
    data_nascimento: str | None,
    email: str | None
) -> tuple[bool, str]:
    
    # --- NOVO: Valida o formato dos dados recebidos antes de consultar a FMS ---
    dados_validos, mensagem_erro = validar_dados_cadastrais(
        numero_reg, nome_paciente, data_nascimento, email
    )
    if not dados_validos:
        return False, mensagem_erro
    # --------------------------------------------------------------------------

    nome_salvar = nome_paciente or "Aguardando consulta"
    data_salvar = data_nascimento or "Não informada"

    # Restante do seu código normal...

    # 1. Realiza a consulta no portal da FMS
    resultado = await consultar_status_fms(numero_reg)

    # 2. Caso ocorra erro de conexão/HTTP com a ScraperAPI ou FMS
    if not resultado.get("sucesso"):
        return False, "Não foi possível verificar a regulação na FMS Teresina neste momento. Tente novamente."

    # 3. Caso a regulação NÃO exista no portal da FMS (Bloqueia o cadastro)
    if not resultado.get("encontrado", False):
        mensagem_erro = montar_mensagem_regulacao(
            numero_reg,
            resultado,
            nome_paciente=nome_salvar,
            data_nascimento=data_salvar,
            email=email,
            titulo="⚠️ *REGULAÇÃO NÃO LOCALIZADA NA FMS*"
        )
        return False, mensagem_erro

    # 4. A regulação existe! Salva no Supabase
    try:
        dados_alerta = {
            "chat_id": chat_id,
            "numero_reg": numero_reg,
            "nome_paciente": nome_salvar,
            "data_nascimento": data_salvar,
            "email": email,
            "status_atual": resultado.get("status", "Cadastrado")
        }

        # Insere ou atualiza o registro na tabela "alertas"
        supabase.table("alertas").upsert(dados_alerta).execute()

        mensagem_sucesso = (
            f"✅ *Alerta ativado com sucesso!*\n\n"
            f"• *Regulação:* `{numero_reg}`\n"
            f"• *Paciente:* {nome_salvar}\n\n"
            f"Acompanharemos a fila para você!"
        )
        return True, mensagem_sucesso

    except Exception as err:
        logging.error(f"Erro ao salvar no Supabase para regulação {numero_reg}: {err}")
        return False, "Erro ao salvar o alerta no banco de dados. Tente novamente."

    # Verifica duplicidade no banco
    try:
        # Validação prévia para garantir que o resultado da consulta é válido
        if not resultado or not isinstance(resultado, dict) or resultado.get("erro") or not resultado.get("status_resumido"):
            return False, "❌ *Regulação não encontrada!* O ID informado é inválido ou não existe na base de dados."

        existente = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0")
            .select("*")
            .eq("chat_id", chat_id)
            .eq("numero_reg", str(numero_reg))
            .execute()
        )

        dados_payload = {
            "chat_id": chat_id,
            "numero_reg": str(numero_reg),
            "status_anterior": resultado.get("status_resumido", "Pendente"),
            "nome_paciente": nome_salvar,
            "data_nascimento": data_salvar,
            "email": email,
        }

        if existente.data:
            await asyncio.to_thread(
                lambda: supabase.table("AlertaSUS_2.0")
                .update(dados_payload)
                .eq("chat_id", chat_id)
                .eq("numero_reg", str(numero_reg))
                .execute()
            )
            msg_retorno = (
                f"ℹ️ Regulação `{escape_markdown(str(numero_reg), version=1)}` já estava cadastrada! "
                "Os dados foram atualizados com sucesso."
            )
        else:
            await asyncio.to_thread(
                lambda: supabase.table("AlertaSUS_2.0").insert(dados_payload).execute()
            )
            detalhes = montar_mensagem_regulacao(
                numero_reg,
                resultado,
                nome_paciente=nome_salvar,
                data_nascimento=data_salvar,
                email=email,
                titulo="✅ *REGULAÇÃO CADASTRADA COM SUCESSO!*"
            )
            
            msg_retorno = (
                f"{detalhes}\n\n"
                f"⏰ *Monitoramento automático:* varreduras diárias às *08:00* e *18:00*.\n"
                f"Para ver todos os seus cadastros, use `/verificar`."
            )

        # Envia notificação diretamente pelo Bot
        if BOT_APP:
            await BOT_APP.bot.send_message(chat_id=chat_id, text=msg_retorno, parse_mode="Markdown")

        return True, "Cadastro realizado com sucesso!"

    except Exception as e:
        logging.error(f"Erro ao salvar no Supabase: {e}")
        return False, "Ocorreu um erro interno ao gravar a regulação no banco de dados."


# ==========================================
# SERVIDOR WEB E FORMULÁRIO (/form_alertaSUS)
# ==========================================
FORMULARIO_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AlertaSUS 2.0 — Formit de Cadastro</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        :root {
            --primary: #0088cc;
            --primary-hover: #006699;
            --bg: #f4f6f9;
            --card-bg: #ffffff;
            --text: #333333;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 16px;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            box-sizing: border-box;
        }
        .card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 24px;
            width: 100%;
            max-width: 420px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.08);
        }
        .header {
            text-align: center;
            margin-bottom: 20px;
        }
        .header h2 {
            margin: 0;
            color: var(--primary);
            font-size: 1.4rem;
        }
        .header p {
            font-size: 0.88rem;
            color: #666;
            margin-top: 6px;
        }
        .form-group {
            margin-bottom: 16px;
        }
        label {
            display: block;
            font-size: 0.85rem;
            font-weight: 600;
            margin-bottom: 6px;
            color: #444;
        }
        input {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #ccc;
            border-radius: 8px;
            font-size: 0.95rem;
            box-sizing: border-box;
            outline: none;
            transition: border-color 0.2s;
        }
        input:focus {
            border-color: var(--primary);
        }
        .required {
            color: #e53935;
        }
        button {
            width: 100%;
            background-color: var(--primary);
            color: white;
            border: none;
            padding: 12px;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: bold;
            cursor: pointer;
            transition: background 0.2s;
            margin-top: 8px;
        }
        button:hover {
            background-color: var(--primary-hover);
        }
        button:disabled {
            background-color: #aaa;
            cursor: not-allowed;
        }
        #statusMessage {
            margin-top: 16px;
            padding: 10px;
            border-radius: 6px;
            font-size: 0.88rem;
            display: none;
            text-align: center;
        }
        .success { background-color: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; }
        .error { background-color: #ffebee; color: #c62828; border: 1px solid #ef9a9a; }
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <h2>🏥 AlertaSUS 2.0</h2>
            <p>Cadastre sua solicitação da FMS Teresina para receber notificações automáticas.</p>
        </div>
        <form id="cadastroForm">
            <input type="hidden" id="chat_id" name="chat_id">

            <div class="form-group">
                <label for="numero_reg">ID de Regulação <span class="required">*</span></label>
                <input type="number" id="numero_reg" name="numero_reg" placeholder="Ex: 12345678" required>
            </div>

            <div class="form-group">
                <label for="nome_paciente">Nome do Paciente</label>
                <input type="text" id="nome_paciente" name="nome_paciente" placeholder="Ex: Maria Silva">
            </div>

            <div class="form-group">
                <label for="data_nascimento">Data de Nascimento</label>
                <input type="text" id="data_nascimento" name="data_nascimento" placeholder="DD/MM/AAAA">
            </div>

            <div class="form-group">
                <label for="email">E-mail</label>
                <input type="email" id="email" name="email" placeholder="seu@email.com">
            </div>

            <button type="submit" id="btnSubmit">Cadastrar e Monitorar</button>
        </form>

        <div id="statusMessage"></div>
    </div>

    <script>
        const tg = window.Telegram?.WebApp;
        if (tg) {
            tg.expand();
        }

        // Recupera chat_id da URL ou do Telegram WebApp
        const urlParams = new URLSearchParams(window.location.search);
        let chatId = urlParams.get('chat_id');
        if (!chatId && tg?.initDataUnsafe?.user?.id) {
            chatId = tg.initDataUnsafe.user.id;
        }
        if (chatId) {
            document.getElementById('chat_id').value = chatId;
        }

        const form = document.getElementById('cadastroForm');
        const statusDiv = document.getElementById('statusMessage');
        const btnSubmit = document.getElementById('btnSubmit');

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const currentChatId = document.getElementById('chat_id').value;
            if (!currentChatId) {
                showStatus('Erro: ID do chat do Telegram não identificado. Acesse este formulário pelo bot.', false);
                return;
            }

            btnSubmit.disabled = true;
            btnSubmit.innerText = 'Consultando FMS Teresina...';
            showStatus('Verificando dados no portal da FMS...', true, true);

            const formData = {
                chat_id: currentChatId,
                numero_reg: document.getElementById('numero_reg').value.trim(),
                nome_paciente: document.getElementById('nome_paciente').value.trim(),
                data_nascimento: document.getElementById('data_nascimento').value.trim(),
                email: document.getElementById('email').value.trim()
            };

                   method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(formData)
                });

                const result = await response.json();

                if (result.sucesso) {
                    showStatus('✅ Regulação cadastrada com sucesso! Você já pode fechar esta página.', true);
                    form.reset();
                    if (tg) setTimeout(() => tg.close(), 2500);
                } else {
                    showStatus('❌ ' + (result.mensagem || 'Falha ao cadastrar regulação.'), false);
                }
            } catch (err) {
                showStatus('❌ Erro de conexão com o servidor. Tente novamente.', false);
            } finally {
                btnSubmit.disabled = false;
                btnSubmit.innerText = 'Cadastrar e Monitorar';
            }
        });

        function showStatus(msg, isSuccess, isPending = false) {
            statusDiv.style.display = 'block';
            statusDiv.innerText = msg;
            statusDiv.className = isPending ? '' : (isSuccess ? 'success' : 'error');
        }
    </script>
</body>
</html>
"""

class HealthCheckHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Desabilita logs repetitivos do servidor HTTP para manter o console limpo
        return
        
    def do_GET(self):
        parsed_path = urlparse(self.path)

        if parsed_path.path in ["/form_alertaSUS", "/form"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(FORMULARIO_HTML.encode("utf-8"))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Bot AlertaSUS 2.0 ativo!")

    def do_POST(self):
        if self.path == "/api/cadastrar":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)

            try:
                dados = json.loads(post_data.decode('utf-8'))
                chat_id = int(dados.get("chat_id"))
                numero_reg = str(dados.get("numero_reg", "")).strip()
                nome_paciente = dados.get("nome_paciente")
                data_nascimento = dados.get("data_nascimento")
                email = dados.get("email")

                if not chat_id or not numero_reg:
                    self._responder_json({"sucesso": False, "mensagem": "Dados incompletos."}, 400)
                    return

                # Executa o cadastro chamando a função assíncrona da thread principal
                future = asyncio.run_coroutine_threadsafe(
                    executar_cadastro_regulacao(chat_id, numero_reg, nome_paciente, data_nascimento, email),
                    MAIN_LOOP
                )
                sucesso, mensagem = future.result(timeout=20.0)

                self._responder_json({"sucesso": sucesso, "mensagem": mensagem})

            except Exception as e:
                logging.error(f"Erro no processamento da API de cadastro: {e}")
                self._responder_json({"sucesso": False, "mensagem": str(e)}, 500)
        else:
            self.send_response(404)
            self.end_headers()

    def _responder_json(self, payload: dict, status_code: int = 200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


def run_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


# ==========================================
# ROTINA DE VERIFICAÇÃO AUTOMÁTICA (CRON)
# ==========================================
async def executar_varredura_regulacoes(bot_app):
    bot = getattr(bot_app, "bot", bot_app)
    logging.info("🔍 Executando varredura agendada no portal da FMS Teresina...")

    try:
        resposta = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").execute()
        )
        regulacoes = resposta.data

        if not regulacoes:
            logging.info("Nenhuma regulação encontrada no banco de dados.")
            return

        for reg in regulacoes:
            chat_id = reg.get("chat_id")
            numero_reg = reg.get("numero_reg")
            nome_paciente = reg.get("nome_paciente")
            data_nascimento = reg.get("data_nascimento")
            email = reg.get("email")
            status_anterior = reg.get("status_anterior")

            if not chat_id or not numero_reg:
                continue

            resultado = await consultar_status_fms(numero_reg)

            if resultado.get("sucesso"):
                novo_status = resultado.get("status_resumido", "Desconhecido")

                if novo_status != status_anterior:
                    await asyncio.to_thread(
                        lambda: supabase.table("AlertaSUS_2.0").update({
                            "status_anterior": novo_status
                        }).eq("id", reg["id"]).execute()
                    )

                    titulo = "🔔 *ATUALIZAÇÃO DE REGULAÇÃO!*" if resultado.get("encontrado", True) else "⚠️ *ATUALIZAÇÃO DE REGULAÇÃO (NÃO LOCALIZADA)*"
                    mensagem = montar_mensagem_regulacao(
                        numero_reg,
                        resultado,
                        nome_paciente=nome_paciente,
                        data_nascimento=data_nascimento,
                        email=email,
                        titulo=titulo,
                    )
                    await bot.send_message(chat_id=chat_id, text=mensagem, parse_mode="Markdown")
                    logging.info(f"Notificação enviada para {chat_id} - Regulação {numero_reg}")

    except Exception as e:
        logging.error(f"Erro na varredura agendada: {traceback.format_exc()}")


async def job_varredura_agendada(context: ContextTypes.DEFAULT_TYPE):
    await executar_varredura_regulacoes(context.bot)


# ==========================================
# COMANDOS DO TELEGRAM
# ==========================================
def obter_link_formulario(chat_id: int) -> str:
    # Aponta para o seu formulário no GitHub Pages mantendo o ID do usuário
    return f"https://simpsonpi.github.io/alerta-sus-bot/?chat_id={chat_id}"


def obter_teclado_cadastro(chat_id: int) -> InlineKeyboardMarkup:
    link = obter_link_formulario(chat_id)
    # Como o GitHub Pages é HTTPS, o WebApp do Telegram funciona diretamente
    btn = InlineKeyboardButton("📝 Abrir Formulário de Cadastro", web_app=WebAppInfo(url=link))
    return InlineKeyboardMarkup([[btn]])


def criar_menu_principal() -> ReplyKeyboardMarkup:
    btn_cadastrar = KeyboardButton("➕ Cadastrar Nova")
    btn_todos = KeyboardButton("📋 Consultar Todos")
    btn_especifico = KeyboardButton("🔍 Consultar Específico")
    btn_corrigir = KeyboardButton("✏️ Corrigir ID")
    btn_excluir = KeyboardButton("❌ Excluir Regulação")
    btn_ajuda = KeyboardButton("ℹ️ Ajuda / Manual")

    keyboard = [
        [btn_cadastrar, btn_todos],
        [btn_especifico, btn_corrigir],
        [btn_excluir, btn_ajuda]
    ]
    
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    return markup

    markup.add(btn_cadastrar)
    markup.add(btn_todos, btn_especifico)
    markup.add(btn_corrigir, btn_excluir)
    markup.add(btn_ajuda)

    return markup


def gerar_botoes_ids(regulacoes, acao_prefixo: str) -> InlineKeyboardMarkup:
    """
    Gera botões inline dinamicamente com base nas regulações do usuário.
    Exemplos:
    - regulacoes: [{'id': '12345678', 'status': 'Pendente'}]
    - acao_prefixo: 'cons', 'corr', 'exc'
    """
    markup = InlineKeyboardMarkup(row_width=1)

    for reg in regulacoes:
        reg_id = reg.get("id") or reg.get("numero_reg") or reg.get("numero")
        status = reg.get("status") or reg.get("status_atual") or reg.get("status_anterior") or "Ativo"

        if reg_id is None:
            continue

        texto_botao = f"ID: {reg_id} - Status: {status}"
        callback_dado = f"{acao_prefixo}_{reg_id}"
        markup.add(InlineKeyboardButton(texto_botao, callback_data=callback_dado))

    return markup


def obter_texto_instrucoes():
    return (
        "👋 **Olá! Seja muito bem-vindo(a) ao AlertaSUS 2.0!**\n\n"
        "Estou aqui para facilitar a sua jornada e ajudar na gestão e consulta de regulações com rapidez e praticidade. 🩺✨\n\n"
        "⚠️ *Aviso: Ferramenta particular e independente, sem vínculo com a FMS.*\n\n"
        "👇 **Escolha abaixo o que você deseja fazer hoje utilizando os botões do nosso menu:**"
        "📌 *1. Cadastrar regulação*\n"
        "Acesse o nosso formulário web interativo utilizando o comando `/cadastrar`.\n\n"
        "📌 *2. Consultar status*\n"
        "• `/verificar` — consulta todas as suas regulações cadastradas\n"
        "• `/verificar 12345678` — consulta instantânea de um ID específico\n\n"
        "📌 *3. Corrigir um ID*\n"
        "• `/corrigir ID_ANTIGO ID_NOVO` (Ex: `/corrigir 12345678 12345689`)\n\n"
        "📌 *4. Excluir uma regulação*\n"
        "• `/excluir 12345678`\n\n"
        "⏰ *Varreduras automáticas:* diariamente às *08:00* e *18:00* (horário de Teresina)."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Aqui você pega o seu menu criado pela função criar_menu_principal()
    reply_markup = ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ Cadastrar Nova"), KeyboardButton("📋 Consultar Todos")],
            [KeyboardButton("🔍 Consultar Específico"), KeyboardButton("✏️ Corrigir ID")],
            [KeyboardButton("❌ Excluir Regulação"), KeyboardButton("ℹ️ Ajuda / Manual")]
        ],
        resize_keyboard=True
    )
    
    # E envia a mensagem passando o reply_markup junto:
    await update.message.reply_text(
        "Olá! Escolha uma das opções abaixo no menu:",
        reply_markup=reply_markup
    )


async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        obter_texto_instrucoes(),
        parse_mode="Markdown",
        reply_markup=criar_menu_principal()
    )


async def comando_cadastrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "📝 Clique no botão abaixo para abrir o **Formulário de Cadastro** e preencher os dados da regulação:",
        parse_mode="Markdown",
        reply_markup=obter_teclado_cadastro(chat_id)
    )


async def comando_verificar_agora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if context.args:
        numero_reg = "".join(re.findall(r'\d+', context.args[0]))

        if not numero_reg:
            await update.message.reply_text(
                "⚠️ Informe um número de regulação válido.\nExemplo: `/verificar 12345678`",
                parse_mode="Markdown"
            )
            return

        reg_esc = escape_markdown(numero_reg, version=1)
        await update.message.reply_text(f"⏳ Consultando a regulação `{reg_esc}` na FMS...", parse_mode="Markdown")

        resultado = await consultar_status_fms(numero_reg)

        if resultado.get("sucesso"):
            nome_paciente = None
            data_nascimento = None
            email = None
            try:
                cadastro = await asyncio.to_thread(
                    lambda: supabase.table("AlertaSUS_2.0").select("*").eq("chat_id", chat_id).eq("numero_reg", numero_reg).execute()
                )
                if cadastro.data:
                    reg_data = cadastro.data[0]
                    nome_paciente = reg_data.get("nome_paciente")
                    data_nascimento = reg_data.get("data_nascimento")
                    email = reg_data.get("email")

                await asyncio.to_thread(
                    lambda: supabase.table("AlertaSUS_2.0").update({
                        "status_anterior": resultado["status_resumido"]
                    }).eq("chat_id", chat_id).eq("numero_reg", numero_reg).execute()
                )
            except Exception as e:
                logging.error(f"Erro ao atualizar status no Supabase: {e}")

            titulo = "🏥 *SITUAÇÃO DA REGULAÇÃO*" if resultado.get("encontrado", True) else "⚠️ *REGULAÇÃO NÃO LOCALIZADA*"
            mensagem = montar_mensagem_regulacao(
                numero_reg,
                resultado,
                nome_paciente=nome_paciente,
                data_nascimento=data_nascimento,
                email=email,
                titulo=titulo
            )
            await update.message.reply_text(mensagem, parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"❌ Falha ao consultar o portal da FMS para o ID `{reg_esc}`.",
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text("⏳ Consultando suas regulações no portal da FMS...")

        try:
            resposta = await asyncio.to_thread(
                lambda: supabase.table("AlertaSUS_2.0").select("*").eq("chat_id", chat_id).execute()
            )
            regulacoes = resposta.data

            if not regulacoes:
                await update.message.reply_text(
                    "⚠️ Você não possui nenhuma regulação cadastrada.",
                    reply_markup=obter_teclado_cadastro(chat_id)
                )
                return

            for reg in regulacoes:
                numero_reg = reg.get("numero_reg")
                nome_paciente = reg.get("nome_paciente")
                data_nascimento = reg.get("data_nascimento")
                email = reg.get("email")
                resultado = await consultar_status_fms(numero_reg)

                if resultado.get("sucesso"):
                    await asyncio.to_thread(
                        lambda: supabase.table("AlertaSUS_2.0").update({
                            "status_anterior": resultado["status_resumido"]
                        }).eq("id", reg["id"]).execute()
                    )

                    titulo = "🏥 *SITUAÇÃO DA REGULAÇÃO*" if resultado.get("encontrado", True) else "⚠️ *REGULAÇÃO NÃO LOCALIZADA*"
                    mensagem = montar_mensagem_regulacao(
                        numero_reg,
                        resultado,
                        nome_paciente=nome_paciente,
                        data_nascimento=data_nascimento,
                        email=email,
                        titulo=titulo
                    )
                    await update.message.reply_text(mensagem, parse_mode="Markdown")
                else:
                    reg_esc = escape_markdown(numero_reg, version=1)
                    await update.message.reply_text(
                        f"❌ Erro ao consultar a regulação `{reg_esc}` no portal da FMS.",
                        parse_mode="Markdown"
                    )

        except Exception as e:
            logging.error(f"Erro no comando verificar: {e}")
            await update.message.reply_text("❌ Ocorreu um erro ao consultar suas regulações.")


async def comando_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "⚠️ Informe o ID que deseja excluir.\nExemplo: `/excluir 12345678`",
            parse_mode="Markdown"
        )
        return

    numero_reg = "".join(re.findall(r'\d+', context.args[0]))

    if not numero_reg:
        await update.message.reply_text("⚠️ Informe um número de regulação válido.")
        return

    try:
        resposta = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0")
            .select("*")
            .eq("chat_id", chat_id)
            .eq("numero_reg", numero_reg)
            .execute()
        )

        reg_esc = escape_markdown(numero_reg, version=1)

        if not resposta.data:
            await update.message.reply_text(
                f"🔍 A regulação `{reg_esc}` não foi encontrada no seu cadastro.",
                parse_mode="Markdown"
            )
            return

        await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0")
            .delete()
            .eq("chat_id", chat_id)
            .eq("numero_reg", numero_reg)
            .execute()
        )

        await update.message.reply_text(
            f"🗑️ Regulação `{reg_esc}` excluída com sucesso!",
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"Erro ao excluir regulação {numero_reg}: {e}")
        await update.message.reply_text("❌ Ocorreu um erro ao excluir a regulação do banco de dados.")


async def comando_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Informe o ID antigo e o novo ID.\nExemplo: `/corrigir 12345678 12345689`",
            parse_mode="Markdown"
        )
        return

    numero_antigo = "".join(re.findall(r'\d+', context.args[0]))
    numero_novo = "".join(re.findall(r'\d+', context.args[1]))

    if not numero_antigo or not numero_novo:
        await update.message.reply_text("⚠️ Informe números de regulação válidos.")
        return

    try:
        resposta = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0")
            .select("*")
            .eq("chat_id", chat_id)
            .eq("numero_reg", numero_antigo)
            .execute()
        )

        antigo_esc = escape_markdown(numero_antigo, version=1)
        novo_esc = escape_markdown(numero_novo, version=1)

        if not resposta.data:
            await update.message.reply_text(
                f"🔍 O ID antigo `{antigo_esc}` não foi encontrado nos seus cadastros.",
                parse_mode="Markdown"
            )
            return

        await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0")
            .update({
                "numero_reg": numero_novo,
                "status_anterior": "Pendente"
            })
            .eq("chat_id", chat_id)
            .eq("numero_reg", numero_antigo)
            .execute()
        )

        await update.message.reply_text(
            f"✏️ Regulação alterada de `{antigo_esc}` para `{novo_esc}` com sucesso!",
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"Erro ao corrigir regulação: {e}")
        await update.message.reply_text("❌ Ocorreu um erro ao atualizar a regulação no banco de dados.")


async def mensagem_texto_padrao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    chat_id = update.effective_chat.id

    if texto == "➕ Cadastrar Nova":
        await update.message.reply_text(
            "📝 Clique no botão abaixo para abrir o **Formulário de Cadastro** e preencher os dados da regulação:",
            parse_mode="Markdown",
            reply_markup=obter_teclado_cadastro(chat_id)
        )
        return

    if texto == "📋 Consultar Todos":
        await comando_verificar_agora(update, context)
        return

    if texto == "🔍 Consultar Específico":
        await update.message.reply_text(
            "⚠️ Informe o ID da regulação para consultar um caso específico.\nExemplo: `/verificar 12345678`",
            parse_mode="Markdown",
            reply_markup=criar_menu_principal()
        )
        return

    if texto == "✏️ Corrigir ID":
        await update.message.reply_text(
            "⚠️ Informe o ID antigo e o novo ID.\nExemplo: `/corrigir 12345678 12345689`",
            parse_mode="Markdown",
            reply_markup=criar_menu_principal()
        )
        return

    if texto == "❌ Excluir Regulação":
        await update.message.reply_text(
            "⚠️ Informe o ID que deseja excluir.\nExemplo: `/excluir 12345678`",
            parse_mode="Markdown",
            reply_markup=criar_menu_principal()
        )
        return

    if texto == "ℹ️ Ajuda / Manual":
        await comando_ajuda(update, context)
        return

    await update.message.reply_text(
        "👋 Para cadastrar uma nova regulação, utilize o formulário abaixo:",
        reply_markup=obter_teclado_cadastro(chat_id)
    )


# ==========================================
# CONFIGURAÇÃO DOS COMANDOS NO TELEGRAM
# ==========================================
async def configurar_menu_comandos(application):
    bot = application.bot

    comandos = [
        BotCommand("start", "Inicia o bot e exibe o manual completo"),
        BotCommand("cadastrar", "Abre o formulário de cadastro"),
        BotCommand("verificar", "Consulta posição na fila e previsão"),
        BotCommand("corrigir", "Altera um ID de regulação cadastrado"),
        BotCommand("excluir", "Remove uma regulação do monitoramento"),
        BotCommand("ajuda", "Exibe as orientações de uso"),
    ]
    await bot.set_my_commands(comandos)

    await bot.set_my_short_description(
        "Monitoramento de solicitações e consultas da FMS Teresina.",
        language_code="pt",
    )
    await bot.set_my_description(
        "AlertaSUS 2.0 acompanha solicitações de consultas e exames no portal da FMS Teresina.\n\n"
        "Cadastre o número de regulação para receber notificações automáticas sobre alterações na fila e no agendamento.",
        language_code="pt",
    )


# ==========================================
# INICIALIZAÇÃO DO BOT
# ==========================================
def main():
    global BOT_APP, MAIN_LOOP

    print("🤖 Iniciando AlertaSUS_2.0...", flush=True)

    # Inicia o servidor Web
    threading.Thread(target=run_health_check, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(configurar_menu_comandos).build()
    BOT_APP = app

    # Captura a referência do Loop Async Principal
    try:
        MAIN_LOOP = asyncio.get_event_loop()
    except RuntimeError:
        MAIN_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(MAIN_LOOP)
    # ==========================================
    # ==========================================
    # ==========================================
    # HANDLERS (CORRIGIDO)
    # ==========================================
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", comando_ajuda))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ Ajuda / Manual$"), comando_ajuda))
    
    # Cadastrar
    app.add_handler(CommandHandler("cadastrar", comando_cadastrar))
    app.add_handler(MessageHandler(filters.Regex("^➕ Cadastrar Nova$"), comando_cadastrar))
    
    # 1. Comandos de texto e botões do menu
    app.add_handler(CommandHandler("verificar", comando_verificar_agora))
    app.add_handler(CommandHandler("consultar", funcao_consulta_especifica))
    
    # Handler para o botão do menu "Consultar Específico"
    app.add_handler(MessageHandler(filters.Regex("^🔍 Consultar Específico$"), consultar especifico))
    
    # 2. Consultar Todos (Substitua 'consultar_todos' pelo nome real da função que mostra todos os IDs)
    
    # Excluir / Deletar
    app.add_handler(CommandHandler("excluir", comando_excluir))
    app.add_handler(CommandHandler("deletar", comando_excluir))
    app.add_handler(MessageHandler(filters.Regex("^❌ Excluir Regulação$"), comando_excluir))
    
    # Corrigir
    app.add_handler(CommandHandler("corrigir", comando_corrigir))
    app.add_handler(MessageHandler(filters.Regex("^✏️ Corrigir ID$"), comando_corrigir))

    # Mensagem padrão para outros textos livres
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensagem_texto_padrao))

    # Agendamento diário (08:00 e 18:00 no fuso de Teresina)
    job_queue = app.job_queue
    job_queue.run_daily(job_varredura_agendada, time=time(hour=8, minute=0, second=0, tzinfo=FUSO_HORARIO))
    job_queue.run_daily(job_varredura_agendada, time=time(hour=18, minute=0, second=0, tzinfo=FUSO_HORARIO))

    print("⏰ Varreduras diárias configuradas para 08:00 e 18:00 (Fuso Teresina).", flush=True)
    print("🚀 AlertaSUS 2.0 em execução com sucesso!", flush=True)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()