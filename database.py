import asyncio
import logging
from config import supabase, BOT_APP
from scraper import consultar_status_fms, montar_mensagem_regulacao

async def executar_cadastro_regulacao(
    chat_id: int,
    numero_reg: str,
    nome_paciente: str | None = None,
    data_nascimento: str | None = None,
    email: str | None = None
) -> tuple[bool, str]:
    nome_salvar = nome_paciente or "Aguardando consulta"
    data_salvar = data_nascimento or "Não informada"

    resultado = await consultar_status_fms(numero_reg)

    if not resultado.get("sucesso"):
        return False, "Não foi possível verificar a regulação na FMS Teresina neste momento."

    try:
        dados_payload = {
            "id_do_chat": chat_id,
            "numero_reg": str(numero_reg),
            "status_anterior": resultado.get("status_resumido", "Pendente"),
            "nome_paciente": nome_salvar,
            "data_nascimento": data_salvar,
            "email": email,
        }

        existente = await asyncio.to_thread(
            lambda: supabase.table("AlertaSUS_2.0")
            .select("*")
            .eq("id_do_chat", chat_id)
            .eq("numero_reg", str(numero_reg))
            .execute()
        )

        if existente.data:
            await asyncio.to_thread(
                lambda: supabase.table("AlertaSUS_2.0")
                .update(dados_payload)
                .eq("id_do_chat", chat_id)
                .eq("numero_reg", str(numero_reg))
                .execute()
            )
            msg_retorno = f"ℹ️ Regulação `{numero_reg}` já cadastrada! Dados atualizados."
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
                f"⏰ *Monitoramento automático:* varreduras diárias às *08:00* e *18:00*."
            )

        if BOT_APP:
            await BOT_APP.bot.send_message(chat_id=chat_id, text=msg_retorno, parse_mode="Markdown")

        return True, "Cadastro realizado com sucesso!"

    except Exception as e:
        logging.error(f"Erro ao salvar no Supabase: {e}")
        return False, "Ocorreu um erro ao gravar no banco de dados."