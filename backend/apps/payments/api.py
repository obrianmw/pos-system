import logging

from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.api import OrgScopedViewSet

from .models import Payment, PaymentCallbackLog, PaymentMethod
from .providers import REGISTRY

log = logging.getLogger(__name__)


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        exclude = ["organization"]

    def validate_provider(self, value):
        if value not in REGISTRY:
            raise serializers.ValidationError(f"Choose one of {sorted(REGISTRY)}")
        return value

    def validate_config(self, value):
        bad = [k for k in value if any(s in k.lower() for s in ("secret", "password", "key", "token"))]
        if bad:
            raise serializers.ValidationError(f"Keep secrets in environment variables, not config: {bad}")
        return value


class PaymentMethodViewSet(OrgScopedViewSet):
    queryset = PaymentMethod.objects.prefetch_related("branches")
    serializer_class = PaymentMethodSerializer
    write_perm = "payments.configure"


@api_view(["POST", "GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def provider_callback(request, provider):
    """Webhook from a wallet/gateway. The body is only used to find which payment it is about;
    the real status always comes from asking the provider (check_status), so a forged callback
    cannot mark a sale as paid."""
    from apps.sales.services import refresh_payment

    body = request.data if isinstance(request.data, dict) else {}
    if request.method == "GET":
        body = {**request.query_params.dict(), **body}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("authorization", "cookie")}
    entry = PaymentCallbackLog.objects.create(provider=provider, body=body, headers=headers)
    cls = REGISTRY.get(provider)
    if not cls:
        entry.error = "unknown provider"
        entry.save(update_fields=["error"])
        return Response({"ok": False}, status=404)
    try:
        ref = cls(None).reference_from_callback(body, headers)
        payment = (Payment.objects.filter(provider_reference=ref).first() or
                   Payment.objects.filter(client_reference=ref).first()) if ref else None
        if not payment:
            entry.error = f"no payment for reference {ref!r}"
        else:
            entry.payment = payment
            refresh_payment(payment)
            entry.processed = True
    except Exception as e:  # always 200 so the provider stops retrying; the log keeps the error
        log.exception("payment callback failed")
        entry.error = str(e)[:255]
    entry.save()
    # M-Pesa expects this exact acknowledgement shape; others ignore it.
    return Response({"ResultCode": 0, "ResultDesc": "Accepted", "ok": True})
