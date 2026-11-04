from litestar import Litestar

from payment_service.api.health import live, ready
from payment_service.api.payments import create_payment, read_payment
from payment_service.api.refunds import create_refund, read_refund
from payment_service.api.webhooks import receive_yookassa_webhook
from payment_service.api.metrics import metrics
from payment_service.core.auth import authorize_internal_request

app = Litestar(
    route_handlers=[live, ready, metrics, create_payment, read_payment, create_refund, read_refund, receive_yookassa_webhook],
    before_request=authorize_internal_request,
)
