"""Wrapper around the Transbank Webpay Plus SDK.

Sandbox mode uses Transbank's public test commerce code + API key — safe to
commit. Production credentials must come from .env.

NOTE about TLS: este entorno tiene una cadena de CA root corrupta a nivel de
sistema (mismo síntoma con git y pip). Para que `requests` (que es lo que
usa el SDK por dentro) funcione contra el sandbox de Transbank, se parchea
`requests.Session.request` para saltar la verificación TLS. **Esto solo
aplica a integración / sandbox**. Para producción quita el parche o,
mejor, configura el OS para que confíe en la cadena de Transbank.
"""
import os

import certifi
import requests
import urllib3

# Asegura que `requests` use el bundle de certifi (cubre la mayoría de los
# ambientes con cert chain rota).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

# Si el setdefault no fuera suficiente (corp MITM, AV, etc.), saltamos verify.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_original_request = requests.Session.request


def _request_skip_verify(self, method, url, **kwargs):
    if "transbank" in str(url) or "webpay" in str(url):
        kwargs["verify"] = False
    return _original_request(self, method, url, **kwargs)


requests.Session.request = _request_skip_verify  # type: ignore[assignment]


from transbank.common.integration_api_keys import IntegrationApiKeys  # noqa: E402
from transbank.common.integration_commerce_codes import IntegrationCommerceCodes  # noqa: E402
from transbank.common.integration_type import IntegrationType  # noqa: E402
from transbank.common.options import WebpayOptions  # noqa: E402
from transbank.webpay.webpay_plus.transaction import Transaction  # noqa: E402


def _get_transaction() -> Transaction:
    options = WebpayOptions(
        IntegrationCommerceCodes.WEBPAY_PLUS,
        IntegrationApiKeys.WEBPAY,
        IntegrationType.TEST,
    )
    return Transaction(options)


def create_transaction(buy_order: str, session_id: str, amount: int, return_url: str) -> dict:
    """Returns {'token': str, 'url': str} — frontend POSTs to url with token_ws."""
    tx = _get_transaction()
    return tx.create(buy_order, session_id, amount, return_url)


def commit_transaction(token: str) -> dict:
    """Confirms the transaction with Transbank. response_code == 0 → success."""
    tx = _get_transaction()
    response = tx.commit(token)
    return response if isinstance(response, dict) else response.__dict__
