import os
import re
import random
import asyncio
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

async def consultar_status_fms(numero_reg: str, max_tentativas: int = 3) -> dict:
    # 🛡️ Proteção Antibloqueio / Anti-burst (Jitter)
    atraso = random.uniform(1.5, 3.5)
    await asyncio.sleep(atraso)

    if not SCRAPER_KEY:
        logging.error("A variável de ambiente SCRAPER_KEY não foi configurada.")
        return {"sucesso": False, "mensagem": "Erro de configuração no servidor."}

    url_fms_target = f"{URL_BUSCA_FMS}?number_id={numero_reg}"
    scraper_url = f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={url_fms_target}&country_code=br"

    # 🔄 Loop de tentativas automáticas em caso de instabilidade ou timeout
    for tentativa in range(1, max_tentativas + 1):
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=35.0) as client:
                resposta = await client.get(scraper_url)

                if resposta.status_code != 200:
                    logging.warning(f"Tentativa {tentativa}/{max_tentativas} - Erro HTTP {resposta.status_code} na ScraperAPI.")
                    if tentativa < max_tentativas:
                        await asyncio.sleep(2)
                        continue
                    return {"sucesso": False, "mensagem": f"Erro HTTP {resposta.status_code}"}

                soup = BeautifulSoup(resposta.text, "html.parser")
                texto_pagina = soup.get_text().lower()

                if "nenhum registro" in texto_pagina or "não encontrado" in texto_pagina:
                    return {
                        "sucesso": False,
                        "mensagem": f"⚠️ A regulação *{numero_reg}* não foi encontrada no portal da FMS."
                    }

                card = soup.find("div", class_="card-body") or soup

                # Captura blocos de alertas e avisos (ex: Revalidação / UBS)
                alertas = [
                    re.sub(r"\s+", " ", a.get_text(" ", strip=True))
                    for a in card.find_all("div", class_=re.compile(r"alert"))
                ]
                alerta_texto = "\n".join(alertas) if alertas else None

                # Extrai os pares rótulo (h4) -> valor (p)
                campos = {}
                for h4 in card.find_all("h4", class_="card-title") or soup.find_all("h4"):
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

                # Se a página respondeu mas veio vazia por falha no carregamento, tenta novamente
                if not campos and situacao == "Informada no portal" and not alerta_texto:
                    if tentativa < max_tentativas:
                        logging.warning(f"Tentativa {tentativa}/{max_tentativas} - Conteúdo incompleto para a Regulação {numero_reg}. Re-tentando...")
                        await asyncio.sleep(2)
                        continue

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

        except (httpx.TimeoutException, httpx.RequestError) as e:
            logging.warning(f"Tentativa {tentativa}/{max_tentativas} falhou por conexão/timeout na FMS (Reg {numero_reg}): {e}")
            if tentativa < max_tentativas:
                await asyncio.sleep(2.5)

    return {"sucesso": False, "mensagem": "Tempo limite de conexão excedido ao acessar a FMS."}

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