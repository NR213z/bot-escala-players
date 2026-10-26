"""Bot de recordatorios de coberturas de Players. Modos: poll, remind hoy|manana."""
import json
import os
import sys
import unicodedata
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import requests

from parser import parse_cronograma, sin_acentos, MESES

TOKEN = os.environ["TELEGRAM_TOKEN"]
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")
API = f"https://api.telegram.org/bot{TOKEN}"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
TZ = ZoneInfo("America/Argentina/Buenos_Aires")

NOMBRES_MES = {v: k for k, v in MESES.items() if k != "setiembre"}


def ahora():
    from datetime import datetime
    return datetime.now(TZ).date()


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"offset": 0, "eventos": [], "pendiente": None, "pendiente_limpiar": False}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def api(method, **params):
    r = requests.post(f"{API}/{method}", json=params, timeout=20)
    r.raise_for_status()
    return r.json()


def enviar(chat_id, texto, botones=None):
    kwargs = {"chat_id": chat_id, "text": texto}
    if botones:
        kwargs["reply_markup"] = {"inline_keyboard": botones}
    return api("sendMessage", **kwargs)


def limpiar_pasadas(state):
    hoy_d = ahora()
    state["eventos"] = [
        e for e in state["eventos"]
        if date(e["anio"], e["mes"], e["dia"]) >= hoy_d
    ]


def formatear_evento(e):
    return f"{e['dia']}/{e['mes']} {e['categoria']}"


def formatear_lista(eventos):
    return " · ".join(formatear_evento(e) for e in eventos)


# ---------- poll ----------

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
    lista = formatear_lista(eventos)
    if tipo == "reemplazo":
        pregunta = (
            f"Encontré un cronograma de {NOMBRES_MES.get(mes_nominal)} con estas fechas de Players: "
            f"{lista}. Ya había uno registrado para ese mes. ¿Reemplazo el anterior con este?"
        )
    else:
        pregunta = f"Encontré estas fechas de Players: {lista}. ¿Las registro?"
    if OWNER_CHAT_ID:
        enviar(
            OWNER_CHAT_ID,
            pregunta,
            botones=[[
                {"text": "Sí", "callback_data": "confirmar_si"},
                {"text": "No", "callback_data": "confirmar_no"},
            ]],
        )


def manejar_mensaje_privado(state, texto, chat_id):
    if str(chat_id) != str(OWNER_CHAT_ID):
        return
    texto = texto.strip()
    if texto == "/fechas":
        limpiar_pasadas(state)
        futuras = sorted(state["eventos"], key=lambda e: (e["anio"], e["mes"], e["dia"]))
        if not futuras:
            enviar(chat_id, "No hay coberturas de Players registradas.")
        else:
            enviar(chat_id, "Coberturas de Players registradas:\n" + "\n".join(formatear_evento(e) for e in futuras))
    elif texto.startswith("/borrar"):
        partes = texto.split()
        if len(partes) != 2 or "/" not in partes[1]:
            enviar(chat_id, "Usá /borrar DD/MM, por ejemplo /borrar 24/10")
            return
        dia_s, mes_s = partes[1].split("/", 1)
        try:
            dia_b, mes_b = int(dia_s), int(mes_s)
        except ValueError:
            enviar(chat_id, "Usá /borrar DD/MM, por ejemplo /borrar 24/10")
            return
        antes = len(state["eventos"])
        state["eventos"] = [e for e in state["eventos"] if not (e["dia"] == dia_b and e["mes"] == mes_b)]
        if len(state["eventos"]) < antes:
            enviar(chat_id, f"Borré la fecha {dia_b}/{mes_b}.")
        else:
            enviar(chat_id, f"No tenía registrada ninguna fecha {dia_b}/{mes_b}.")
    elif texto == "/limpiar":
        state["pendiente_limpiar"] = True
        enviar(
            chat_id,
            "¿Seguro que querés borrar todas las fechas registradas?",
            botones=[[
                {"text": "Sí, borrar todo", "callback_data": "limpiar_si"},
                {"text": "No", "callback_data": "limpiar_no"},
            ]],
        )


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
        enviar(chat_id, "Listo, lo registré.")
    elif data == "confirmar_no":
        state["pendiente"] = None
        enviar(chat_id, "Descartado, no registré nada.")
    elif data == "limpiar_si" and state.get("pendiente_limpiar"):
        state["eventos"] = []
        state["pendiente_limpiar"] = False
        enviar(chat_id, "Borré todas las fechas registradas.")
    elif data == "limpiar_no":
        state["pendiente_limpiar"] = False
        enviar(chat_id, "No borré nada.")
    api("answerCallbackQuery", callback_query_id=callback["id"])


def modo_poll():
    state = load_state()
    resp = api("getUpdates", offset=state["offset"] + 1, timeout=0)
    for update in resp.get("result", []):
        state["offset"] = max(state["offset"], update["update_id"])
        if "callback_query" in update:
            manejar_callback(state, update["callback_query"])
            continue
        msg = update.get("message")
        if not msg:
            continue
        chat = msg["chat"]
        texto = msg.get("text") or msg.get("caption") or ""
        if chat["type"] == "private":
            if not OWNER_CHAT_ID:
                print(f"[info] mensaje privado recibido, OWNER_CHAT_ID todavía no configurado. chat_id={chat['id']}")
            if str(chat["id"]) == str(OWNER_CHAT_ID) and "CRONOGRAMA DE COBERTURAS" in sin_acentos(texto).upper():
                manejar_cronograma(state, texto)
            else:
                manejar_mensaje_privado(state, texto, chat["id"])
        else:
            if not GROUP_CHAT_ID:
                print(f"[info] mensaje de grupo recibido, GROUP_CHAT_ID todavía no configurado. chat_id={chat['id']}")
            if str(chat["id"]) == str(GROUP_CHAT_ID) and "CRONOGRAMA DE COBERTURAS" in sin_acentos(texto).upper():
                manejar_cronograma(state, texto)
    save_state(state)


# ---------- remind ----------

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
        categorias = " y ".join(e["categoria"] for e in pendientes)
        cuando = "Hoy" if momento == "hoy" else "Mañana"
        enviar(GROUP_CHAT_ID, f"{cuando} Players cubre {categorias}.")
        for e in pendientes:
            e[flag] = True
    save_state(state)


def main():
    if len(sys.argv) < 2:
        print("Uso: python bot.py poll | python bot.py remind hoy|manana")
        sys.exit(1)
    modo = sys.argv[1]
    if modo == "poll":
        modo_poll()
    elif modo == "remind":
        momento = sys.argv[2] if len(sys.argv) > 2 else "hoy"
        modo_remind(momento)
    else:
        print(f"Modo desconocido: {modo}")
        sys.exit(1)


if __name__ == "__main__":
    main()
