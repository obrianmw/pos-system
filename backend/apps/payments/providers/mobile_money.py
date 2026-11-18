"""Mobile money wallets: Airtel Money (Africa API), M-Pesa (Daraja STK push), MTN MoMo (Collections).

Written against each provider's published sandbox API. Run against the sandbox with real sandbox
credentials before going live; field names occasionally change between API versions.
"""
import base64
import uuid
from datetime import datetime

import requests

from .base import BaseProvider, ProviderError, ProviderResult, local_msisdn


class AirtelMoneyProvider(BaseProvider):
    key = "airtel_money"
    env_prefix = "AIRTEL"

    def _token(self):
        r = requests.post(f"{self.setting('base_url')}/auth/oauth2/token", timeout=self.timeout, json={
            "client_id": self.setting("client_id"), "client_secret": self.setting("client_secret"),
            "grant_type": "client_credentials"})
        r.raise_for_status()
        return r.json()["access_token"]

    def _headers(self, payment):
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json",
                "X-Country": self.setting("country", "MW"), "X-Currency": payment.sale.currency}

    def initiate(self, payment):
        country = self.setting("country", "MW")
        body = {
            "reference": payment.sale.number,
            "subscriber": {"country": country, "currency": payment.sale.currency,
                           "msisdn": local_msisdn(payment.payer_phone, self.setting("dial_code", "265"))},
            "transaction": {"amount": float(payment.amount), "country": country,
                            "currency": payment.sale.currency, "id": str(payment.client_reference)},
        }
        r = requests.post(f"{self.setting('base_url')}/merchant/v1/payments/", json=body,
                          headers=self._headers(payment), timeout=self.timeout)
        data = r.json() if r.content else {}
        if not r.ok or not data.get("status", {}).get("success", False):
            return ProviderResult("failed", message=str(data.get("status", {}).get("message", r.text))[:255], raw=data)
        return ProviderResult("pending", provider_reference=str(payment.client_reference),
                              message="Customer must approve on phone", raw=data)

    def check_status(self, payment):
        r = requests.get(f"{self.setting('base_url')}/standard/v1/payments/{payment.client_reference}",
                         headers=self._headers(payment), timeout=self.timeout)
        data = r.json() if r.content else {}
        txn = (data.get("data") or {}).get("transaction") or {}
        code = txn.get("status")
        status = {"TS": "confirmed", "TF": "failed", "TE": "failed"}.get(code, "pending")
        return ProviderResult(status, provider_reference=txn.get("airtel_money_id", ""), raw=data,
                              message=txn.get("message", ""))

    def reference_from_callback(self, body, headers):
        return (body.get("transaction") or {}).get("id", "")


class MpesaProvider(BaseProvider):
    key = "mpesa"
    env_prefix = "MPESA"

    def _token(self):
        r = requests.get(f"{self.setting('base_url')}/oauth/v1/generate?grant_type=client_credentials",
                         auth=(self.setting("consumer_key"), self.setting("consumer_secret")), timeout=self.timeout)
        r.raise_for_status()
        return r.json()["access_token"]

    def _password(self):
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        raw = f"{self.setting('shortcode')}{self.setting('passkey')}{ts}"
        return base64.b64encode(raw.encode()).decode(), ts

    def initiate(self, payment):
        password, ts = self._password()
        phone = "".join(c for c in payment.payer_phone if c.isdigit())
        body = {
            "BusinessShortCode": self.setting("shortcode"), "Password": password, "Timestamp": ts,
            "TransactionType": "CustomerPayBillOnline", "Amount": int(payment.amount),
            "PartyA": phone, "PartyB": self.setting("shortcode"), "PhoneNumber": phone,
            "CallBackURL": self.callback_url, "AccountReference": payment.sale.number[:12],
            "TransactionDesc": "Shop payment",
        }
        r = requests.post(f"{self.setting('base_url')}/mpesa/stkpush/v1/processrequest", json=body,
                          headers={"Authorization": f"Bearer {self._token()}"}, timeout=self.timeout)
        data = r.json() if r.content else {}
        if not r.ok or data.get("ResponseCode") != "0":
            return ProviderResult("failed", message=data.get("errorMessage", r.text)[:255], raw=data)
        return ProviderResult("pending", provider_reference=data["CheckoutRequestID"],
                              message=data.get("CustomerMessage", ""), raw=data)

    def check_status(self, payment):
        password, ts = self._password()
        r = requests.post(f"{self.setting('base_url')}/mpesa/stkpushquery/v1/query", timeout=self.timeout,
                          headers={"Authorization": f"Bearer {self._token()}"},
                          json={"BusinessShortCode": self.setting("shortcode"), "Password": password,
                                "Timestamp": ts, "CheckoutRequestID": payment.provider_reference})
        data = r.json() if r.content else {}
        if "ResultCode" not in data:  # still processing
            return ProviderResult("pending", payment.provider_reference, data.get("errorMessage", ""), raw=data)
        status = "confirmed" if str(data["ResultCode"]) == "0" else "failed"
        return ProviderResult(status, payment.provider_reference, data.get("ResultDesc", ""), raw=data)

    def reference_from_callback(self, body, headers):
        return ((body.get("Body") or {}).get("stkCallback") or {}).get("CheckoutRequestID", "")


class MtnMomoProvider(BaseProvider):
    key = "mtn_momo"
    env_prefix = "MTN"

    def _token(self):
        r = requests.post(f"{self.setting('base_url')}/collection/token/", timeout=self.timeout,
                          auth=(self.setting("api_user"), self.setting("api_key")),
                          headers={"Ocp-Apim-Subscription-Key": self.setting("subscription_key")})
        r.raise_for_status()
        return r.json()["access_token"]

    def _headers(self):
        return {"Authorization": f"Bearer {self._token()}",
                "Ocp-Apim-Subscription-Key": self.setting("subscription_key"),
                "X-Target-Environment": self.setting("target_env", "sandbox")}

    def initiate(self, payment):
        ref = str(uuid.uuid4())
        headers = {**self._headers(), "X-Reference-Id": ref, "X-Callback-Url": self.callback_url}
        body = {"amount": str(payment.amount), "currency": payment.sale.currency,
                "externalId": str(payment.client_reference),
                "payer": {"partyIdType": "MSISDN", "partyId": "".join(c for c in payment.payer_phone if c.isdigit())},
                "payerMessage": f"Payment {payment.sale.number}", "payeeNote": payment.sale.number}
        r = requests.post(f"{self.setting('base_url')}/collection/v1_0/requesttopay", json=body,
                          headers=headers, timeout=self.timeout)
        if r.status_code != 202:
            return ProviderResult("failed", message=r.text[:255])
        return ProviderResult("pending", provider_reference=ref, message="Customer must approve on phone")

    def check_status(self, payment):
        r = requests.get(f"{self.setting('base_url')}/collection/v1_0/requesttopay/{payment.provider_reference}",
                         headers=self._headers(), timeout=self.timeout)
        data = r.json() if r.content else {}
        status = {"SUCCESSFUL": "confirmed", "FAILED": "failed", "REJECTED": "failed",
                  "TIMEOUT": "failed"}.get(data.get("status"), "pending")
        return ProviderResult(status, payment.provider_reference, data.get("reason", "") or "", raw=data)

    def reference_from_callback(self, body, headers):
        return body.get("externalId", "")


class TnmMpambaProvider(BaseProvider):
    """TNM Mpamba (Malawi). TNM issues its merchant API documentation on application, so this is a
    placeholder: either implement it from those docs, or take Mpamba through the PayChangu provider,
    which aggregates Airtel Money and TNM Mpamba in Malawi."""

    key = "tnm_mpamba"
    env_prefix = "TNM"

    def initiate(self, payment):
        raise ProviderError("TNM Mpamba direct integration is not implemented; use PayChangu or record as manual.")

    def check_status(self, payment):
        raise ProviderError("TNM Mpamba direct integration is not implemented.")
