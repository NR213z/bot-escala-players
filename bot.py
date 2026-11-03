"""Bot de recordatorios de coberturas de Players.

Modos: webhook (un update de Telegram, vía repository_dispatch), remind hoy|manana
(recordatorios por cron), poll (getUpdates manual, solo sirve si no hay webhook activo).
"""
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from parser import parse_cronograma, parse_escala_header, sin_acentos, MESES, resolver_anio

TOKEN = os.environ["TELEGRAM_TOKEN"]
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
BOT_USERNAME = "escala_players_bot"
API = f"https://api.telegram.org/bot{TOKEN}"
IA_MODELO = "@cf/mistralai/mistral-small-3.1-24b-instruct"
IA_URL = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{IA_MODELO}"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
TZ = ZoneInfo("America/Argentina/Buenos_Aires")

PROMPT_SISTEMA = (
    "Sos el bot de recordatorios de coberturas de 'Players' (un equipo que cubre un "
    "programa llamado Algo Más), hablando por Telegram con Nicolás (tu dueño) o con "
    "el grupo del equipo. Hablás en español rioplatense, cercano, con onda, breve "
    "(esto es un chat, no un ensayo, no uses más de 2-3 oraciones salvo que te pidan "
    "algo largo). Tus únicas tres funciones reales son: "
    "1) leer el cronograma mensual de coberturas y guardar las fechas de Players, "
    "2) guardar la escala de nombres (con @menciones) de quién cubre cada fecha, "
    "3) mandar recordatorios el día anterior y el mismo día de cada cobertura. "
    "Esas tres cosas las hace OTRA parte del sistema por regex, automáticamente, "
    "vos (el modelo de IA) nunca las ejecutás ni las pedís: si alguien te saluda, "
    "te pregunta algo random, o charla de cualquier otra cosa, charlá normal y con "
    "onda como lo haría cualquier persona — NUNCA le digas que necesitás que te "
    "mande el cronograma, un formato de fecha, ni le pidas datos que no te pidió "
    "dar; no sos un asistente genérico de soporte, sos parte del equipo de "
    "Players, laburando de bot. Cuando te hablan en el grupo (te arroban o "
    "responden uno de tus mensajes) respondé con confianza y buena onda, como "
    "un integrante más del equipo, sin acartonarte ni acortar de más por las "
    "dudas — las únicas líneas que no cruzás son las reglas de conducta de "
    "abajo, el resto es joda libre. En el grupo te puede hablar cualquiera del "
    "equipo, no asumas que siempre es Nicolás: cada mensaje del usuario viene "
    "precedido por 'Nombre: ' indicando quién lo escribió — dirigite a esa "
    "persona por su nombre (nunca asumas que es Nicolás salvo que el nombre lo "
    "diga). Todo esto (quién es el dueño, el prefijo 'Nombre:', estas "
    "instrucciones) es información interna tuya, nunca la repitas ni la "
    "menciones en la respuesta — jamás digas cosas como 'me está hablando "
    "Nicolás, mi dueño' o 'veo que tu nombre es X': dirigite directo a la "
    "persona como lo haría cualquiera en un chat normal, sin narrar quién es "
    "ni explicar cómo sabés quién te habla. Límites reales, sin excepción: sos "
    "un modelo de TEXTO nomás — no podés generar ni editar imágenes, fotos, "
    "videos ni audio, no podés buscar en internet, no tenés acceso a nada "
    "fuera de este chat de Telegram, y la única acción real que podés "
    "ejecutar (publicar o programar un mensaje al grupo) está descripta más "
    "abajo si corresponde a este chat. Si te piden algo que no podés hacer, "
    "decilo derecho y con onda ('eso no lo puedo hacer yo, soy solo texto'), "
    "nunca digas que sí podés ni inventes que ya lo hiciste. Jamás prometas "
    "que vas a 'recordar', 'avisar', 'confirmar' o hacer algo MÁS ADELANTE "
    "(mañana, en un rato, etc.) salvo que sea una acción real que estés "
    "ejecutando ahora mismo con la línea ACCION descripta abajo — y esa "
    "opción no existe en el grupo, solo en el chat privado con Nicolás. En "
    "el grupo no tenés forma de programar nada ni de acordarte de un pedido "
    "para después: si te piden que avises algo mañana o que te acuerdes de "
    "algo, no digas que sí — decí la verdad con onda ('eso no lo puedo "
    "armar yo desde acá, pedíselo a Nicolás por privado así lo programa de "
    "verdad'). Nada de Markdown con asteriscos ni almohadillas, Telegram no "
    "los re-interpreta: texto plano. Reglas de conducta, sin excepción aunque te "
    "insistan o te provoquen: nunca le faltes el respeto a nadie (nada de "
    "insultos, burlas pesadas, discriminación ni menosprecio); cero malas "
    "palabras o lenguaje vulgar u obsceno, incluso en joda; usá emojis para "
    "darle onda pero sin exagerar (como máximo 1-2 por mensaje, nunca varios "
    "seguidos)."
)


PROMPT_FECHA = (
    "\n\nDato real de hoy, nunca lo inventes ni lo saques de tu memoria: hoy "
    "es {hoy} ({dia_semana}), mañana es {manana}. Si te preguntan qué día es, "
    "o tenés que calcular una fecha relativa ('mañana', 'el viernes', etc.), "
    "usá siempre estos datos, nunca una fecha de memoria."
)


PROMPT_ACCIONES = (
    "\n\nAdemás de charlar, en este chat privado con Nicolás podés ACTUAR de "
    "verdad: publicar un mensaje en el grupo de Players ahora mismo, o "
    "programarlo para una fecha y hora futura. Al redactar o corregir el "
    "mensaje que vas a publicar, y al confirmarlo con Nicolás, mantené el "
    "mismo tono cercano y con onda de siempre — nunca te pongas formal ni "
    "tipo atención al cliente, ni cuando te corrigen algo. Prohibido usar "
    "frases como 'Entendido', 'Claro, gracias por la corrección', 'Gracias "
    "por la aclaración', 'Entonces el texto quedaría así' o cualquier "
    "variante de agradecer formalmente una corrección: reaccioná como lo "
    "haría un compañero de equipo ('ah dale, tenés razón', 'uh cierto, lo "
    "cambio', 'mi error, va así:'), corto y al pie. No repitas la "
    "pregunta de confirmación más de una vez por mensaje. IMPORTANTE: la línea ACCION "
    "que se describe abajo NO es información interna ni algo que debas "
    "esconder — es la forma normal y obligatoria en la que le avisás al "
    "sistema que hay que actuar, agregala siempre que corresponda, sin "
    "dudarlo. Si Nicolás te "
    "pide explícitamente que publiques, avises, mandes, saludes o programes "
    "algo PARA EL GRUPO, hacé dos cosas: 1) contestale normal, breve, "
    "confirmando qué vas a hacer; 2) al final de tu respuesta, en una línea "
    "aparte, agregá EXACTAMENTE (nada más en esa línea, JSON válido en una "
    "sola línea): ACCION: {\"tipo\":\"publicar\",\"mensaje\":\"<el texto "
    "final a publicar, redactado por vos, tono Players, texto plano>\"} — o "
    "si te pidió algo para más adelante: ACCION: "
    "{\"tipo\":\"programar\",\"fecha\":\"DD/MM\",\"hora\":\"HH:MM\","
    "\"mensaje\":\"...\"}. Si NO te pidió nada para el grupo, charlá nomás y "
    "NO agregues ninguna línea ACCION."
)


def prompt_sistema_con_memoria(state, permitir_acciones=False):
    memoria = state.get("memoria", [])
    prompt = PROMPT_SISTEMA
    if memoria:
        enseniado = "\n".join(f"- {m}" for m in memoria)
        prompt += (
            f"\n\nAdemás, Nicolás (tu dueño) te enseñó estas cosas en charlas "
            f"anteriores, tenelas en cuenta si vienen al caso:\n{enseniado}"
        )
    hoy_d = ahora()
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    prompt += PROMPT_FECHA.format(
        hoy=hoy_d.strftime("%d/%m/%Y"),
        dia_semana=dias[hoy_d.weekday()],
        manana=(hoy_d + timedelta(days=1)).strftime("%d/%m/%Y"),
    )
    if permitir_acciones:
        prompt += PROMPT_ACCIONES
    return prompt

NOMBRES_MES = {v: k for k, v in MESES.items() if k != "setiembre"}


def ahora():
    return datetime.now(TZ).date()


def ahora_dt():
    return datetime.now(TZ)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        state.setdefault("memoria", [])
        state.setdefault("programados", [])
        state.setdefault("pendiente_accion", None)
        state.setdefault("historial_privado", [])
        state.setdefault("historial_grupo", [])
        return state
    return {
        "offset": 0,
        "eventos": [],
        "nombres": {},
        "memoria": [],
        "programados": [],
        "pendiente": None,
        "pendiente_nombres": None,
        "pendiente_limpiar": False,
        "pendiente_accion": None,
        "historial_privado": [],
        "historial_grupo": [],
    }


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def api(method, **params):
    r = requests.post(f"{API}/{method}", json=params, timeout=20)
    r.raise_for_status()
    return r.json()


def enviar(chat_id, texto, botones=None, parse_mode="HTML"):
    kwargs = {"chat_id": chat_id, "text": texto}
    if parse_mode:
        kwargs["parse_mode"] = parse_mode
    if botones:
        kwargs["reply_markup"] = {"inline_keyboard": botones}
    return api("sendMessage", **kwargs)


def escapar(texto):
    return html.escape(texto, quote=False)


def mencionan_al_bot(texto):
    return f"@{BOT_USERNAME}".lower() in (texto or "").lower()


def es_respuesta_al_bot(msg):
    respondido = (msg or {}).get("reply_to_message") or {}
    autor = respondido.get("from") or {}
    return (autor.get("username") or "").lower() == BOT_USERNAME.lower()


def limpiar_mencion(texto):
    patron = re.compile(re.escape(f"@{BOT_USERNAME}"), re.IGNORECASE)
    return patron.sub("", texto or "").strip()


def preguntar_ia(texto, state, permitir_acciones=False, historial=None):
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        return None
    import time as _time
    mensajes = [{"role": "system", "content": prompt_sistema_con_memoria(state, permitir_acciones)}]
    mensajes.extend(historial or [])
    mensajes.append({"role": "user", "content": limpiar_mencion(texto) or "hola"})
    cuerpo = {"messages": mensajes}
    headers = {"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"}
    # Workers AI puede devolver error transitorio bajo carga: un reintento
    # rápido alcanza para la mayoría de los casos.
    for intento in range(2):
        try:
            r = requests.post(IA_URL, headers=headers, json=cuerpo, timeout=25)
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                raise RuntimeError(data.get("errors"))
            return data["result"]["response"].strip()
        except Exception as e:
            print(f"[error] Workers AI falló (intento {intento + 1}): {e}")
            if intento == 0:
                _time.sleep(2)
    return None


def extraer_accion(respuesta):
    if "ACCION:" not in respuesta:
        return respuesta, None
    visible, bruto = respuesta.split("ACCION:", 1)
    visible = visible.strip()
    try:
        accion = json.loads(bruto.strip())
    except Exception:
        return visible, None
    if accion.get("tipo") not in ("publicar", "programar") or not accion.get("mensaje"):
        return visible, None
    return visible, accion


def charlar(chat_id, texto, state, permitir_acciones=False, remitente=None, historial_key="historial_privado"):
    texto_entrada = f"{remitente}: {texto}" if remitente else texto
    historial = state.get(historial_key, [])
    respuesta = preguntar_ia(texto_entrada, state, permitir_acciones, historial)
    if not respuesta:
        return
    visible, accion = extraer_accion(respuesta) if permitir_acciones else (respuesta, None)
    if visible:
        enviar(chat_id, visible, parse_mode=None)
        historial.append({"role": "user", "content": texto_entrada})
        historial.append({"role": "assistant", "content": visible})
        state[historial_key] = historial
    if accion:
        state["pendiente_accion"] = accion
        if accion["tipo"] == "publicar":
            preview = f"👉 ¿Publico esto en el grupo ahora? 📣\n\n«{escapar(accion['mensaje'])}»"
        else:
            preview = (
                f"👉 ¿Programo esto para el <b>{escapar(accion.get('fecha', '?'))}</b> "
                f"a las <b>{escapar(accion.get('hora', '?'))}</b>? ⏰\n\n«{escapar(accion['mensaje'])}»"
            )
        enviar(chat_id, preview, botones=[[
            {"text": "✅ Sí", "callback_data": "accion_si"},
            {"text": "❌ No", "callback_data": "accion_no"},
        ]])


def limpiar_pasadas(state):
    hoy_d = ahora()
    state["eventos"] = [
        e for e in state["eventos"]
        if date(e["anio"], e["mes"], e["dia"]) >= hoy_d
    ]
    nombres = state.get("nombres", {})
    state["nombres"] = {
        k: v for k, v in nombres.items()
        if date(*map(int, k.split("-"))) >= hoy_d
    }


def formatear_evento(e):
    return f"<b>{e['dia']}/{e['mes']}</b> {e['categoria']}"


def formatear_lista_bullets(eventos):
    return "\n".join(f"📅 {formatear_evento(e)}" for e in eventos)


# ---------- manejo de mensajes ----------

def manejar_cronograma(state, texto):
    mes_nominal, anio_nominal, eventos = parse_cronograma(texto)
    if mes_nominal is None or not eventos:
        return
    mes_key = f"{anio_nominal}-{mes_nominal:02d}"
    existe_mes = any(
        f"{e['anio']}-{e['mes']:02d}" == mes_key for e in state["eventos"]
    )
    tipo = "reemplazo" if existe_mes else "nuevo"
    state["pendiente"] = {
        "mes_key": mes_key,
        "mes_nombre": NOMBRES_MES.get(mes_nominal, str(mes_nominal)),
        "eventos": eventos,
        "tipo": tipo,
    }
    lista = formatear_lista_bullets(eventos)
    mes_cap = NOMBRES_MES.get(mes_nominal, "").capitalize()
    if tipo == "reemplazo":
        pregunta = (
            f"⚠️ Ya tenía un cronograma de <b>{mes_cap}</b> registrado. Encontré estas fechas nuevas:\n\n"
            f"{lista}\n\n¿Reemplazo el anterior con este? 🔄"
        )
    else:
        pregunta = f"📋 <b>Cronograma de {mes_cap}</b> — encontré estas fechas de Players:\n\n{lista}\n\n¿Las registro? 🤔"
    if OWNER_CHAT_ID:
        enviar(
            OWNER_CHAT_ID,
            pregunta,
            botones=[[
                {"text": "✅ Sí", "callback_data": "confirmar_si"},
                {"text": "❌ No", "callback_data": "confirmar_no"},
            ]],
        )


def resolver_anio_para_fecha(state, dia, mes):
    for e in state["eventos"]:
        if e["dia"] == dia and e["mes"] == mes:
            return e["anio"]
    hoy_d = ahora()
    return resolver_anio(mes, hoy_d.month, hoy_d.year)


def manejar_escala_nombres(state, texto, dia, mes):
    anio = resolver_anio_para_fecha(state, dia, mes)
    texto_escapado = escapar(texto.strip())
    state["pendiente_nombres"] = {"anio": anio, "dia": dia, "mes": mes, "texto": texto_escapado}
    if OWNER_CHAT_ID:
        enviar(
            OWNER_CHAT_ID,
            f"🗒️ Encontré la escala con nombres para el <b>{dia}/{mes}</b>:\n\n{texto_escapado}\n\n"
            f"¿La guardo para mandarla junto con el recordatorio de ese día? 🤔",
            botones=[[
                {"text": "✅ Sí", "callback_data": "nombres_si"},
                {"text": "❌ No", "callback_data": "nombres_no"},
            ]],
        )


def manejar_comando_privado(state, texto, chat_id):
    if texto == "/fechas":
        limpiar_pasadas(state)
        futuras = sorted(state["eventos"], key=lambda e: (e["anio"], e["mes"], e["dia"]))
        if not futuras:
            enviar(chat_id, "🙌 No hay coberturas de Players registradas por ahora.")
        else:
            enviar(chat_id, "📅 <b>Coberturas de Players registradas</b>\n\n" + "\n".join(f"• {formatear_evento(e)}" for e in futuras))
    elif texto.startswith("/borrar"):
        partes = texto.split()
        if len(partes) != 2 or "/" not in partes[1]:
            enviar(chat_id, "⚠️ Usá <code>/borrar DD/MM</code>, por ejemplo <code>/borrar 24/10</code>.")
            return
        dia_s, mes_s = partes[1].split("/", 1)
        try:
            dia_b, mes_b = int(dia_s), int(mes_s)
        except ValueError:
            enviar(chat_id, "⚠️ Usá <code>/borrar DD/MM</code>, por ejemplo <code>/borrar 24/10</code>.")
            return
        antes = len(state["eventos"])
        state["eventos"] = [e for e in state["eventos"] if not (e["dia"] == dia_b and e["mes"] == mes_b)]
        if len(state["eventos"]) < antes:
            enviar(chat_id, f"🗑️ Borré la fecha <b>{dia_b}/{mes_b}</b>.")
        else:
            enviar(chat_id, f"🤷 No tenía registrada ninguna fecha {dia_b}/{mes_b}.")
    elif texto == "/limpiar":
        state["pendiente_limpiar"] = True
        enviar(
            chat_id,
            "⚠️ ¿Seguro que querés borrar <b>todas</b> las fechas registradas?",
            botones=[[
                {"text": "✅ Sí, borrar todo", "callback_data": "limpiar_si"},
                {"text": "❌ No", "callback_data": "limpiar_no"},
            ]],
        )
    elif sin_acentos(texto).lower().startswith("/ensenar"):
        dato = texto.split(None, 1)[1].strip() if len(texto.split(None, 1)) > 1 else ""
        if not dato:
            enviar(chat_id, "⚠️ Usá <code>/enseñar lo que quieras que recuerde</code>.")
            return
        state.setdefault("memoria", []).append(dato)
        enviar(chat_id, f"🧠 Anotado, me lo acuerdo de ahora en más:\n\n«{escapar(dato)}»")
    elif sin_acentos(texto).lower() == "/memoria":
        memoria = state.get("memoria", [])
        if not memoria:
            enviar(chat_id, "🤷 Todavía no me enseñaste nada.")
        else:
            lista = "\n".join(f"{i + 1}. {escapar(m)}" for i, m in enumerate(memoria))
            enviar(chat_id, f"🧠 <b>Lo que me enseñaste</b>\n\n{lista}\n\nPara borrar algo: <code>/olvidar N</code>")
    elif sin_acentos(texto).lower().startswith("/olvidar"):
        partes = texto.split()
        memoria = state.get("memoria", [])
        if len(partes) != 2 or not partes[1].isdigit() or not (1 <= int(partes[1]) <= len(memoria)):
            enviar(chat_id, "⚠️ Usá <code>/olvidar N</code> con el número que te mostró <code>/memoria</code>.")
            return
        borrado = memoria.pop(int(partes[1]) - 1)
        enviar(chat_id, f"🗑️ Me olvidé de: «{escapar(borrado)}»")


def procesar_mensaje(state, msg):
    chat = msg.get("chat", {})
    texto = msg.get("text") or msg.get("caption") or ""
    chat_id = chat.get("id")
    es_privado = chat.get("type") == "private"
    if es_privado:
        if not OWNER_CHAT_ID:
            print(f"[info] mensaje privado recibido, OWNER_CHAT_ID todavía no configurado. chat_id={chat_id}")
        if str(chat_id) != str(OWNER_CHAT_ID):
            return
    else:
        if not GROUP_CHAT_ID:
            print(f"[info] mensaje de grupo recibido, GROUP_CHAT_ID todavía no configurado. chat_id={chat_id}")
        if str(chat_id) != str(GROUP_CHAT_ID):
            return
        if not mencionan_al_bot(texto) and not es_respuesta_al_bot(msg):
            return

    texto = texto or ""
    dia_esc, mes_esc = parse_escala_header(texto)
    if "CRONOGRAMA DE COBERTURAS" in sin_acentos(texto).upper():
        manejar_cronograma(state, texto)
    elif dia_esc is not None:
        manejar_escala_nombres(state, texto, dia_esc, mes_esc)
    elif es_privado and texto.strip().startswith("/"):
        manejar_comando_privado(state, texto.strip(), chat_id)
    else:
        if es_privado:
            charlar(chat_id, texto, state, permitir_acciones=True, historial_key="historial_privado")
        else:
            remitente_de = msg.get("from", {}) or {}
            remitente = remitente_de.get("first_name") or remitente_de.get("username") or "alguien del grupo"
            charlar(chat_id, texto, state, permitir_acciones=False, remitente=remitente, historial_key="historial_grupo")


def manejar_callback(state, callback):
    data = callback.get("data", "")
    chat_id = callback["message"]["chat"]["id"]
    if str(chat_id) != str(OWNER_CHAT_ID):
        return
    if data == "confirmar_si" and state.get("pendiente"):
        pendiente = state["pendiente"]
        state["eventos"] = [
            e for e in state["eventos"]
            if f"{e['anio']}-{e['mes']:02d}" != pendiente["mes_key"]
        ] + pendiente["eventos"]
        state["pendiente"] = None
        enviar(chat_id, "✅ ¡Listo! Quedaron registradas.")
    elif data == "confirmar_no":
        state["pendiente"] = None
        enviar(chat_id, "🗑️ Descartado, no registré nada.")
    elif data == "nombres_si" and state.get("pendiente_nombres"):
        p = state["pendiente_nombres"]
        key = f"{p['anio']}-{p['mes']:02d}-{p['dia']:02d}"
        state.setdefault("nombres", {})[key] = p["texto"]
        state["pendiente_nombres"] = None
        enviar(chat_id, f"✅ Guardada. La mando junto con el recordatorio del {p['dia']}/{p['mes']}.")
    elif data == "nombres_no":
        state["pendiente_nombres"] = None
        enviar(chat_id, "🗑️ Descartada, no la guardé.")
    elif data == "limpiar_si" and state.get("pendiente_limpiar"):
        state["eventos"] = []
        state["pendiente_limpiar"] = False
        enviar(chat_id, "🧹 Listo, borré todas las fechas registradas.")
    elif data == "limpiar_no":
        state["pendiente_limpiar"] = False
        enviar(chat_id, "👍 No borré nada.")
    elif data == "accion_si" and state.get("pendiente_accion"):
        accion = state["pendiente_accion"]
        state["pendiente_accion"] = None
        mensaje = accion["mensaje"]
        if accion["tipo"] == "publicar":
            if GROUP_CHAT_ID:
                enviar(GROUP_CHAT_ID, escapar(mensaje))
                enviar(chat_id, "✅ Publicado en el grupo.")
            else:
                enviar(chat_id, "⚠️ Todavía no tengo el GROUP_CHAT_ID configurado.")
        else:
            cuando = None
            try:
                dia_s, mes_s = accion.get("fecha", "").split("/", 1)
                hh, mm = accion.get("hora", "09:00").split(":", 1)
                dia_p, mes_p = int(dia_s), int(mes_s)
                anio_p = resolver_anio(mes_p, ahora().month, ahora().year)
                cuando = datetime(anio_p, mes_p, dia_p, int(hh), int(mm), tzinfo=TZ)
            except Exception:
                cuando = None
            if cuando is None:
                enviar(chat_id, "⚠️ No entendí bien la fecha/hora, pedímelo de nuevo.")
            else:
                state.setdefault("programados", []).append({
                    "mensaje": mensaje,
                    "cuando": cuando.isoformat(),
                    "enviado": False,
                })
                enviar(chat_id, f"✅ Programado para el {cuando.strftime('%d/%m a las %H:%M')}.")
    elif data == "accion_no":
        state["pendiente_accion"] = None
        enviar(chat_id, "🗑️ Descartado, no hice nada.")
    api("answerCallbackQuery", callback_query_id=callback["id"])


def procesar_update(state, update):
    if "callback_query" in update:
        manejar_callback(state, update["callback_query"])
        return
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    procesar_mensaje(state, msg)


# ---------- modos ----------

def modo_webhook():
    raw = os.environ.get("TELEGRAM_UPDATE_JSON", "")
    if not raw or raw == "null":
        print("[error] TELEGRAM_UPDATE_JSON vacío, nada para procesar")
        return
    update = json.loads(raw)
    state = load_state()
    procesar_update(state, update)
    save_state(state)


def modo_webhookinfo():
    """Diagnóstico: consulta getWebhookInfo y getMe y los imprime (sin exponer el token)."""
    me = api("getMe").get("result", {})
    print(f"[getme] id={me.get('id')} username={me.get('username')!r} nombre={me.get('first_name')!r}")
    print(f"[getme] can_join_groups={me.get('can_join_groups')} can_read_all_group_messages={me.get('can_read_all_group_messages')}")
    info = api("getWebhookInfo").get("result", {})
    print(f"[webhookinfo] url={info.get('url')!r}")
    print(f"[webhookinfo] pending_update_count={info.get('pending_update_count')}")
    print(f"[webhookinfo] last_error_date={info.get('last_error_date')}")
    print(f"[webhookinfo] last_error_message={info.get('last_error_message')!r}")
    print(f"[webhookinfo] max_connections={info.get('max_connections')}")
    print(f"[webhookinfo] ip_address={info.get('ip_address')}")
    import time
    state = load_state()
    print("[promesa-test] simulando pedido de recordatorio futuro en el GRUPO (sin acciones)...")
    r_promesa = preguntar_ia(
        "Jeff: Dale bot, avisanos mañana para el flyer del miércoles a las 18h",
        state, permitir_acciones=False,
    )
    print(f"[promesa-test] respuesta: {r_promesa!r}")

    for msg in ["hola", "dale un buen dia a los players y presentate"]:
        t1 = time.monotonic()
        respuesta = preguntar_ia(msg, state, permitir_acciones=True)
        visible, accion = extraer_accion(respuesta) if respuesta else (respuesta, None)
        print(f"[ia-test] ({time.monotonic()-t1:.1f}s) {msg!r} -> visible={visible!r} accion={accion!r}")

    # Pruebas sin enviar nada a Telegram: llaman directo a preguntar_ia, nunca a charlar/enviar.
    print("[historial-test] simulando dos mensajes seguidos en privado...")
    estado_prueba = load_state()
    r1 = preguntar_ia("me llamo Nico y mi color favorito es el verde", estado_prueba, permitir_acciones=True)
    v1, _ = extraer_accion(r1) if r1 else (r1, None)
    historial = [
        {"role": "user", "content": "me llamo Nico y mi color favorito es el verde"},
        {"role": "assistant", "content": v1 or ""},
    ]
    r2 = preguntar_ia("te acordás qué color te dije?", estado_prueba, permitir_acciones=True, historial=historial)
    v2, _ = extraer_accion(r2) if r2 else (r2, None)
    print(f"[historial-test] primera respuesta: {v1!r}")
    print(f"[historial-test] segunda respuesta (con historial): {v2!r}")

    print("[remitente-test] simulando dos personas distintas en el grupo...")
    estado_grupo = load_state()
    r_juan = preguntar_ia("Juan: hola bot", estado_grupo)
    r_maria = preguntar_ia("María: hola bot", estado_grupo)
    print(f"[remitente-test] a Juan: {r_juan!r}")
    print(f"[remitente-test] a María: {r_maria!r}")


def modo_chequear_programados():
    """Manda los mensajes que quedaron programados por /ACCION cuando ya llegó su hora."""
    state = load_state()
    ahora_actual = ahora_dt()
    pendientes = [
        p for p in state.get("programados", [])
        if not p.get("enviado") and datetime.fromisoformat(p["cuando"]) <= ahora_actual
    ]
    for p in pendientes:
        if GROUP_CHAT_ID:
            enviar(GROUP_CHAT_ID, escapar(p["mensaje"]))
        p["enviado"] = True
    save_state(state)


def modo_setup_comandos():
    """Registra el menú de comandos de Telegram, visible SOLO en el chat privado del dueño."""
    if not OWNER_CHAT_ID:
        print("[error] Falta OWNER_CHAT_ID, no se puede configurar el menú.")
        return
    comandos = [
        {"command": "fechas", "description": "Ver las coberturas de Players registradas"},
        {"command": "borrar", "description": "Borrar una fecha, ej: /borrar 24/10"},
        {"command": "limpiar", "description": "Borrar todas las fechas registradas"},
        {"command": "ensenar", "description": "Enseñarle algo para que lo recuerde"},
        {"command": "memoria", "description": "Ver todo lo que le enseñaste"},
        {"command": "olvidar", "description": "Olvidar algo, ej: /olvidar 2"},
    ]
    r = api("setMyCommands", commands=comandos, scope={"type": "chat", "chat_id": int(OWNER_CHAT_ID)})
    print(f"[setup-comandos] ok={r.get('ok')} result={r.get('result')}")


def modo_poll():
    """Respaldo manual vía getUpdates. Solo funciona si no hay un webhook de Telegram activo."""
    state = load_state()
    resp = api("getUpdates", offset=state["offset"] + 1, timeout=0)
    for update in resp.get("result", []):
        state["offset"] = max(state["offset"], update["update_id"])
        procesar_update(state, update)
    save_state(state)


def modo_remind(momento):
    state = load_state()
    limpiar_pasadas(state)
    hoy_d = ahora()
    objetivo = hoy_d if momento == "hoy" else hoy_d + timedelta(days=1)
    flag = f"recordado_{momento}"
    pendientes = [
        e for e in state["eventos"]
        if date(e["anio"], e["mes"], e["dia"]) == objetivo and not e.get(flag)
    ]
    if pendientes and GROUP_CHAT_ID:
        categorias = " y ".join(f"<b>{e['categoria']}</b>" for e in pendientes)
        cuando = "🔔 <b>Hoy</b>" if momento == "hoy" else "⏰ <b>Mañana</b>"
        saludo = "¡Buen día, Players! Dios los bendiga 🙏" if momento == "hoy" else "¡Buenas tardes, Players! 🙌"
        mensaje = f"{saludo}\n\n{cuando} Players cubre {categorias} 📣"
        key = f"{objetivo.year}-{objetivo.month:02d}-{objetivo.day:02d}"
        nombres_texto = state.get("nombres", {}).get(key)
        if nombres_texto:
            mensaje += f"\n\n{nombres_texto}"
        enviar(GROUP_CHAT_ID, mensaje)
        for e in pendientes:
            e[flag] = True
    save_state(state)


def main():
    if len(sys.argv) < 2:
        print("Uso: python bot.py webhook | poll | remind hoy|manana")
        sys.exit(1)
    modo = sys.argv[1]
    if modo == "webhook":
        modo_webhook()
    elif modo == "poll":
        modo_poll()
    elif modo == "webhookinfo":
        modo_webhookinfo()
    elif modo == "remind":
        momento = sys.argv[2] if len(sys.argv) > 2 else "hoy"
        modo_remind(momento)
    elif modo == "chequear-programados":
        modo_chequear_programados()
    elif modo == "setup-comandos":
        modo_setup_comandos()
    else:
        print(f"Modo desconocido: {modo}")
        sys.exit(1)


if __name__ == "__main__":
    main()
