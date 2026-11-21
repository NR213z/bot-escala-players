// El schedule nativo de GitHub Actions no es confiable. Los recordatorios (10 y
// 18 hs ART) se disparan por Cron Trigger de Cloudflare. Todo lo demás — leer el
// cronograma, la escala con nombres, confirmaciones y comandos — llega por
// webhook de Telegram: apenas hay un mensaje nuevo, Telegram le pega a este
// Worker, que dispara un repository_dispatch de GitHub con el update adentro.
// No se pollea nunca.

const GITHUB_REPO = "NR213z/bot-escala-players";
const GITHUB_WORKFLOW = "bot.yml";
const BOT_USERNAME = "escala_players_bot";

const MODO_POR_CRON = {
  "0 13 * * *": "remind-hoy", // 10:00 ART
  "0 21 * * *": "remind-manana", // 18:00 ART
  "*/15 * * * *": "chequear-programados", // mensajes que el dueño programó por chat
};

async function dispatchWorkflow(env, modo) {
  const res = await fetch(
    `https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${GITHUB_WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "bot-escala-players-cron",
      },
      body: JSON.stringify({ ref: "main", inputs: { modo } }),
    }
  );
  if (!res.ok) {
    console.error(`GitHub dispatch error ${res.status}: ${await res.text()}`);
  }
}

async function dispatchUpdate(env, update) {
  const res = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "bot-escala-players-cron",
    },
    body: JSON.stringify({ event_type: "telegram-update", client_payload: { update } }),
  });
  if (!res.ok) {
    console.error(`GitHub repository_dispatch error ${res.status}: ${await res.text()}`);
  }
}

function esRelevante(update) {
  if (update.callback_query) return true;
  const msg = update.message || update.edited_message;
  if (!msg) return false;
  if (msg.chat && msg.chat.type === "private") return true;
  const texto = (msg.text || msg.caption || "").toLowerCase();
  if (texto.includes(`@${BOT_USERNAME}`)) return true;
  const respondido = msg.reply_to_message;
  return !!(respondido && respondido.from && (respondido.from.username || "").toLowerCase() === BOT_USERNAME);
}

// Si Nicolás (u otro Player) manda varios mensajes seguidos muy rápido, cada
// uno dispararía su propia corrida y su propia respuesta de la IA por
// separado, sin que una vea a la otra. Este Durable Object junta los
// mensajes de un mismo chat durante una ventana corta (3s desde el último)
// y recién ahí dispara UNA sola corrida con todo el texto combinado.
const VENTANA_RECOPILACION_MS = 3000;

export class ChatBuffer {
  constructor(state, env) {
    this.state = state;
    this.env = env;
  }

  async fetch(request) {
    const { update } = await request.json();
    const mensajes = (await this.state.storage.get("mensajes")) || [];
    mensajes.push(update);
    await this.state.storage.put("mensajes", mensajes);
    await this.state.storage.setAlarm(Date.now() + VENTANA_RECOPILACION_MS);
    return new Response("ok");
  }

  async alarm() {
    const mensajes = (await this.state.storage.get("mensajes")) || [];
    await this.state.storage.delete("mensajes");
    if (mensajes.length === 0) return;
    await dispatchUpdate(this.env, combinarMensajes(mensajes));
  }
}

function combinarMensajes(updates) {
  const msgs = updates.map((u) => u.message || u.edited_message).filter(Boolean);
  if (msgs.length === 0) return updates[updates.length - 1];
  const ultimo = msgs[msgs.length - 1];
  const textoCombinado = msgs
    .map((m) => m.text || m.caption || "")
    .filter(Boolean)
    .join("\n");
  const combinado = { ...ultimo };
  if (ultimo.caption !== undefined) {
    combinado.caption = textoCombinado;
  } else {
    combinado.text = textoCombinado;
  }
  return { message: combinado };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/telegram-webhook") {
      const secreto = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
      if (!env.WEBHOOK_SECRET || secreto !== env.WEBHOOK_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      const update = await request.json();
      if (esRelevante(update)) {
        if (update.callback_query) {
          // Los clicks de botón (Sí/No) son acciones puntuales, nunca se recopilan.
          ctx.waitUntil(dispatchUpdate(env, update));
        } else {
          const msg = update.message || update.edited_message;
          const id = env.CHAT_BUFFER.idFromName(String(msg.chat.id));
          const stub = env.CHAT_BUFFER.get(id);
          ctx.waitUntil(stub.fetch("https://chat-buffer/add", {
            method: "POST",
            body: JSON.stringify({ update }),
          }));
        }
      }
      return new Response("ok", { status: 200 });
    }
    return new Response("ok", { status: 200 });
  },

  async scheduled(event, env, ctx) {
    const modo = MODO_POR_CRON[event.cron];
    if (modo) ctx.waitUntil(dispatchWorkflow(env, modo));
  },
};
