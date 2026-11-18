import os
from dataclasses import dataclass, field

from django.conf import settings


class ProviderError(Exception):
    pass


class ProviderNotConfigured(ProviderError):
    pass


@dataclass
class ProviderResult:
    status: str  # "confirmed" | "pending" | "failed"
    provider_reference: str = ""
    message: str = ""
    checkout_url: str = ""
    raw: dict = field(default_factory=dict)


class BaseProvider:
    """Interface every payment integration implements.

    The flow for electronic payments:
      1. initiate()      -> usually "pending" (customer approves on their phone / checkout page)
      2. provider calls  /api/payments/callback/<key>/ ; we never trust the body, we call check_status()
      3. check_status()  -> "confirmed" finalizes the sale
    """

    key = "base"
    env_prefix = ""
    timeout = 30

    def __init__(self, method):
        self.method = method

    def setting(self, name, default=None, required=True):
        """Branch/organization config first, then environment variable PREFIX_NAME."""
        value = self.method.config.get(name.lower()) if self.method else None
        if value in (None, ""):
            value = os.environ.get(f"{self.env_prefix}_{name.upper()}", default)
        if required and value in (None, ""):
            raise ProviderNotConfigured(f"{self.key}: missing setting {self.env_prefix}_{name.upper()}")
        return value

    @property
    def callback_url(self):
        return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/payments/callback/{self.key}/"

    def initiate(self, payment) -> ProviderResult:
        raise NotImplementedError

    def check_status(self, payment) -> ProviderResult:
        raise NotImplementedError

    def reference_from_callback(self, body: dict, headers: dict) -> str:
        """Return the value stored in Payment.provider_reference or Payment.client_reference."""
        raise NotImplementedError


def local_msisdn(phone: str, country_code: str) -> str:
    """'+265 99 123 4567' / '0991234567' -> '991234567' (number without country code)."""
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith(country_code):
        digits = digits[len(country_code):]
    return digits.lstrip("0")
