"""CLI: `abalar login|children|events|alerts|absences|calendar|register`.

Calendar export writes an .ics with 1-day and 1-hour alarms for events.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import sys
from pathlib import Path

from .client import AbalarClient, AbalarError
from .crypto import decrypt, encrypt, sha1_key  # noqa: F401  (re-export)
from .register import interactive_register


def _fmt_ts(epoch) -> str | None:
    if epoch is None:
        return None
    return dt.datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M")


def _ical_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _vevent(uid, dtstart, dtend, summary, description, alarms):
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        dtstart,
        dtend,
        f"SUMMARY:{_ical_escape(summary)}",
        f"DESCRIPTION:{_ical_escape(description)}",
    ]
    for mins in alarms:
        lines += [
            "BEGIN:VALARM",
            f"TRIGGER:-PT{mins}M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_ical_escape(summary)}",
            "END:VALARM",
        ]
    lines.append("END:VEVENT")
    return lines


def build_ics(avisos: list[dict] | None = None, non_lectivos: list[dict] | None = None,
              reminders_minutes=(1440, 60)) -> str:
    """Avisos (con beginDate/endDate) + días non lectivos (all-day)."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//abalar-cli//ES",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:Abalar",
    ]
    for i, ev in enumerate(avisos or []):
        start = int(ev.get("beginDate") or 0)
        end = int(ev.get("endDate") or start)
        if not start:
            continue
        ds = dt.datetime.fromtimestamp(start)
        de = dt.datetime.fromtimestamp(end)
        all_day = ds.hour == 0 and de.hour == 0
        if all_day:
            dtstart = f"DTSTART;VALUE=DATE:{ds.strftime('%Y%m%d')}"
            dtend = f"DTEND;VALUE=DATE:{(de + dt.timedelta(days=1)).strftime('%Y%m%d')}"
        else:
            dtstart = ds.strftime("DTSTART:%Y%m%dT%H%M%S")
            dtend = de.strftime("DTEND:%Y%m%dT%H%M%S")
        title = ev.get("title") or ev.get("tipoAviso") or "Aviso"
        desc = ev.get("coment") or ev.get("aviso") or ""
        if ev.get("observaciones"):
            desc += "\n" + ev["observaciones"]
        uid = f"abalar-{ev.get('codMarkRead', i)}-{start}@abalar.local"
        lines += _vevent(uid, dtstart, dtend, title, desc, reminders_minutes)
    for j, d in enumerate(non_lectivos or []):
        fecha = d.get("fecha")
        if not fecha:
            continue
        day, month, year = fecha.split("/")
        dtstart = f"DTSTART;VALUE=DATE:{year}{month}{day}"
        dtend = f"DTEND;VALUE=DATE:{(dt.date(int(year), int(month), int(day)) + dt.timedelta(days=1)).strftime('%Y%m%d')}"
        title = f"Non lectivo — {d.get('descDia', '').strip().title()}"
        uid = f"abalar-nonlectivo-{year}{month}{day}-{j}@abalar.local"
        lines += _vevent(uid, dtstart, dtend, title, "", reminders_minutes)
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def events_to_ics(events: list[dict], reminders_minutes=(1440, 60)) -> str:
    """Legacy helper for old-style list-events payloads."""
    avisos = [
        {
            "title": ev.get("tipoAviso"),
            "coment": ev.get("aviso"),
            "beginDate": ev.get("inicio"),
            "endDate": ev.get("fin"),
            "observaciones": ev.get("observaciones"),
            "codMarkRead": ev.get("codAvisoLectura"),
        }
        for ev in events
    ]
    return build_ics(avisos=avisos, reminders_minutes=reminders_minutes)


def _client(args) -> AbalarClient:
    try:
        return AbalarClient.load_session(args.session)
    except AbalarError:
        print("Non hai sesión gardada. Executa primeiro: abalar login", file=sys.stderr)
        sys.exit(2)


def cmd_login(args) -> None:
    user_id = args.user_id or int(input("user-id numérico: ").strip())
    password = args.password or getpass.getpass("Contrasinal: ")
    client = AbalarClient()
    client.login(user_id=user_id, password=password)
    print(f"Sesión iniciada (user-id {user_id}, session {client.session_id[:8]}…)")
    print(f"Sesión gardada en {client.session_file}")


def cmd_children(args) -> None:
    client = _client(args)
    children = client.children()
    for i, ch in enumerate(children.get("records", [])):
        print(
            f"[{i}] {ch.get('nome')} {ch.get('apelido1', '')} — "
            f"{ch.get('nomeCentro')} / {ch.get('nomeCurso')} / {ch.get('nomeGrupo')} "
            f"(codAlumno={ch.get('codAlumno')}, codCentro={ch.get('codCentro')}, "
            f"codGrupo={ch.get('codGrupo')}, codMatricula={ch.get('codMatricula')}, "
            f"evaluacionActiva={ch.get('evaluacionActiva')})"
        )


def cmd_events(args) -> None:
    client = _client(args)
    child = _pick_child(client, args.child)
    alerts = client.alerts(
        child["codAlumno"], child["codCentro"], child["codGrupo"], child["codMatricula"]
    )
    avisos = alerts.get("records", [])
    print(f"{len(avisos)} avisos ({alerts.get('unread_alerts', '?')} sen ler)\n")
    for ev in sorted(avisos, key=lambda e: int(e.get("beginDate") or 0)):
        print(f"• {_fmt_ts(ev.get('beginDate'))} → {_fmt_ts(ev.get('endDate'))} — {ev.get('title')}")
        if ev.get("coment"):
            print(f"  {str(ev.get('coment'))[:120]}")
        print()
    non_lectivos = []
    if args.calendar:
        months = client.calendar(child["codAlumno"], child["codMatricula"])
        for m in months:
            non_lectivos.extend(m.get("diasNonLectivos", []))
        print(f"(calendario escolar: {len(non_lectivos)} días non lectivos)")
    if args.ics:
        Path(args.ics).write_text(build_ics(avisos=avisos, non_lectivos=non_lectivos))
        print(f"ICS escrito en {args.ics}")


def cmd_alerts(args) -> None:
    client = _client(args)
    child = _pick_child(client, args.child)
    data = client.alerts(
        child["codAlumno"],
        child["codCentro"],
        child["codGrupo"],
        child["codMatricula"],
    )
    for a in data.get("records", []):
        mark = "•" if not a.get("read") else " "
        print(f"{mark} {_fmt_ts(a.get('beginDate'))} [{a.get('type')}] {a.get('title')}")
        if a.get("coment"):
            print(f"  {str(a.get('coment'))[:120]}")
        print()


def cmd_absences(args) -> None:
    client = _client(args)
    child = _pick_child(client, args.child)
    end = dt.date.today()
    start = end - dt.timedelta(days=90)
    data = client.absences(
        child["codAlumno"], child["codGrupo"], child["codMatricula"],
        start.strftime("%d/%m/%Y"), end.strftime("%d/%m/%Y"),
    )
    for a in data.get("records", []):
        print(f"• {a.get('fecha') or a.get('data')} — {a.get('materia') or a.get('nomeMateria')}: {a.get('tipoFalta') or a.get('tipo')}")


def cmd_register(args) -> None:
    client = interactive_register(args.phone)
    print("Rexistro/login completado.")


def _pick_child(client: AbalarClient, index: int | None) -> dict:
    children = client.children().get("records", [])
    if not children:
        print("Non se atoparon fillos na conta.", file=sys.stderr)
        sys.exit(1)
    if index is None:
        if len(children) > 1:
            for i, ch in enumerate(children):
                print(f"[{i}] {ch.get('nome')} {ch.get('apelido1', '')}")
            idx = int(input("Fillo/a [nº]: ").strip())
            return children[idx]
        return children[0]
    return children[index]


def _latest_messages(client: AbalarClient, child: dict, limit: int | None = None,
                     unread_only: bool = False) -> list[dict]:
    """Últimos avisos do cole, do máis recente ao máis vello.

    2026-10: o endpoint devolve un formato novo (titularAviso/descricionAviso,
    datas 'dd/MM/yyyy', leido, codAvisoLectura); normalízao ao formato antigo
    (title/coment/author/beginDate/read/codMarkRead) para non romper consumidores.
    """
    alerts = client.alerts(
        child["codAlumno"],
        child["codCentro"],
        child["codGrupo"],
        child["codMatricula"],
    )
    records = alerts.get("records", [])

    def _norm(a: dict) -> dict:
        if "titularAviso" in a:
            def _ts(s: str) -> int:
                try:
                    d, mth, y = s.split("/")
                    return int(dt.datetime(int(y), int(mth), int(d), tzinfo=dt.timezone.utc).timestamp())
                except (ValueError, AttributeError, TypeError):
                    return 0
            pub = a.get("dataPublicacion") or a.get("dataInicioValidez") or ""
            return {
                "codigo": a.get("codigo"),
                "title": a.get("titularAviso"),
                "coment": a.get("descricionAviso"),
                "author": a.get("autor"),
                "type": (a.get("tipoAviso") or {}).get("descricion"),
                "beginDate": _ts(pub),
                "endDate": _ts(a.get("dataFinValidez") or ""),
                "read": bool(a.get("leido")),
                "codMarkRead": a.get("codAvisoLectura"),
            }
        return a

    records = [_norm(a) for a in records]
    records = sorted(
        records,
        key=lambda e: int(e.get("beginDate") or 0),
        reverse=True,
    )
    if unread_only:
        records = [a for a in records if not a.get("read")]
    if limit:
        records = records[:limit]
    return records


def cmd_messages(args) -> None:
    """A tarefa máis común: ler as mensaxes (avisos) do cole."""
    client = _client(args)
    child = _pick_child(client, args.child)
    messages = _latest_messages(
        client, child, limit=args.n, unread_only=args.unread
    )

    if args.json:
        import json as _json

        print(_json.dumps(messages, ensure_ascii=False, indent=2))
        return

    if not messages:
        print("Non hai mensaxes.")
        return

    shown = f"últimos {len(messages)}" if args.n else f"{len(messages)}"
    scope = "sen ler" if args.unread else "total"
    print(
        f"Mensaxes de {child.get('nome')} ({child.get('nomeCentro')}) — "
        f"{shown} {scope}\n"
    )
    for a in messages:
        mark = "● NO LEÍDO" if not a.get("read") else "○"
        ini = dt.datetime.fromtimestamp(int(a.get("beginDate") or 0))
        fin = dt.datetime.fromtimestamp(int(a.get("endDate") or 0))
        print(f"{mark}  {ini:%d/%m/%Y} → {fin:%d/%m/%Y}  [{a.get('type')}]")
        print(f"   {a.get('title')}")
        print(f"   Autor/a: {a.get('author')}")
        print("   " + (a.get("coment") or "").strip().replace("\n", "\n   "))
        links = a.get("links") or []
        for link in links if isinstance(links, list) else []:
            if isinstance(link, str):
                print(f"   → {link}")
        print("-" * 72)

    if args.mark_read:
        pending = [a for a in messages if not a.get("read") and a.get("codMarkRead")]
        for a in pending:
            client.set_read(a["codMarkRead"], True)
        print(f"(marcados {len(pending)} mensaxes como lidos)")


def main() -> None:
    # `abalar` ou `abalar -n 3` sen subcomando → mensajes (a tarefa máis común)
    if len(sys.argv) == 1 or (len(sys.argv) > 1 and sys.argv[1].startswith("-")):
        sys.argv.insert(1, "mensajes")
    parser = argparse.ArgumentParser(prog="abalar", description="Cliente abalarMóbil")
    parser.add_argument("--session", help="Ruta do ficheiro de sesión", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Iniciar sesión")
    p_login.add_argument("--user-id", type=int)
    p_login.add_argument("--password")
    p_login.set_defaults(func=cmd_login)

    p_children = sub.add_parser("children", help="Listar fillos")
    p_children.set_defaults(func=cmd_children)

    p_events = sub.add_parser("events", help="Avisos do colexio (opcionalmente + calendario)")
    p_events.add_argument("--child", type=int)
    p_events.add_argument("--ics", help="Exportar a .ics")
    p_events.add_argument("--calendar", action="store_true", help="Incluír días non lectivos")
    p_events.set_defaults(func=cmd_events)

    p_messages = sub.add_parser(
        "mensajes", help="Ler as mensaxes (avisos) do cole — comando principal"
    )
    p_messages.add_argument("--child", type=int, help="Índice do fillo/a se hai máis dun")
    p_messages.add_argument("-n", type=int, help="Só os N últimos")
    p_messages.add_argument("--unread", action="store_true", help="Só os non lidos")
    p_messages.add_argument("--mark-read", action="store_true", help="Marcalos como lidos ao final")
    p_messages.add_argument("--json", action="store_true", help="Saída JSON para automatización")
    p_messages.set_defaults(func=cmd_messages)

    p_alerts = sub.add_parser("alerts", help="(alias de mensajes)")
    p_alerts.add_argument("--child", type=int)
    p_alerts.set_defaults(func=cmd_messages)

    p_abs = sub.add_parser("absences", help="Faltas de asistencia (últimos 90 días)")
    p_abs.add_argument("--child", type=int)
    p_abs.set_defaults(func=cmd_absences)

    p_reg = sub.add_parser("register", help="Rexistrar/recuperar conta por SMS")
    p_reg.add_argument("--phone", required=True)
    p_reg.set_defaults(func=cmd_register)

    args = parser.parse_args()
    args.session = args.session or "default"
    try:
        args.func(args)
    except AbalarError as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
