import os
import json
import logging
import threading
import asyncio
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

import config
from config import TELEGRAM_BOT_TOKEN, PORT, supabase
from scraper import consultar_status_fms, montar_mensagem_regulacao
import handlers
from handlers import (
    start,
    comando_ajuda,
    abrir_link_cadastro,
    comando_verificar_todas,
    iniciar_verificar_especifico,
    processar_verificar_especifico,
    iniciar_corrigir,
    processar_corrigir_antigo,
    processar_corrigir_novo,
    iniciar_excluir,
    processar_excluir_id,
    processar_excluir_confirmacao,
    cancelar_operacao,
    configurar_menu_comandos,
    CONSULTAR_ID,
    CORRIGIR_ANTIGO,
    CORRIGIR_NOVO,
    EXCLUIR_ID,
    EXCLUIR_CONFIRM,
)
from database import executar_cadastro_regulacao

# Servidor de Health Check para o Railway / API Externa
class HealthCheckHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
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

                if not chat_id or not numero_reg:
                    self._responder_json({"sucesso": False, "mensagem": "Dados incompletos."}, 400)
                    return

                future = asyncio.run_coroutine_threadsafe(
                    executar_cadastro_regulacao(chat_id, numero_reg), config.MAIN_LOOP
                )
                sucesso, mensagem = future.result(timeout=20.0)
                self._responder_json({"sucesso": sucesso, "mensagem": mensagem})

            except Exception as e:
                logging.error(f"Erro na API de cadastro: {e}")
                self._responder_json({"sucesso": False, "mensagem": str(e)}, 500)

    def _responder_json(self, payload: dict, status_code: int = 200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

def run_health_check():
    server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
    server.serve_forever()

def main():
    print("🤖 Iniciando AlertaSUS_2.0...", flush=True)

    # Inicia Servidor Web em Background
    threading.Thread(target=run_health_check, daemon=True).start()

    # Prepara App Telegram
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(configurar_menu_comandos).build()
    config.BOT_APP = app

    try:
        config.MAIN_LOOP = asyncio.get_running_loop()
    except RuntimeError:
        config.MAIN_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(config.MAIN_LOOP)

    # Handlers Básicos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", comando_ajuda))

    # 1. Cadastrar Nova (Link Web)
    app.add_handler(CommandHandler("cadastrar", abrir_link_cadastro))
    app.add_handler(MessageHandler(filters.Regex("^(➕ Cadastrar Nova|Cadastrar nova)$"), abrir_link_cadastro))

    # 2. Verificar Todas
    app.add_handler(CommandHandler("verificar", comando_verificar_todas))
    app.add_handler(MessageHandler(filters.Regex("^(📋 Verificar Todas|Consultar Todos)$"), comando_verificar_todas))

    # 3. Verificar Específico (ConversationHandler)
    conv_verificar_especifico = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^(🔍 Verificar Específico|Consultar Específico)$"), iniciar_verificar_especifico),
            CommandHandler("consultar", iniciar_verificar_especifico),
        ],
        states={
            CONSULTAR_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, processar_verificar_especifico)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    )

    # 4. Corrigir ID (ConversationHandler)
    conv_corrigir = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^(✏️ Corrigir ID|Corrigir)$"), iniciar_corrigir),
            CommandHandler("corrigir", iniciar_corrigir),
        ],
        states={
            CORRIGIR_ANTIGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, processar_corrigir_antigo)],
            CORRIGIR_NOVO: [MessageHandler(filters.TEXT & ~filters.COMMAND, processar_corrigir_novo)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    )

    # 5. Excluir ID com Confirmação (ConversationHandler)
    conv_excluir = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^(❌ Excluir Regulação|Excluir)$"), iniciar_excluir),
            CommandHandler("excluir", iniciar_excluir),
        ],
        states={
            EXCLUIR_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, processar_excluir_id)],
            EXCLUIR_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, processar_excluir_confirmacao)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    )

    # Registrar ConversationHandlers
    app.add_handler(conv_verificar_especifico)
    app.add_handler(conv_corrigir)
    app.add_handler(conv_excluir)

    # Handler do menu de Ajuda
    app.add_handler(MessageHandler(filters.Regex("^(ℹ️ Ajuda|Ajuda / Manual)$"), comando_ajuda))

    print("🚀 AlertaSUS 2.0 pronto e rodando!", flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()