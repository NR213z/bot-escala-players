# Bot de recordatorios de coberturas (Players)

Lee el cronograma mensual de coberturas que se publica en el grupo, registra
**solo** las fechas de **Players** y manda recordatorios al grupo para que no
se olviden. No arma grilla de personas (eso lo hace otra persona).

- Recordatorio el día anterior a las 18:00 (ART) y el mismo día a las 10:00 (ART).
- El bot se entera del cronograma en el grupo, pero pregunta por privado a
  Nicolás si lo registra. Nada se guarda sin su confirmación (botones Sí/No).
- Sin IA: el formato del cronograma es fijo, el parseo es con regex (`parser.py`).

## Cómo funciona

1. Un [Cloudflare Worker](worker/) dispara el workflow de GitHub Actions 3
   veces por día (10, 14 y 18 hs ART) llamando a su API — el `schedule` nativo
   de GitHub Actions no es confiable (nunca disparó solo en `bot-autos-caba`),
   así que se deja solo como respaldo.
2. `bot.py poll`: revisa mensajes nuevos de Telegram (`getUpdates`).
   - Si el grupo manda un mensaje con "CRONOGRAMA DE COBERTURAS", lo parsea
     (`parser.py`) y le pregunta a Nicolás por privado si registra las fechas
     de Players que encontró.
   - Si Nicolás contesta por privado (botones o comandos), procesa la
     respuesta.
3. `bot.py remind hoy` / `bot.py remind manana`: compara las fechas
   registradas con la fecha de hoy (zona `America/Argentina/Buenos_Aires`) y
   manda el recordatorio al grupo si corresponde.
4. El estado (`state.json`: offset de Telegram, fechas registradas,
   confirmación pendiente) se commitea solo al final de cada corrida.

## Comandos privados (solo para `OWNER_CHAT_ID`)

- `/fechas` — lista las coberturas de Players registradas.
- `/borrar DD/MM` — saca una fecha puntual.
- `/limpiar` — borra todo (pide confirmación Sí/No antes).

## Setup pendiente

1. **Agregar el bot al grupo de coberturas** (a propósito no se hizo acá).
2. Mandarle `/start` al bot por privado — si no, Telegram no deja que le
   escriba primero.
3. Obtener `GROUP_CHAT_ID` y `OWNER_CHAT_ID`: correr el workflow una vez
   manualmente (Actions → "Bot escala Players" → "Run workflow") después del
   paso 1 y 2, y mirar los logs — el bot loguea cualquier chat_id que todavía
   no esté configurado como secret.
4. Cargar los secrets del repo: `TELEGRAM_TOKEN` (ya configurado),
   `GROUP_CHAT_ID`, `OWNER_CHAT_ID`, `GITHUB_DISPATCH_TOKEN` (Personal Access
   Token con permiso único: Actions de este repo — mismo patrón que
   `bot-autos-caba`).
5. Desplegar el Worker: `cd worker && npx wrangler deploy` (cuenta Cloudflare
   `rnico2080@gmail.com`, igual que los otros bots).

## Correr manualmente

GitHub → Actions → "Bot escala Players" → "Run workflow" (elegir modo:
`poll` / `remind-hoy` / `remind-manana`). O local:

```bash
pip install requests
TELEGRAM_TOKEN=xxx GROUP_CHAT_ID=xxx OWNER_CHAT_ID=xxx python bot.py poll
```

## Test del parser

```bash
python test_parser.py
```

Usa un cronograma de ejemplo (octubre 2026): las primeras 4 líneas de datos
son las reales que trajo el plan original, el resto sigue el mismo formato
para completar las 7 fechas de Players esperadas, porque el plan no incluía
el cronograma completo del mes. Si el parseo falla con un cronograma real,
pegarlo en `test_parser.py` para ajustar el regex.
