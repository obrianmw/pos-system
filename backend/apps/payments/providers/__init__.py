from .base import BaseProvider, ProviderError, ProviderNotConfigured, ProviderResult
from .gateways import PayChanguProvider
from .mobile_money import AirtelMoneyProvider, MpesaProvider, MtnMomoProvider, TnmMpambaProvider


class ManualProvider(BaseProvider):
    """Cash, bank transfer, own card terminal, store credit: confirmed when the cashier records it."""

    key = "manual"

    def initiate(self, payment):
        return ProviderResult("confirmed", provider_reference=payment.provider_reference)

    def check_status(self, payment):
        return ProviderResult(payment.status if payment.status != "pending" else "confirmed",
                              payment.provider_reference)


REGISTRY = {p.key: p for p in [ManualProvider, AirtelMoneyProvider, MpesaProvider, MtnMomoProvider,
                               TnmMpambaProvider, PayChanguProvider]}


def get_provider(method) -> BaseProvider:
    try:
        return REGISTRY[method.provider](method)
    except KeyError:
        raise ProviderError(f"Unknown payment provider '{method.provider}'")


__all__ = ["get_provider", "REGISTRY", "ProviderError", "ProviderNotConfigured", "ProviderResult"]
