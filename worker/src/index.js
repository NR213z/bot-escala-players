// El schedule nativo de GitHub Actions no es confiable (nunca disparó solo en
// bot-autos-caba). El cron real vive acá: un Cron Trigger de Cloudflare dispara
// el workflow de GitHub por su API, 3 veces por día (10, 14 y 18 hs ART).

const GITHUB_REPO = "NR213z/bot-escala-players";
const GITHUB_WORKFLOW = "bot.yml";

const MODO_POR_CRON = {
  "0 13 * * *": "remind-hoy", // 10:00 ART
  "0 17 * * *": "poll", // 14:00 ART
  "0 21 * * *": "remind-manana", // 18:00 ART
};

async function dispatchGitHubWorkflow(env, modo) {
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

export default {
  async fetch() {
    return new Response("ok", { status: 200 });
  },

  async scheduled(event, env, ctx) {
    const modo = MODO_POR_CRON[event.cron] || "poll";
    ctx.waitUntil(dispatchGitHubWorkflow(env, modo));
  },
};
