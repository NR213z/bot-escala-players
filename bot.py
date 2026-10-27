"""Bot de recordatorios de coberturas de Players.

Modos: webhook (un update de Telegram, vía repository_dispatch), remind hoy|manana
(recordatorios por cron), poll (getUpdates manual, solo sirve si no hay webhook activo).
"""
import html
import json
import os
import re
import sys
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import requests

from parser import parse_cronograma, parse_escala_header, sin_acentos, MESES, resolver_anio

TOKEN = os.environ["TELEGRAM_TOKEN"]
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BOT_USERNAME = "escala_players_bot"
API = f"https://api.telegram.org/bot{TOKEN}"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
TZ = ZoneInfo("America/Argentina/Buenos_Aires")

PROMPT_SISTEMA = (
    "Sos el bot de recordatorios de coberturas de 'Players' (un equipo que cubre un "
    "programa llamado Algo Más). Hablás en español rioplatense, cercano, con onda, "
    "breve (esto es un chat, no un ensayo). Tus únicas tres funciones reales son: "
    "1) leer el cronograma mensual de coberturas y guardar las fechas de Players, "
    "2) guardar la escala de nombres (con @menciones) de quién cubre cada fecha, "
    "3) mandar recordatorios el día anterior y el mismo día de cada cobertura. "
    "Para esas tres cosas, el mensaje tiene que venir en el formato fijo que ya "
    "conocés (si alguien te pide anotar algo pero no vino en ese formato, explicale "
    "que no lo reconociste y qué formato esperás). Para cualquier otra cosa que te "
    "digan, charlá normal y con onda, pero dejando claro si hace falta que tus "
    "poderes reales son solo esos tres. Nada de Markdown con asteriscos ni "
    "almohadillas, Telegram no los re-interpreta: texto plano."
)

NOMBRES_MES = {v: k for k, v in MESES.items() if k != "setiembre"}


def ahora():
    from datetime import datetime
    return datetime.now(TZ).date()


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "offset": 0,
        "eventos": [],
        "nombres": {},
        "pendiente": None,
        "pendiente_nombres": None,
        "pendiente_limpiar": False,
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


def preguntar_gemini(texto):
    if not GEMINI_API_KEY:
        return None
    import time as _time
    cuerpo = {
        "system_instruction": {"parts": [{"text": PROMPT_SISTEMA}]},
        "contents": [{"role": "user", "parts": [{"text": limpiar_mencion(texto) or "hola"}]}],
    }
    # El free tier de Gemini devuelve 503 (sobrecarga) con cierta frecuencia:
    # un reintento rápido alcanza para la mayoría de los casos.
    for intento in range(2):
        try:
            r = requests.post(GEMINI_URL, params={"key": GEMINI_API_KEY}, json=cuerpo, timeout=25)
            r.raise_for_status()
            data = r.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            print(f"[error] Gemini falló (intento {intento + 1}): {e}")
            if intento == 0:
                _time.sleep(2)
    return None


def charlar(chat_id, texto):
    respuesta = preguntar_gemini(texto)
    if respuesta:
        enviar(chat_id, respuesta, parse_mode=None)


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
        charlar(chat_id, texto)


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
    t0 = time.monotonic()
    try:
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": GEMINI_API_KEY},
            timeout=15,
        )
        nombres = [m.get("name") for m in r.json().get("models", []) if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        print(f"[gemini-test] status={r.status_code} elapsed={time.monotonic()-t0:.1f}s modelos_generateContent={nombres}")
    except Exception as e:
        print(f"[gemini-test] excepcion tras {time.monotonic()-t0:.1f}s: {e}")
    t1 = time.monotonic()
    respuesta = preguntar_gemini("decime 'hola' nada mas, como prueba")
    print(f"[gemini-generate-test] elapsed={time.monotonic()-t1:.1f}s respuesta={respuesta!r}")


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
        mensaje = f"{cuando} Players cubre {categorias} 📣"
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
    else:
        print(f"Modo desconocido: {modo}")
        sys.exit(1)


if __name__ == "__main__":
    main()
