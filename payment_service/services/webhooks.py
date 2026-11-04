from payment_service.adapters import get_adapter
from payment_service.adapters.base import ProviderError
from payment_service.repositories.webhooks import confirm_status, find_operation


async def verify_notification(event: str, provider_id: str) -> str:
    operation = await find_operation(event, provider_id)
    if operation is None:
        return "unavailable"
    try:
        if event.startswith("refund."):
            result = await get_adapter().get_refund(provider_id)
            payment = operation.payment
            matches = (result.provider_id == provider_id
                       and result.provider_payment_id == payment.provider_payment_id
                       and result.amount_kopecks == operation.amount_kopecks
                       and operation.currency == "RUB")
        else:
            result = await get_adapter().get_payment(provider_id)
            matches = (result.provider_id == provider_id
                       and result.payment_id == operation.id
                       and result.amount_kopecks == operation.amount_kopecks
                       and operation.currency == "RUB")
    except ProviderError:
        return "unavailable"
    if not matches:
        return "ignored"
    status = "pending" if result.status == "waiting_for_capture" else result.status
    if status == "pending":
        return "unavailable"
    await confirm_status(event, provider_id, status)
    return "accepted"
