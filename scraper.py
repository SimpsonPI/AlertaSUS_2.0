import os
import re
import logging
import httpx
from bs4 import BeautifulSoup
from telegram.helpers import escape_markdown
from config import URL_BUSCA_FMS, SCRAPER_KEY

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

def formatar_data_br(data_str: str | None) -> str:
    """Converte datas de AAAA-MM-DD para DD/MM/AAAA"""
    if not data_str:
        return "Não informada"
    data_limpa = str(data_str).split("T")[0].strip()
    if "-" in data_limpa:
        partes = data_limpa.split("-")
        if len(partes) == 3:
            return f"{partes[2]}/{partes[1]}/{partes[0]}"
    return data_limpa

def nome_paciente_exibicao(nome: str | None) -> str:
    if not nome or not nome.strip() or nome.strip() == "Aguardando consulta":
        return "Não informado"
    return nome.strip()

async def consultar_status_fms(numero_reg: str) -> dict:
    if not SCRAPER_KEY:
        logging.error("A variável de ambiente SCRAPER_KEY não foi configurada.")
        return {"sucesso": False, "mensagem": "Erro de configuração no servidor."}

    url_fms_target = f"{URL_BUSCA_FMS}?number_id={numero_reg}"
    scraper_url = f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={url_fms_target}&country_code=br"

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resposta = await client.get(scraper_url)

            if resposta.status_code != 200:
                logging.error(f"Erro HTTP {resposta.status_code} na ScraperAPI.")
                return {"sucesso": False, "mensagem": f"Erro HTTP {resposta.status_code}"}

            soup = BeautifulSoup(resposta.text, "html.parser")
            texto_pagina = soup.get_text().lower()

            if "nenhum registro" in texto_pagina or "não encontrado" in texto_pagina:
                return {
                    "sucesso": False,
                    "mensagem": f"⚠️ A regulação *{numero_reg}* não foi encontrada no portal da FMS."
                }

            tabela = soup.find("table")
            if not tabela:
                logging.warning(f"Tabela não encontrada no HTML para a regulação {numero_reg}.")
                return {"sucesso": False, "mensagem": "⚠️ Não foi possível extrair a tabela de dados da FMS."}

            card = soup.find("div", class_="card-body") or soup

            alertas = [
                re.sub(r"\s+", " ", a.get_text(" ", strip=True))
                for a in card.find_all("div", class_=re.compile(r"alert"))
            ]
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

            partes_resumo = [f"{k}: {v}" for k, v in campos.items()]
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

def montar_mensagem_regulacao(
    numero_reg: str,
    resultado: dict,
    nome_paciente: str | None = None,
    data_nascimento: str | None = None,
    email: str | None = None,
    titulo: str = "🏥 *SITUAÇÃO DA REGULAÇÃO*",
) -> str:
    nome_esc = escape_markdown(nome_paciente_exibicao(nome_paciente), version=1)
    numero_esc = escape_markdown(str(numero_reg), version=1)
    dt_esc = escape_markdown(formatar_data_br(data_nascimento), version=1)
    email_txt = email.strip() if email else "Não informado"
    email_esc = escape_markdown(email_txt, version=1)

    linhas = [
        titulo,
        "",
        f"👤 *Paciente:* *{nome_esc}*",
        f"🎂 *Data de Nascimento:* {dt_esc}",
        f"📧 *E-mail:* {email_esc}",
        f"🆔 *ID de Regulação:* `{numero_esc}`",
    ]

    if isinstance(resultado, dict):
        status = resultado.get("status_resumido") or resultado.get("status_anterior") or "Não informado"
        posicao = resultado.get("posicao_fila") or "Não informada"
        previsao = resultado.get("previsao_atendimento") or "Não informada"

        linhas.append(f"📌 *Situação:* {escape_markdown(str(status), version=1)}")
        linhas.append(f"• *Posição da Fila:* {escape_markdown(str(posicao), version=1)}")
        linhas.append(f"• *Previsão de atendimento:* {escape_markdown(str(previsao), version=1)}")

    return "\n".join(linhas)