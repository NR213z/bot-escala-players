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
  charla con **Cloudflare Workers AI** (`@cf/mistralai/mistral-small-3.1-24b-instruct`,
  free tier de Cloudflare — 10.000 "Neurons" por día, sin tarjeta, la misma
  cuenta donde ya corre el Worker). Si falla o no hay credenciales cargadas,
  el bot simplemente no contesta esa parte — nunca rompe el resto del flujo.
- Por privado podés **enseñarle cosas** con `/enseñar <algo>`: queda guardado
  y se lo incluye como contexto en cada charla de ahí en más (no es
  aprendizaje real del modelo, es una lista de datos que vos le pasás). Ver
  `/memoria` y `/olvidar N` abajo.
- También por privado podés pedirle que **actúe de verdad** en el grupo —
  "mandale un buen día a los players y presentate" o "mañana a las 7 mandá la
  escala" — y te va a pedir confirmación (Sí/No) antes de publicar nada.
  Ver "Pedirle acciones" abajo.

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
3. El mismo Worker dispara `remind-hoy` (10:00 ART), `remind-manana` (18:00
   ART) y `chequear-programados` (cada 15 min) por Cron Trigger propio — esto
   sí es por horario, no por webhook. `bot.py remind hoy|manana` compara las
   fechas registradas con la fecha de hoy (zona
   `America/Argentina/Buenos_Aires`); si hay escala con nombres guardada para
   esa fecha, la agrega al mensaje. `bot.py chequear-programados` manda los
   mensajes que quedaron pendientes de "Pedirle acciones" (abajo) cuando ya
   llegó su hora.
4. El estado (`state.json`: fechas, escalas con nombres, confirmaciones
   pendientes) se commitea solo al final de cada corrida.
5. `bot.py poll` (getUpdates) queda solo como respaldo manual de depuración —
   **no funciona mientras el webhook esté activo** (Telegram no permite las
   dos cosas a la vez).

## Comandos privados (solo para `OWNER_CHAT_ID`)

- `/fechas` — lista las coberturas de Players registradas.
- `/borrar DD/MM` — saca una fecha puntual.
- `/limpiar` — borra todo (pide confirmación Sí/No antes).
- `/enseñar <algo>` — le agrega ese dato a la memoria, para que lo tenga en
  cuenta cuando charla.
- `/memoria` — lista todo lo que le enseñaste, numerado.
- `/olvidar N` — borra la entrada número N de `/memoria`.

## Pedirle acciones (solo por privado)

Además de charlar, el bot puede publicar o programar un mensaje para el
grupo cuando se lo pedís explícitamente por privado — por ejemplo "dale un
buen día a los players y presentate" o "mañana a las 7 mandá la escala".
Internamente: la IA detecta el pedido y arma el mensaje, te lo muestra con
botones Sí/No antes de tocar el grupo (igual que el cronograma y la escala),
y si confirmás:

- **Ahora mismo** → lo publica al toque.
- **Para más adelante** → lo guarda en `state.json` y el Worker lo manda en
  la primera pasada de `chequear-programados` (cada 15 min) después de la
  hora pedida.

No es un agente con herramientas de verdad ni aprendizaje real — es un
prompt que le pide a la IA que, cuando corresponda, agregue una línea
`ACCION: {...}` al final de su respuesta con el mensaje a publicar; el
código la detecta, se la saca de lo que te muestra, y arma la confirmación.
Por eso siempre hay un paso de Sí/No antes de publicar: un error de
interpretación de la IA no llega al grupo sin que lo veas antes.

## Setup

1. **Agregar el bot al grupo de coberturas** (a propósito no se hizo acá) y
   mandarle `/start` por privado.
2. Secrets del repo: `TELEGRAM_TOKEN`, `GROUP_CHAT_ID`, `OWNER_CHAT_ID`,
   `GITHUB_DISPATCH_TOKEN` (PAT de NR213z, permisos Actions: Read and write +
   Contents: Read and write sobre este repo — el `repository_dispatch` pide
   Contents, no alcanza con Actions solo), `CLOUDFLARE_ACCOUNT_ID` y
   `CLOUDFLARE_API_TOKEN` (token con permiso "Workers AI", creado en
   [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens)
   — misma cuenta que el Worker, gratis).
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
