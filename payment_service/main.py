from litestar import Litestar

from payment_service.api.health import live, ready
from payment_service.api.payments import create_payment, read_payment
from payment_service.api.webhooks import receive_yookassa_webhook
from payment_service.core.auth import authorize_internal_request

app = Litestar(
    route_handlers=[live, ready, create_payment, read_payment, receive_yookassa_webhook],
    before_request=authorize_internal_request,
)
