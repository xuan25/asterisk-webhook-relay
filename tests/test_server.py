import socket
import unittest

from asterisk_webhook_relay.ami import AmiSessionSupervisor
from asterisk_webhook_relay.config import RelayConfig
from asterisk_webhook_relay.server import create_http_server


@unittest.skipUnless(socket.has_dualstack_ipv6(), "dual-stack IPv6 is unavailable")
class DualStackServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = RelayConfig(
            listen_host="::",
            listen_port=0,
            ami_host="127.0.0.1",
            ami_port=5038,
            ami_username="relay",
            ami_password="secret",
            webhook_hmac_secret=b"webhook-secret",
            signature_header="X-Signature",
            max_body_bytes=1024,
            max_action_id_bytes=64,
            write_queue_size=2,
            connect_timeout=1,
            login_timeout=1,
            write_timeout=1,
            submit_timeout=1,
            pending_timeout=60,
            reconnect_min_delay=1,
            reconnect_max_delay=1,
        )
        self.session = AmiSessionSupervisor(self.config)
        self.server = create_http_server(self.config, self.session)

    def tearDown(self) -> None:
        self.server.server_close()

    def test_accepts_ipv4_and_ipv6_connections(self) -> None:
        port = self.server.server_address[1]
        ipv4 = socket.create_connection(("127.0.0.1", port), timeout=1)
        ipv6 = socket.create_connection(("::1", port), timeout=1)
        ipv4.close()
        ipv6.close()
