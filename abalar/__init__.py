"""abalar — cliente Python non oficial para abalarMóbil (Xunta de Galicia)."""

from .client import AbalarClient, AbalarError
from . import register

__all__ = ["AbalarClient", "AbalarError", "register"]
