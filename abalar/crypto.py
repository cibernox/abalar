"""Primitives replicating abalarMóbil's client-side crypto.

The app (com.everis.abalarmobile) derives AES keys as
``SHA1(secret)[:16]`` and encrypts request/response bodies with
AES-128-CBC, PKCS5/PKCS7 padding and a zero IV (``util/AES128.java``).
"""

from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

ZERO_IV = b"\x00" * 16


def sha1_key(secret: str) -> bytes:
    """Key derivation used for login and every list service.

    ``key = SHA1(secret.encode())[:16]`` where secret is normally
    ``password + challenge``.
    """
    return hashlib.sha1(secret.encode("utf-8")).digest()[:16]


def xor_sha1_key(phone: str, sms_code: str) -> bytes:
    """Key for ``register-continue``: SHA1(phone XOR repeated sms_code)[:16]."""
    phone_b = phone.encode("utf-8")
    sms_b = sms_code.encode("utf-8")
    xored = bytes(b ^ sms_b[i % len(sms_b)] for i, b in enumerate(phone_b))
    return hashlib.sha1(xored).digest()[:16]


def register_token(phone: str, sms_code: str) -> str:
    """Token for ``register-continue``: full hex of SHA1(phone + sms_code)."""
    return hashlib.sha1((phone + sms_code).encode("utf-8")).hexdigest()


def encrypt(data: bytes, key: bytes) -> bytes:
    """AES-128-CBC encrypt with zero IV and PKCS7 padding."""
    padder = PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(ZERO_IV))
    enc = cipher.encryptor()
    return enc.update(padded) + enc.finalize()


def decrypt(data: bytes, key: bytes) -> bytes:
    """AES-128-CBC decrypt with zero IV; raises ValueError on bad padding."""
    cipher = Cipher(algorithms.AES(key), modes.CBC(ZERO_IV))
    dec = cipher.decryptor()
    padded = dec.update(data) + dec.finalize()
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()
