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
    for titulo in soup.find_all(["h4", "h5"]):
        if titulo.get_text(strip=True).lower() != rotulo_normalizado:
            continue
        paragrafo = titulo.find_next_sibling(["p", "div", "span"])
        if paragrafo:
            valor = paragrafo.get_text(strip=True)
            if valor:
                return valor
    return None

def _extrair_dados_html(soup: BeautifulSoup) -> dict:
    """Extrai e mapeia todos os campos da FMS (seja agendado ou em fila)."""
    card = soup.find("div", class_="card-body") or soup

    # 1. Captura de Alertas e Avisos em caixas de destaque
    alertas = [
        re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        for a in card.find_all("div", class_=re.compile(r"alert|bg-success|alert-success", re.I))
    ]
    alerta_texto = "\n".join(alertas) if alertas else None

    # 2. Varredura de Títulos (h4, h5, card-title)
    campos_brutos = {}
    dados_mapeados = {
        "data_consulta": None,
        "autorizacao": None,
        "estabelecimento": None,
        "endereco": None,
        "telefone": None,
        "situacao": None,
        "posicao_fila": None,
        "previsao_atendimento": None,
    }

    titulos = card.find_all(["h4", "h5"], class_=re.compile(r"card-title", re.I)) or card.find_all(["h4", "h5"])

    for elem in titulos:
        rotulo = elem.get_text(strip=True)
        if not rotulo or "_" in rotulo:
            continue

        p = elem.find_next_sibling(["p", "span", "div"])
        if not p and elem.parent:
            p = elem.parent.find(["p", "span", "div"], class_=re.compile(r"card-text|badge", re.I))

        if p:
            valor = re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip()
            if valor:
                campos_brutos[rotulo] = valor
                rotulo_lower = rotulo.lower()

                # Mapeamento dinâmico para chaves padronizadas
                if "data e hora" in rotulo_lower:
                    dados_mapeados["data_consulta"] = valor
                elif "autorização" in rotulo_lower:
                    dados_mapeados["autorizacao"] = valor
                elif "estabelecimento" in rotulo_lower:
                    dados_mapeados["estabelecimento"] = valor
                elif "endereço" in rotulo_lower:
                    dados_mapeados["endereco"] = valor
                elif "telefone" in rotulo_lower:
                    dados_mapeados["telefone"] = valor
                elif "situação" in rotulo_lower:
                    dados_mapeados["situacao"] = valor
                elif "posição" in rotulo_lower:
                    dados_mapeados["posicao_fila"] = valor
                elif "previsão" in rotulo_lower:
                    dados_mapeados["previsao_atendimento"] = valor

    # 3. Determinação da Situação do Agendamento
    situacao = dados_mapeados["situacao"] or campos_brutos.get("Situação") or _extrair_valor_campo_fms(soup, "Situação")

    if not situacao:
        if dados_mapeados["data_consulta"] or (alerta_texto and "MARCADO" in alerta_texto.upper()):
            situacao = "MARCADA"
        else:
            situacao = "Informada no portal"

    dados_mapeados["situacao"] = situacao
    dados_mapeados["posicao_fila"] = dados_mapeados["posicao_fila"] or campos_brutos.get("Posição da Fila") or _extrair_valor_campo_fms(soup, "Posição da Fila") or "Não informada"
    dados_mapeados["previsao_atendimento"] = dados_mapeados["previsao_atendimento"] or campos_brutos.get("Previsão de atendimento") or _extrair_valor_campo_fms(soup, "Previsão de atendimento") or "Não informada"

    # Montagem do resumo de status
    partes_resumo = [f"{k}: {v}" for k, v in campos_brutos.items()]
    if alerta_texto:
        partes_resumo.append(f"Alerta: {alerta_texto}")

    status_resumido = " | ".join(partes_resumo) if partes_resumo else f"Situação: {situacao}"

    return {
        "sucesso": True,
        "encontrado": True,
        "situacao": situacao,
        "posicao_fila": dados_mapeados["posicao_fila"],
        "previsao_atendimento": dados_mapeados["previsao_atendimento"],
        "data_consulta": dados_mapeados["data_consulta"],
        "autorizacao": dados_mapeados["autorizacao"],
        "estabelecimento": dados_mapeados["estabelecimento"],
        "endereco": dados_mapeados["endereco"],
        "telefone": dados_mapeados["telefone"],
        "alerta_fms": alerta_texto,
        "campos": campos_brutos,
        "status_resumido": status_resumido,
    }

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

async def consultar_status_fms(numero_reg: str, max_tentativas: int = 2) -> dict:
    # 🛡️ Proteção Antibloqueio / Anti-burst (Jitter)
    atraso = random.uniform(1.0, 2.0)
    await asyncio.sleep(atraso)

    url_fms_target = f"{URL_BUSCA_FMS}?number_id={numero_reg}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    # 🚀 1. TENTATIVA DIRETA AO PORTAL DA FMS (Resposta instantânea)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=12.0, headers=headers) as client:
            resposta = await client.get(url_fms_target)
            if resposta.status_code == 200 and "nenhum registro" not in resposta.text.lower():
                soup = BeautifulSoup(resposta.text, "html.parser")
                return _extrair_dados_html(soup)
    except Exception as e:
        logging.info(f"Acesso direto à FMS falhou ou bloqueou ({e}). Acionando ScraperAPI...")

    # 🌐 2. FALLBACK VIA SCRAPERAPI
    if not SCRAPER_KEY:
        return {"sucesso": False, "mensagem": "Erro de configuração na chave do ScraperAPI."}

    scraper_url = f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={url_fms_target}"

    for tentativa in range(1, max_tentativas + 1):
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=45.0) as client:
                resposta = await client.get(scraper_url)

                if resposta.status_code != 200:
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

                return _extrair_dados_html(soup)

        except (httpx.TimeoutException, httpx.RequestError) as e:
            logging.warning(f"Tentativa ScraperAPI {tentativa}/{max_tentativas} falhou (Reg {numero_reg}): {e}")
            if tentativa < max_tentativas:
                await asyncio.sleep(2)

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
        situacao = resultado.get("situacao") or "Informada no portal"
        data_consulta = resultado.get("data_consulta")
        autorizacao = resultado.get("autorizacao")
        estabelecimento = resultado.get("estabelecimento")
        endereco = resultado.get("endereco")
        telefone = resultado.get("telefone")
        alerta = resultado.get("alerta_fms")

        linhas.append(f"📌 *Situação:* *{escape_markdown(str(situacao), version=1)}*")

        # Se houver consulta agendada, constrói o bloco do agendamento
        if data_consulta or estabelecimento:
            linhas.append("")
            linhas.append("📅 *DADOS DO AGENDAMENTO*")
            if data_consulta:
                linhas.append(f"• *Data/Hora:* {escape_markdown(str(data_consulta), version=1)}")
            if autorizacao:
                linhas.append(f"• *Autorização:* `{escape_markdown(str(autorizacao), version=1)}`")

            linhas.append("")
            linhas.append("🏥 *LOCAL DO ATENDIMENTO*")
            if estabelecimento:
                linhas.append(f"• *Local:* {escape_markdown(str(estabelecimento), version=1)}")
            if endereco:
                linhas.append(f"• *Endereço:* {escape_markdown(str(endereco), version=1)}")
            if telefone:
                linhas.append(f"• *Telefone:* {escape_markdown(str(telefone), version=1)}")

            if alerta:
                linhas.append("")
                linhas.append(f"⚠️ *AVISO:* _{escape_markdown(str(alerta), version=1)}_")
        else:
            # Dados padrão de regulação na fila
            posicao = resultado.get("posicao_fila") or "Não informada"
            previsao = resultado.get("previsao_atendimento") or "Não informada"
            linhas.append(f"• *Posição da Fila:* {escape_markdown(str(posicao), version=1)}")
            linhas.append(f"• *Previsão de atendimento:* {escape_markdown(str(previsao), version=1)}")

            if alerta:
                linhas.append("")
                linhas.append(f"⚠️ *AVISO:* _{escape_markdown(str(alerta), version=1)}_")

    return "\n".join(linhas)