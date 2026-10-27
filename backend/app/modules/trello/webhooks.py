import base64
import hashlib
import hmac


def trello_webhook_signature(body: bytes, secret: str, callback_url: str) -> str:
    digest = hmac.new(
        secret.encode(),
        body + callback_url.encode(),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_trello_webhook_signature(
    body: bytes,
    signature: str | None,
    secret: str,
    callback_url: str,
) -> bool:
    if not signature:
        return False
    expected = trello_webhook_signature(body, secret, callback_url)
    return hmac.compare_digest(expected, signature)
