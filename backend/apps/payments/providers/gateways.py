"""Online card / aggregator gateways."""
import requests

from .base import BaseProvider, ProviderResult


class PayChanguProvider(BaseProvider):
    """PayChangu (Malawi): cards plus Airtel Money and TNM Mpamba through one hosted checkout.

    initiate() returns a checkout URL the POS shows as a QR code or opens on a customer-facing screen.
    """

    key = "paychangu"
    env_prefix = "PAYCHANGU"

    def _headers(self):
        return {"Authorization": f"Bearer {self.setting('secret_key')}", "Accept": "application/json"}

    def initiate(self, payment):
        sale = payment.sale
        body = {
            "amount": str(payment.amount), "currency": sale.currency,
            "tx_ref": str(payment.client_reference),
            "email": (sale.customer.email if sale.customer_id and sale.customer.email else
                      self.setting("default_email", "pos@example.com", required=False)),
            "first_name": sale.customer.name if sale.customer_id else "Walk-in",
            "callback_url": self.callback_url,
            "return_url": self.setting("return_url", self.callback_url, required=False),
            "customization": {"title": sale.branch.organization.name, "description": f"Sale {sale.number}"},
        }
        r = requests.post(f"{self.setting('base_url', 'https://api.paychangu.com')}/payment", json=body,
                          headers=self._headers(), timeout=self.timeout)
        data = r.json() if r.content else {}
        url = ((data.get("data") or {}).get("checkout_url")) or ""
        if not r.ok or not url:
            return ProviderResult("failed", message=str(data.get("message", r.text))[:255], raw=data)
        return ProviderResult("pending", provider_reference=str(payment.client_reference),
                              checkout_url=url, message="Waiting for customer to pay", raw=data)

    def check_status(self, payment):
        r = requests.get(f"{self.setting('base_url', 'https://api.paychangu.com')}/verify-payment/"
                         f"{payment.client_reference}", headers=self._headers(), timeout=self.timeout)
        data = r.json() if r.content else {}
        d = data.get("data") or {}
        st = (d.get("status") or "").lower()
        status = "confirmed" if st == "success" else "failed" if st in ("failed", "cancelled") else "pending"
        # Never confirm a payment for less than we asked for.
        if status == "confirmed" and str(d.get("amount", "")) and float(d["amount"]) < float(payment.amount):
            status, msg = "failed", "Amount paid is less than amount due"
        else:
            msg = d.get("status", "")
        return ProviderResult(status, d.get("reference", payment.provider_reference), msg, raw=data)

    def reference_from_callback(self, body, headers):
        return body.get("tx_ref", "") or (body.get("data") or {}).get("tx_ref", "")
