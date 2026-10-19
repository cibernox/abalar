# Notes for LLM agents

Reading notifications and deciding which ones are calendar events:

```bash
~/src/abalar-mcp/.venv/bin/abalar mensajes --json          # all
~/src/abalar-mcp/.venv/bin/abalar mensajes --unread --json # unread only
```

Each message: `title`, `coment` (full text, Galician/Spanish), `author`,
`beginDate`/`endDate` (epoch UTC seconds), `read`, `codMarkRead` (stable ID).

## What you can decide (and what NOT to trust from the API)

1. **`beginDate`/`endDate` are NOT the event dates** — they are the notice's
   publication window (it can span months). Example: a notice about a party
   on 30 October may have window 09/10 → 30/10. The real date usually has to
   be extracted from `coment`.
2. **Not every notice is an event.** Notices about the virtual classroom or
   pickup procedures are standing information with no date. Only create a
   calendar event if the text mentions concrete date(s).
3. **The text carries the temporal context**: "o domingo 18 de outubro, de
   11:00 a 13:00 h", "do 27 ao 29", "antes do día 20". Use the current date
   to resolve the year. Day without time → all-day event.
4. **Deduplicate by `codMarkRead`**, not by title (notices can be duplicated,
   and long-lived pinned notices reappear on every read). Keep your own
   processed-ID state; the `read` flag is shared with the mobile app, so do
   not use it as sync state.
5. Venue/centre-specific dates (school holidays etc.) will appear in the
   notices themselves — read them, don't hardcode.

## Other commands

```bash
abalar children          # children (codAlumno, codCentro, codGrupo, codMatricula)
abalar events --calendar --ics /tmp/abalar.ics  # notices + non-school days → ICS
abalar absences          # absences
```

Session lives in `~/.config/abalar/session.json` (chmod 600, holds
credentials). If it expires, re-login with your own `user-id`.
