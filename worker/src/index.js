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
        // No esperamos la respuesta de GitHub para no demorar el 200 a Telegram.
        ctx.waitUntil(dispatchUpdate(env, update));
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
