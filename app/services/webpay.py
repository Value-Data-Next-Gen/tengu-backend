"""Wrapper around the Transbank Webpay Plus SDK.

Modos:
- WEBPAY_ENVIRONMENT='test' (default): usa las credenciales públicas de
  integración bundled en el SDK. Tarjetas de prueba documentadas.
- WEBPAY_ENVIRONMENT='live': usa WEBPAY_COMMERCE_CODE y WEBPAY_API_KEY
  de las env vars (las que Transbank te entrega tras la afiliación).

NOTE about TLS: este entorno tiene una cadena de CA root corrupta a nivel de
sistema (mismo síntoma con git y pip). Para que `requests` (que es lo que
usa el SDK por dentro) funcione contra el sandbox de Transbank, se parchea
`requests.Session.request` para saltar la verificación TLS solo en URLs de
Transbank. **Esto solo aplica a integración / sandbox**. Para producción
quita el parche o configura el OS para que confíe en la cadena de Transbank.
"""
import os

import certifi
import requests
import urllib3

from ..config import settings

# Asegura que `requests` use el bundle de certifi.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

# Si la cadena del OS está rota (corp MITM, AV, etc.), saltamos verify SOLO
# para llamadas a transbank.cl. Producción no debería necesitarlo.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_original_request = requests.Session.request


def _request_skip_verify(self, method, url, **kwargs):
    if settings.webpay_environment == "test" and ("transbank" in str(url) or "webpay" in str(url)):
        kwargs["verify"] = False
    return _original_request(self, method, url, **kwargs)


requests.Session.request = _request_skip_verify  # type: ignore[assignment]


from transbank.common.integration_api_keys import IntegrationApiKeys  # noqa: E402
from transbank.common.integration_commerce_codes import IntegrationCommerceCodes  # noqa: E402
from transbank.common.integration_type import IntegrationType  # noqa: E402
from transbank.common.options import WebpayOptions  # noqa: E402
from transbank.webpay.webpay_plus.transaction import Transaction  # noqa: E402


def _get_transaction() -> Transaction:
    if settings.webpay_environment == "live":
        if not settings.webpay_commerce_code or not settings.webpay_api_key:
            raise RuntimeError(
                "WEBPAY_ENVIRONMENT=live pero faltan WEBPAY_COMMERCE_CODE o WEBPAY_API_KEY"
            )
        options = WebpayOptions(
            settings.webpay_commerce_code,
            settings.webpay_api_key,
            IntegrationType.LIVE,
        )
    else:
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
