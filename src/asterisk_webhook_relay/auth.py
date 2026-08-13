from __future__ import annotations

import hashlib
import hmac


class AuthenticationError(ValueError):
    """The webhook signature is missing or invalid."""


class HmacRequestAuthenticator:
    def __init__(self, secret: bytes, signature_header: str) -> None:
        self._secret = secret
        self._signature_header = signature_header

    def verify(self, headers: object, raw_body: bytes) -> None:
        supplied = headers.get(self._signature_header)
        if not supplied:
            raise AuthenticationError("missing webhook signature")
        expected = hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied.strip(), expected):
            raise AuthenticationError("invalid webhook signature")
