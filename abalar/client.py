"""AbalarMóbil API client.

Reverse-engineered from abalarMóbil (es.xunta.edu.abalarmobil), the
official Xunta de Galicia app for families. All list endpoints share the
same scheme:

* ``POST https://xadews.edu.xunta.gal/xadews/AbalarMobil/<service>``
* header ``session-id`` (after login) or ``user-id`` (login)
* body: AES-128-CBC-encrypted JSON ``{"<service>": {...}, "language": ...}``
  with key ``SHA1(password + challenge)[:16]``
* response: AES-encrypted JSON ``{"result": {...}}``
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from typing import Any

import requests

from .crypto import decrypt, encrypt, sha1_key

API_SERVER = "https://xadews.edu.xunta.gal"
BASE_ROUTE = "/xadews/AbalarMobil/"
CANAL = "Android"
APP_VERSION = "1.36.1"
DEFAULT_LANGUAGE = "gl"
TIMEOUT = 45

DEFAULT_SESSION_FILE = Path(
    os.environ.get("ABALAR_SESSION_FILE", "~/.config/abalar/session.json")
).expanduser()


class AbalarError(Exception):
    """Error returned by the Abalar API (code + message)."""

    def __init__(self, code: int | str, message: str, url: str | None = None):
        self.code = code
        self.message = message
        self.url = url
        super().__init__(f"[{code}] {message}")


class AbalarClient:
    def __init__(
        self,
        user_id: int | None = None,
        password: str | None = None,
        session_id: str | None = None,
        challenge: str | None = None,
        language: str = DEFAULT_LANGUAGE,
        version: str = APP_VERSION,
        session_file: Path | str | None = "default",
        persoa_id: int | None = None,
        doi: str | None = None,
    ):
        self.user_id = user_id
        self.password = password
        self.session_id = session_id
        self.challenge = challenge
        self.persoa_id = persoa_id
        self.doi = doi
        self.language = language
        self.version = version
        self.session_file = (
            DEFAULT_SESSION_FILE if session_file == "default" else session_file
        )
        self.http = requests.Session()
        self.http.headers["User-Agent"] = f"abalarmobil/{version}"

    # ------------------------------------------------------------------ auth

    @property
    def _list_key(self) -> bytes:
        if not (self.password and self.challenge):
            raise AbalarError("no-session", "Not logged in: run login() first")
        return sha1_key(self.password + self.challenge)

    def login(self, user_id: int | None = None, password: str | None = None) -> dict:
        """Full login: challenge request + encrypted password check."""
        if user_id is not None:
            self.user_id = user_id
        if password is not None:
            self.password = password
        if self.user_id is None or self.password is None:
            raise ValueError("user_id and password are required")

        resp = self._plain_request(
            "login-request",
            {
                "user-id": self.user_id,
                "canal": CANAL,
                "version": self.version,
            },
        )
        self.challenge = resp["result"]["challenge"]

        result = self._encrypted_request(
            "login",
            {},
            headers={"user-id": str(self.user_id)},
            encrypted_response=False,
        )["result"]
        self.session_id = result["session-id"]
        self.persoa_id = result.get("persoa-id")
        self.doi = result.get("doi")
        self.save_session()
        return result

    def logout(self) -> None:
        try:
            self._encrypted_request("logout", {})
        finally:
            self.session_id = None
            self.delete_session()

    @staticmethod
    def load_session(session_file: Path | str | None = "default") -> "AbalarClient":
        """Build a client from a previously saved session."""
        path = _session_path(session_file)
        if not path.exists():
            raise AbalarError("no-session", f"No session file at {path}")
        data = json.loads(path.read_text())
        return AbalarClient(
            user_id=data.get("user_id"),
            password=data.get("password"),
            session_id=data.get("session_id"),
            challenge=data.get("challenge"),
            persoa_id=data.get("persoa_id"),
            doi=data.get("doi"),
            session_file=session_file,
        )

    def save_session(self) -> None:
        if self.session_file is None:
            return
        path = _session_path(self.session_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "user_id": self.user_id,
            "password": self.password,
            "session_id": self.session_id,
            "challenge": self.challenge,
            "persoa_id": self.persoa_id,
            "doi": self.doi,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        path.write_text(json.dumps(payload, indent=2))
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def delete_session(self) -> None:
        if self.session_file:
            path = _session_path(self.session_file)
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------ data

    def children(self) -> list[dict]:
        return self._list("list-children", {}, key_name="children")

    def school(self, cod_centro: int) -> dict:
        return self._list("get-school", {"codCentro": cod_centro})

    def alerts(
        self,
        cod_alumno: int,
        cod_centro: int,
        cod_grupo: int,
        cod_matricula: int,
        page_size: int = 90,
    ) -> dict:
        """Avisos do colexio (notices): title, coment, author, dates."""
        return self._list(
            "list-alerts",
            {
                "codAlumno": cod_alumno,
                "codCentro": cod_centro,
                "codGrupo": cod_grupo,
                "codMatricula": cod_matricula,
                "dt_indice_primeiro": 0,
                "dt_tamano_paxina": page_size,
            },
        )

    def calendar(self, cod_alumno: int, cod_matricula: int) -> list[dict]:
        """Calendario escolar (12 meses) con días lectivos/non lectivos."""
        return self._plain(
            "list-calendar",
            {"codAlumno": cod_alumno, "codMatricula": cod_matricula},
        ).get("records", [])

    def absences(
        self,
        cod_alumno: int,
        cod_grupo: int,
        cod_matricula: int,
        start: str,
        end: str,
        page_size: int = 90,
    ) -> dict:
        """Faltas de asistencia. start/end como 'dd/MM/yyyy'."""
        return self._plain(
            "list-absences",
            {
                "codAlumno": cod_alumno,
                "codGrupo": cod_grupo,
                "codMatricula": cod_matricula,
                "fechaInicio": start,
                "fechaFin": end,
                "dt_indice_primeiro": 0,
                "dt_tamano_paxina": page_size,
                "dtOrde": 1,
                "codEstado": 1,
            },
        )

    def grades(self, cod_matricula: int, cod_avaliacion: int) -> dict:
        return self._list(
            "list-grades",
            {"codMatricula": cod_matricula, "codAvaliacion": cod_avaliacion},
        )

    def issues(self, cod_alumno: int, page_size: int = 90) -> dict:
        return self._list(
            "list-issues",
            {
                "codAlumno": cod_alumno,
                "dt_indice_primeiro": 0,
                "dt_tamano_paxina": page_size,
            },
        )

    def misbehaviors(self, cod_alumno: int, cod_convocatoria: int, page_size: int = 90) -> dict:
        return self._plain(
            "list-misbehaviors",
            {
                "codAlumno": cod_alumno,
                "codConvocatoria": cod_convocatoria,
                "dt_indice_primeiro": 0,
                "dt_tamano_paxina": page_size,
            },
        )

    def tutors(self, cod_alumno: int, cod_matricula: int) -> dict:
        return self._list(
            "list-tutors",
            {"codAlumno": cod_alumno, "codMatricula": cod_matricula},
        )

    def schedule(self, cod_grupo: int, cod_matricula: int) -> list[dict]:
        return self._plain(
            "list-schedule",
            {"codGrupo": cod_grupo, "codMatricula": cod_matricula},
        ).get("records", [])

    def notifications(self, cod_comunication: int = 3) -> dict:
        """cod_comunication: 1=mail, 3=push."""
        return self._list(
            "get-notifications", {"codComunication": cod_comunication}
        )

    def messages(
        self,
        child_index: int = 0,
        limit: int | None = None,
        unread_only: bool = False,
    ) -> list[dict]:
        """Atallo: últimas mensaxes (avisos) do cole, máis recente primeiro.

        ```python
        for m in AbalarClient.load_session().messages():
            print(m["beginDate"], m["title"], m["coment"])
        ```
        """
        children = self.children().get("records", [])
        if not children:
            return []
        child = children[child_index]
        records = self.alerts(
            child["codAlumno"],
            child["codCentro"],
            child["codGrupo"],
            child["codMatricula"],
        ).get("records", [])
        records = sorted(
            records, key=lambda e: int(e.get("beginDate") or 0), reverse=True
        )
        if unread_only:
            records = [a for a in records if not a.get("read")]
        if limit:
            records = records[:limit]
        return records

    def mark_read(self, messages: list[dict]) -> int:
        """Marca como lidos os avisos pasados (os de messages())."""
        n = 0
        for a in messages:
            if not a.get("read") and a.get("codMarkRead"):
                self.set_read(a["codMarkRead"], True)
                n += 1
        return n

    def set_read(self, codigo: int, leido: bool = True) -> dict:
        return self._list("set-read", {"codigo": codigo, "leido": leido})

    # --------------------------------------------------------------- plumbing

    def _url(self, service: str) -> str:
        return f"{API_SERVER}{BASE_ROUTE}{service}"

    def _plain_request(self, service: str, content: dict, headers: dict | None = None) -> dict:
        """Endpoints whose bodies travel as plain JSON (login-request)."""
        body = {"language": self.language, service: content}
        r = self.http.post(
            self._url(service),
            json=body,
            headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})},
            timeout=TIMEOUT,
        )
        return self._parse_response(r, encrypted=False)

    def _encrypted_request(
        self,
        service: str,
        content: dict,
        headers: dict | None = None,
        encrypted_response: bool = True,
    ) -> dict:
        """Send an AES-encrypted body.

        ``login`` sends an encrypted body but answers in plain JSON;
        every other service encrypts both ways.
        """
        body = {"language": self.language, service: content}
        payload = encrypt(json.dumps(body).encode("utf-8"), self._list_key)
        r = self.http.post(
            self._url(service),
            data=payload,
            headers={
                "Content-Type": "application/json-aes; charset=utf-8",
                **(headers or {}),
            },
            timeout=TIMEOUT,
        )
        return self._parse_response(r, encrypted=encrypted_response)

    def _plain(self, service: str, content: dict) -> dict:
        """Newer endpoints: plain JSON body, session-id + Authorization."""
        def _call():
            headers = {"session-id": self.session_id or ""}
            if self.session_id:
                headers["Authorization"] = self.session_id
            body = {"language": self.language, **content}
            r = self.http.post(
                self._url(service),
                json=body,
                headers={"Content-Type": "application/json; charset=utf-8", **headers},
                timeout=TIMEOUT,
            )
            return self._parse_response(r, encrypted=False)

        try:
            return _call()
        except AbalarError as e:
            if e.code in ("crypto", 401, 10005) and self.user_id and self.password:
                self.login(self.user_id, self.password)
                return _call()
            raise

    def _list(self, service: str, content: dict, key_name: str | None = None) -> dict:
        headers = {"session-id": self.session_id or ""}
        if self.session_id:
            headers["Authorization"] = self.session_id
        try:
            result = self._encrypted_request(service, content, headers=headers)
        except AbalarError as e:
            # El challenge/session rotan; si guardamos credenciales, re-login y reintento.
            if e.code in ("crypto", 401) and self.user_id and self.password:
                self.login(self.user_id, self.password)
                headers = {
                    "session-id": self.session_id or "",
                    "Authorization": self.session_id or "",
                }
                result = self._encrypted_request(service, content, headers=headers)
            else:
                raise
        return result.get("result", result)

    def _parse_response(self, r: requests.Response, encrypted: bool) -> dict:
        if r.status_code == 401:
            raise AbalarError(401, "Sesión caducada; vuelve a iniciar sesión")
        if r.status_code == 429:
            try:
                err = r.json()["error"]
                raise AbalarError(err.get("code"), err.get("message", ""))
            except (ValueError, KeyError):
                raise AbalarError(429, r.text[:200])
        raw = r.content
        if encrypted and raw:
            try:
                raw = decrypt(raw, self._list_key)
            except ValueError:
                raise AbalarError("crypto", "No se pudo descifrar la respuesta")
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise AbalarError("bad-json", f"Respuesta no JSON: {raw[:200]!r}")

        if isinstance(data, dict) and "error" in data:
            err = data["error"] or {}
            raise AbalarError(
                err.get("code"), err.get("message", "error"), err.get("url")
            )
        return data


def _session_path(session_file: Path | str | None) -> Path:
    if session_file in (None, "default"):
        return DEFAULT_SESSION_FILE
    return Path(session_file).expanduser()
