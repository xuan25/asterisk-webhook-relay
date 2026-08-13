from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import logging
import socket

from .ami import AmiSessionSupervisor, SubmitResult
from .auth import AuthenticationError, HmacRequestAuthenticator
from .config import RelayConfig
from .frame import FrameError, StrictAmiFrameNormalizer


LOG = logging.getLogger(__name__)


class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server with an explicitly selected IPv6 socket mode."""

    address_family = socket.AF_INET6

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], *, dual_stack: bool) -> None:
        self._dual_stack = dual_stack
        super().__init__(address, handler)

    def server_bind(self) -> None:
        try:
            self.socket.setsockopt(
                socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, int(not self._dual_stack)
            )
        except OSError as exc:
            if self._dual_stack:
                raise OSError("the platform does not support an IPv6 dual-stack listener") from exc
            raise
        super().server_bind()


class WebhookHandler(BaseHTTPRequestHandler):
    authenticator: HmacRequestAuthenticator
    normalizer: StrictAmiFrameNormalizer
    session: AmiSessionSupervisor
    config: RelayConfig

    server_version = "asterisk-webhook-relay/0.1"

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/ami":
            self._respond(HTTPStatus.NOT_FOUND)
            return
        if self.headers.get("Content-Type") is None or self.headers.get_content_type() != "text/plain":
            self._respond(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        content_length = self.headers.get("Content-Length")
        try:
            size = int(content_length) if content_length is not None else -1
        except ValueError:
            size = -1
        if size < 0:
            self._respond(HTTPStatus.LENGTH_REQUIRED)
            return
        if size > self.config.max_body_bytes:
            self._respond(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        body = self.rfile.read(size)
        try:
            self.authenticator.verify(self.headers, body)
            frame = self.normalizer.normalize(body)
        except AuthenticationError:
            self._respond(HTTPStatus.UNAUTHORIZED)
            return
        except FrameError:
            self._respond(HTTPStatus.BAD_REQUEST)
            return

        result = self.session.submit(frame)
        status = {
            SubmitResult.ACCEPTED: HTTPStatus.ACCEPTED,
            SubmitResult.ACTION_ID_CONFLICT: HTTPStatus.CONFLICT,
            SubmitResult.SESSION_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
            SubmitResult.QUEUE_FULL: HTTPStatus.SERVICE_UNAVAILABLE,
            SubmitResult.WRITE_FAILED: HTTPStatus.SERVICE_UNAVAILABLE,
            SubmitResult.TIMEOUT: HTTPStatus.SERVICE_UNAVAILABLE,
        }[result]
        self._respond(status)

    def do_GET(self) -> None:  # noqa: N802
        self._respond(HTTPStatus.METHOD_NOT_ALLOWED, {"Allow": "POST"})

    def do_PUT(self) -> None:  # noqa: N802
        self._respond(HTTPStatus.METHOD_NOT_ALLOWED, {"Allow": "POST"})

    def log_message(self, format: str, *args: object) -> None:
        LOG.info("%s - %s", self.address_string(), format % args)

    def _respond(self, status: HTTPStatus, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()


def create_http_server(config: RelayConfig, session: AmiSessionSupervisor) -> ThreadingHTTPServer:
    authenticator = HmacRequestAuthenticator(config.webhook_hmac_secret, config.signature_header)
    normalizer = StrictAmiFrameNormalizer(config.max_body_bytes, config.max_action_id_bytes)

    class ConfiguredWebhookHandler(WebhookHandler):
        pass

    ConfiguredWebhookHandler.authenticator = authenticator
    ConfiguredWebhookHandler.normalizer = normalizer
    ConfiguredWebhookHandler.session = session
    ConfiguredWebhookHandler.config = config
    try:
        address = ipaddress.ip_address(config.listen_host)
    except ValueError:
        address = None

    if config.listen_host == "::":
        if not socket.has_dualstack_ipv6():
            raise OSError("the platform does not support an IPv6 dual-stack listener")
        return IPv6ThreadingHTTPServer((config.listen_host, config.listen_port), ConfiguredWebhookHandler, dual_stack=True)
    if isinstance(address, ipaddress.IPv6Address):
        return IPv6ThreadingHTTPServer((config.listen_host, config.listen_port), ConfiguredWebhookHandler, dual_stack=False)
    return ThreadingHTTPServer((config.listen_host, config.listen_port), ConfiguredWebhookHandler)
