"""Phone registration flow.

abalarMóbil identifies families by a numeric ``user-id`` assigned when
the phone number is registered. Re-running registration on a new device
returns the same user-id, so this flow also works to recover credentials:

1. ``request_code(phone)``   -> server sends an SMS code
2. ``confirm_code(phone, sms_code)`` -> returns user-id, challenge and
   (for new registrations) an init-password
3. ``set_password(...)``     -> sets the password (new registrations)
"""

from __future__ import annotations

import json

import requests

from .client import API_SERVER, BASE_ROUTE, CANAL, TIMEOUT, AbalarClient, AbalarError
from .crypto import register_token, xor_sha1_key

APP_VERSION = "1.36.1"


def request_code(phone: str, language: str = "gl") -> None:
    """Ask the server to send an SMS verification code to ``phone``."""
    body = {
        "language": language,
        "register": {
            "phone": phone,
            "canal": CANAL,
            "version": APP_VERSION,
            "model": "python-abalar",
        },
    }
    r = requests.post(
        f"{API_SERVER}{BASE_ROUTE}register",
        json=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=TIMEOUT,
    )
    data = r.json()
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        raise AbalarError(err.get("code"), err.get("message"), err.get("url"))


def confirm_code(phone: str, sms_code: str, language: str = "gl") -> dict:
    """Exchange the SMS code for user-id / challenge / init-password.

    The request is plain JSON; the response is AES-encrypted with
    SHA1(phone XOR sms_code)[:16].
    """
    key = xor_sha1_key(phone, sms_code)
    body = {
        "language": language,
        "register-continue": {
            "phone": phone,
            "token": register_token(phone, sms_code),
        },
    }
    r = requests.post(
        f"{API_SERVER}{BASE_ROUTE}register-continue",
        json=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=TIMEOUT,
    )
    if r.status_code == 400:
        raise AbalarError("sms", "Código SMS incorrecto ou caducado")
    from .crypto import decrypt

    data = json.loads(decrypt(r.content, key).decode("utf-8"))
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        raise AbalarError(err.get("code"), err.get("message"), err.get("url"))
    return data["result"]


def set_password(
    user_id: int,
    init_password: str,
    password: str,
    challenge: str,
    language: str = "gl",
) -> dict:
    """Complete registration by setting the definitive password."""
    key = __import__("hashlib").sha1((init_password + challenge).encode()).digest()[:16]
    body = {
        "language": language,
        "register-complete": {
            "init-password": init_password,
            "password": password,
            "user-id": user_id,
        },
    }
    from .crypto import encrypt

    r = requests.post(
        f"{API_SERVER}{BASE_ROUTE}register-complete",
        data=encrypt(json.dumps(body).encode("utf-8"), key),
        headers={
            "Content-Type": "application/json-aes; charset=utf-8",
            "user-id": str(user_id),
        },
        timeout=TIMEOUT,
    )
    data = r.json()
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        raise AbalarError(err.get("code"), err.get("message"), err.get("url"))
    return data["result"]


def interactive_register(phone: str, password: str | None = None) -> AbalarClient:
    """End-to-end registration helper: asks for the SMS code on stdin."""
    print(f"Solicitando código SMS para {phone}...")
    request_code(phone)
    sms = input("Código SMS: ").strip()
    result = confirm_code(phone, sms)
    user_id = result["user-id"]
    challenge = result["challenge"]
    init_pass = result.get("init-password")
    print(f"user-id: {user_id}")
    if init_pass:
        password = password or input("Nova contrasinal: ").strip()
        res = set_password(user_id, init_pass, password, challenge)
        challenge = res.get("challenge", challenge)
    else:
        # Phone already registered; the existing password still works.
        password = password or input("Contrasinal existente: ").strip()
    client = AbalarClient(user_id=user_id, password=password)
    client.login()
    return client
