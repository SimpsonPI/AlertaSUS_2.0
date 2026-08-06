import os
import json
import logging
import threading
import asyncio
import traceback
from datetime import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

import config
from config import TELEGRAM_BOT_TOKEN, FUSO_HORARIO, PORT, supabase
from scraper import consultar_status_fms, montar_mensagem_regulacao
from handlers import (
    start,
    comando_ajuda,
    comando_cadastrar,
    comando_verificar_agora,
    comando_excluir,
    comando_corrigir,
    processar_texto_usuario,
    configurar_menu_comandos,
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

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", comando_ajuda))
    app.add_handler(CommandHandler("cadastrar", comando_cadastrar))
    app.add_handler(CommandHandler("verificar", comando_verificar_agora))
    app.add_handler(CommandHandler("excluir", comando_excluir))
    app.add_handler(CommandHandler("corrigir", comando_corrigir))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, processar_texto_usuario))

    # Agendamento Diário (08:00 e 18:00 - Teresina)
    job_queue = app.job_queue
    job_queue.run_daily(job_varredura_agendada, time=time(hour=8, minute=0, second=0, tzinfo=FUSO_HORARIO))
    job_queue.run_daily(job_varredura_agendada, time=time(hour=18, minute=0, second=0, tzinfo=FUSO_HORARIO))

    print("🚀 AlertaSUS 2.0 pronto e rodando!", flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()