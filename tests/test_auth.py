import hashlib
import hmac
import unittest

from asterisk_webhook_relay.auth import AuthenticationError, HmacRequestAuthenticator


class AuthenticatorTests(unittest.TestCase):
    def test_verifies_exact_raw_body(self) -> None:
        body = b"Action: Originate\nActionID: one\n"
        signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        authenticator = HmacRequestAuthenticator(b"secret", "X-Signature")
        authenticator.verify({"X-Signature": signature}, body)
        with self.assertRaises(AuthenticationError):
            authenticator.verify({"X-Signature": signature}, body + b"\n")
