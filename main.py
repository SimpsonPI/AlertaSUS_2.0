import os
import json
import logging
import threading
import asyncio
import traceback
from datetime import time
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
from config import TELEGRAM_BOT_TOKEN, FUSO_HORARIO, PORT, supabase
from scraper import consultar_status_fms, montar_mensagem_regulacao
import handlers
from handlers import (
    start,
    comando_ajuda,
    comando_verificar_agora,
    iniciar_consulta_especifica,
    processar_consulta_especifica,
    iniciar_cadastro,
    cad_passo_regulacao,
    cad_passo_nome,
    cad_passo_data_nasc,
    cad_passo_email,
    cad_passo_finalizar,
    iniciar_exclusao,
    processar_exclusao,
    iniciar_correcao,
    correcao_passo_antigo,
    correcao_passo_novo,
    cancelar_operacao,
    configurar_menu_comandos,
    CAD_REGULACAO,
    CAD_NOME,
    CAD_DATA_NASC,
    CAD_EMAIL,
    CAD_CELULAR,
    CONSULTAR_ID,
    EXCLUIR_ID,
    CORRIGIR_ANTIGO,
    CORRIGIR_NOVO,
)
from database import executar_cadastro_regulacao

# Servidor de Health Check para o Railway
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

# Varredura Diária
async def job_varredura_agendada(context: ContextTypes.DEFAULT_TYPE):
    logging.info("🔄 Executando varredura diária no portal FMS...")
    try:
        resposta = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0").select("*").execute()
        )
        regulacoes = resposta.data or []

        for reg in regulacoes:
            chat_id = reg.get("id_do_chat")
            numero_reg = reg.get("numero_reg")
            status_anterior = reg.get("status_anterior")

            if not chat_id or not numero_reg:
                continue

            resultado = await consultar_status_fms(numero_reg)

            if resultado.get("sucesso"):
                novo_status = resultado.get("status_resumido", "Desconhecido")
                if novo_status != status_anterior:
                    await asyncio.to_thread(
                        lambda: supabase.table("AlertaSUS_2.0")
                        .update({"status_anterior": novo_status})
                        .eq("id", reg["id"])
                        .execute()
                    )
                    mensagem = montar_mensagem_regulacao(
                        numero_reg, resultado, titulo="🔔 *ATUALIZAÇÃO DE REGULAÇÃO!*"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=mensagem, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Erro na varredura agendada: {traceback.format_exc()}")

def main():
    print("🤖 Iniciando AlertaSUS_2.0...", flush=True)

    # Inicia Servidor Web em Background
    threading.Thread(target=run_health_check, daemon=True).start()

    # Prepara Loop e App
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(configurar_menu_comandos).build()
    config.BOT_APP = app

    try:
        config.MAIN_LOOP = asyncio.get_event_loop()
    except RuntimeError:
        config.MAIN_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(config.MAIN_LOOP)

    # Handlers Globais Estáticos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", comando_ajuda))

    # ConversationHandler: CADASTRO COMPLETO
    conv_cadastro = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^➕ Cadastrar Nova$"), iniciar_cadastro),
            CommandHandler("cadastrar", iniciar_cadastro),
        ],
        states={
            CAD_REGULACAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, cad_passo_regulacao)],
            CAD_NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, cad_passo_nome)],
            CAD_DATA_NASC: [MessageHandler(filters.TEXT & ~filters.COMMAND, cad_passo_data_nasc)],
            CAD_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, cad_passo_email)],
            CAD_CELULAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, cad_passo_finalizar)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    )

    # ConversationHandler: CONSULTA ESPECÍFICA
    conv_consulta_especifica = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🔍 Consultar Específico$"), iniciar_consulta_especifica),
            CommandHandler("consultar", iniciar_consulta_especifica),
        ],
        states={
            CONSULTAR_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, processar_consulta_especifica)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    )

    # ConversationHandler: EXCLUSÃO INTERATIVA
    conv_exclusao = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^❌ Excluir Regulação$"), iniciar_exclusao),
            CommandHandler("excluir", iniciar_exclusao),
        ],
        states={
            EXCLUIR_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, processar_exclusao)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    )

    # ConversationHandler: CORREÇÃO DE ID INTERATIVA
    conv_correcao = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^✏️ Corrigir ID$"), iniciar_correcao),
            CommandHandler("corrigir", iniciar_correcao),
        ],
        states={
            CORRIGIR_ANTIGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, correcao_passo_antigo)],
            CORRIGIR_NOVO: [MessageHandler(filters.TEXT & ~filters.COMMAND, correcao_passo_novo)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    )

    # Registra os ConversationHandlers
    app.add_handler(conv_cadastro)
    app.add_handler(conv_consulta_especifica)
    app.add_handler(conv_exclusao)
    app.add_handler(conv_correcao)

    # Outros Botões do Menu
    app.add_handler(MessageHandler(filters.Regex("^📋 Consultar Todos$") | CommandHandler("verificar"), comando_verificar_agora))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ Ajuda / Manual$"), comando_ajuda))

    print("🚀 AlertaSUS 2.0 pronto e rodando!", flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()