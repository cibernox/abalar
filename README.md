# abalar

Unofficial Python client for **abalarMóbil** (Xunta de Galicia) — the app Galician
schools use to communicate with families. Read school notices, the school
calendar, absences and grades programmatically, and export them to `.ics`
(calendar files with reminders).

> Built by reverse-engineering the Android app (`es.xunta.edu.abalarmobil`).
> Read-only: it never writes anything to the school. Use it for your own
> family's data, responsibly.

## Features

- **Login** with the numeric `user-id` + password (the app's own scheme,
  including its AES-128-CBC challenge/response protocol)
- **Notices (mensaxes)** — the main use case: title, full text, author,
  publication dates, read/unread, stable IDs
- **School calendar** — school days / non-school days for the academic year
- **Absences** (faltas de asistencia), **grades**, **misbehaviours**, **tutors**
- **Weekly schedule** (horario)
- **Session persistence** with automatic re-login when the server rotates the
  challenge — safe for unattended cron jobs
- **SMS registration/recovery flow** to obtain your `user-id`
- **ICS export** with configurable alarms (e.g. 24 h and 1 h before each event)

## Installation

```bash
pip install -e .   # from a clone of this repo
```

Requires Python 3.10+. Dependencies: `requests`, `cryptography`.

## First-time setup

The API identifies you by a **numeric `user-id`** (not an email), assigned when
your phone number is registered. If you don't know it, the SMS flow recovers it
(the same flow the app uses for "forgot password"):

```bash
abalar register --phone +346XXXXXXXX   # an SMS code arrives
# enter the code when prompted → prints your user-id
```

If the phone is already registered, the existing password keeps working.

Then log in once:

```bash
abalar login --user-id 123456789 --password '...'
```

The session (including the password, needed to decrypt responses) is stored in
`~/.config/abalar/session.json` with `600` permissions. Override the location
with `--session <path>` or `ABALAR_SESSION_FILE`.

## CLI

```bash
abalar                     # = `abalar mensajes`: latest school notices
abalar mensajes -n 3       # only the last 3
abalar mensajes --unread   # only unread ones (marked ●)
abalar mensajes --mark-read
abalar mensajes --json     # JSON output, for scripts/agents
abalar children            # list children and their internal codes
abalar events --calendar --ics abalar.ics   # notices + non-school days → ICS
abalar alerts              # alias of mensajes
abalar absences            # last 90 days
abalar register --phone ...  # SMS registration / user-id recovery
```

## Python API

```python
from abalar import AbalarClient

c = AbalarClient.load_session()          # from the saved session file
# or: c = AbalarClient(); c.login(user_id=..., password=...)
```

### Reading notices (the main use case)

```python
c.messages()                    # all notices, newest first
c.messages(limit=3)             # last 3
c.messages(unread_only=True)    # only unread
c.messages(child_index=1)       # pick a child if you have several

for m in c.messages():
    print(m["title"], m["coment"], m["author"], m["beginDate"], m["read"])

c.mark_read(c.messages(unread_only=True))   # mark as read server-side
```

Each notice is a dict: `title`, `coment` (full text, Galician/Spanish),
`author`, `beginDate` / `endDate` (epoch seconds — **publication window**, not
necessarily the event date), `read`, `codMarkRead` (stable ID), `type`.

### Other reads

```python
children = c.children()                       # list[dict]
child = children[0]
# every child carries the codes the other endpoints need:
# codAlumno, codCentro, codGrupo, codMatricula, evaluacionActiva, ...

c.alerts(child["codAlumno"], child["codCentro"],
         child["codGrupo"], child["codMatricula"])     # raw notices payload

c.calendar(child["codAlumno"], child["codMatricula"])
# 12 months: diasNonLectivos / diasNonLectivosCentro / diasLectivosCentro

c.absences(child["codAlumno"], child["codGrupo"], child["codMatricula"],
           "01/09/2026", "19/12/2026")         # dates as dd/MM/yyyy

c.grades(child["codMatricula"], child["evaluacionActiva"])
c.misbehaviors(child["codAlumno"], child["evaluacionActiva"])
c.tutors(child["codAlumno"], child["codMatricula"])
c.schedule(child["codGrupo"], child["codMatricula"])
c.school(child["codCentro"])
c.notifications()          # notification preferences (mail/push)
c.set_read(codigo, True)   # mark one item as read
```

All methods return plain `dict` / `list[dict]` with the API's own field names
(Spanish/Galician: `nome`, `fechaInicio`, `diasNonLectivos`, …).

### ICS export

```python
from abalar.cli import build_ics

ics = build_ics(
    avisos=c.messages(),                        # timed events with alarms
    non_lectivos=[d for m in c.calendar(child["codAlumno"],
                  child["codMatricula"]) for d in m["diasNonLectivos"]],
    reminders_minutes=(1440, 60),               # 24 h and 1 h before
)
open("abalar.ics", "w").write(ics)
```

### Low-level

```python
c._list("list-children", {})        # AES-encrypted style endpoint
c._plain("list-calendar", {"codAlumno": ..., "codMatricula": ...})
```

### Errors

Anything the server rejects raises `abalar.AbalarError` with `.code` and
`.message`. Stale sessions raise code `"crypto"` or `401` — when credentials
are loaded, the client re-logs-in automatically and retries once.

## For LLM agents

See [AGENT-NOTES.md](AGENT-NOTES.md) for guidance on turning notices into
calendar events (the notice dates are publication windows; real event dates
must be extracted from the text).

## Protocol notes

Server: `https://xadews.edu.xunta.gal/xadews/AbalarMobil/`. Two endpoint
families coexist:

1. **Encrypted (legacy Volley layer)** — `login`, `list-children`, `list-alerts`,
   `list-grades`, `list-tutors`, `get-notifications`, `set-read`, `logout`:
   body is AES-128-CBC (zero IV, PKCS7) of `{"<service>": {...}, "language": ...}`
   with key `SHA1(password + challenge)[:16]`; header `user-id` (login) or
   `session-id` (+ `Authorization`) otherwise. Responses are encrypted the same
   way — except `login`, which answers plain JSON.
2. **Plain (Retrofit/ktx layer)** — `list-calendar`, `list-absences`,
   `list-schedule`, `list-misbehaviors`, `get-school`,
   `ultimo-acceso-servizo`: plain JSON body with `session-id` + `Authorization`
   headers; plain JSON responses.

`login-request` (plain JSON) returns the `challenge`. `list-events` and
`list-subjects` no longer exist server-side.

## Disclaimer

This project is not affiliated with, endorsed by, or connected to the Xunta de
Galicia in any way. It accesses only the data of the account you log in with,
through the same endpoints the official app uses. If you break something, it's
yours: keep the pace gentle (a few requests per sync run is plenty).
