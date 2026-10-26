# Bot de recordatorios de coberturas (Players)

Lee el cronograma mensual de coberturas, registra **solo** las fechas de
**Players**, y manda recordatorios al grupo para que no se olviden. También
puede guardar la "escala con nombres" (quién cubre cada rol, con sus @) de
una fecha puntual y reenviarla junto con el recordatorio, para que les llegue
la notificación a los @mencionados.

- Recordatorio el día anterior a las 18:00 (ART) y el mismo día a las 10:00 (ART).
- El bot reacciona **al instante** (webhook de Telegram), no pollea. En el
  grupo solo reacciona si lo mencionás con `@escala_players_bot` o le
  respondés (reply) a uno de sus mensajes; por privado (solo a
  `OWNER_CHAT_ID`) reacciona siempre.
- Nada se guarda sin confirmación por privado (botones Sí/No).
- Los tres formatos fijos (cronograma, escala con nombres, comandos) se
  parsean con regex, sin IA — determinístico y gratis. Para cualquier otro
  mensaje que le llegue (siempre dentro del mismo gate de @mención/privado),
  charla con **Gemini Flash** (free tier de Google, sin tarjeta). Si Gemini
  falla o no hay `GEMINI_API_KEY` cargada, el bot simplemente no contesta esa
  parte — nunca rompe el resto del flujo.

## Cómo funciona

1. Un [Cloudflare Worker](worker/) recibe el webhook de Telegram (cada
   mensaje nuevo, al instante) y, si es relevante (privado del dueño, o
   mención al bot en el grupo), dispara un `repository_dispatch` de GitHub
   con el update adentro. El `schedule` nativo de GitHub Actions no es
   confiable (nunca disparó solo en `bot-autos-caba`), así que no se usa para
   nada de esto.
2. `bot.py webhook`: procesa ese único update.
   - Si el texto tiene "CRONOGRAMA DE COBERTURAS", lo parsea (`parser.py`) y
     le pregunta al dueño por privado si registra las fechas de Players.
   - Si el texto empieza con `ESCALA ... DD/MM:` (la grilla de nombres con
     @, ej. `ESCALA ALGO MAS 20/10:`), le pregunta si la guarda para mandarla
     junto con el recordatorio de esa fecha.
   - Comandos (`/fechas`, `/borrar`, `/limpiar`) y las respuestas Sí/No a
     los botones, solo por privado.
3. El mismo Worker dispara `remind-hoy` (10:00 ART) y `remind-manana` (18:00
   ART) por Cron Trigger propio — esto sí es por horario, no por webhook.
   `bot.py remind hoy|manana` compara las fechas registradas con la fecha de
   hoy (zona `America/Argentina/Buenos_Aires`); si hay escala con nombres
   guardada para esa fecha, la agrega al mensaje.
4. El estado (`state.json`: fechas, escalas con nombres, confirmaciones
   pendientes) se commitea solo al final de cada corrida.
5. `bot.py poll` (getUpdates) queda solo como respaldo manual de depuración —
   **no funciona mientras el webhook esté activo** (Telegram no permite las
   dos cosas a la vez).

## Comandos privados (solo para `OWNER_CHAT_ID`)

- `/fechas` — lista las coberturas de Players registradas.
- `/borrar DD/MM` — saca una fecha puntual.
- `/limpiar` — borra todo (pide confirmación Sí/No antes).

## Setup

1. **Agregar el bot al grupo de coberturas** (a propósito no se hizo acá) y
   mandarle `/start` por privado.
2. Secrets del repo: `TELEGRAM_TOKEN`, `GROUP_CHAT_ID`, `OWNER_CHAT_ID`,
   `GITHUB_DISPATCH_TOKEN` (PAT de NR213z, permisos Actions: Read and write +
   Contents: Read and write sobre este repo — el `repository_dispatch` pide
   Contents, no alcanza con Actions solo), `GEMINI_API_KEY` (gratis, desde
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey)).
3. Secret del Worker: `GITHUB_DISPATCH_TOKEN` (mismo valor) y
   `WEBHOOK_SECRET` (token random, ver abajo) — `cd worker && npx wrangler
   secret put NOMBRE`.
4. Deploy del Worker: `cd worker && npx wrangler deploy` (cuenta Cloudflare
   `rnico2080@gmail.com`).
5. Registrar el webhook en Telegram (una sola vez, usando el mismo
   `WEBHOOK_SECRET`):
   ```bash
   curl "https://api.telegram.org/bot<TELEGRAM_TOKEN>/setWebhook" \
     -d url=https://bot-escala-players-cron.nicoautoscaba.workers.dev/telegram-webhook \
     -d secret_token=<WEBHOOK_SECRET>
   ```

## Correr manualmente

GitHub → Actions → "Bot escala Players" → "Run workflow" (elegir modo:
`remind-hoy` / `remind-manana` / `poll`, este último solo sirve con el
webhook desactivado). O local:

```bash
pip install requests
TELEGRAM_TOKEN=xxx GROUP_CHAT_ID=xxx OWNER_CHAT_ID=xxx python bot.py remind hoy
```

## Test del parser

```bash
python test_parser.py
```

Usa un cronograma de ejemplo (octubre 2026): las primeras 4 líneas de datos
son las reales que trajo el plan original, el resto sigue el mismo formato
para completar las 7 fechas de Players esperadas, porque el plan no incluía
el cronograma completo del mes. También prueba el parseo de la escala con
nombres contra un ejemplo real. Si algo falla con un mensaje real, pegarlo
acá para ajustar el regex.
