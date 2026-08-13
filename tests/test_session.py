import queue
import socket
import threading
import time
import unittest

from asterisk_webhook_relay.ami import AmiSessionSupervisor, SubmitResult
from asterisk_webhook_relay.config import RelayConfig
from asterisk_webhook_relay.frame import StrictAmiFrameNormalizer


class FakeAmiServer:
    def __init__(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.port = self._listener.getsockname()[1]
        self.frames: queue.Queue[bytes] = queue.Queue()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._listener.close()
        self._thread.join(timeout=1)

    def _serve(self) -> None:
        try:
            client, _ = self._listener.accept()
        except OSError:
            return
        with client:
            client.sendall(b"Asterisk Call Manager/5.0\r\n")
            self._read_frame(client)  # Login
            client.sendall(b"Response: Success\r\nMessage: Authentication accepted\r\n\r\n")
            frame = self._read_frame(client)
            self.frames.put(frame)
            client.sendall(b"Response: Success\r\nActionID: delivery-1\r\n\r\n")
            client.sendall(b"Event: OriginateResponse\r\nActionID: delivery-1\r\nResponse: Success\r\n\r\n")
            time.sleep(0.1)

    @staticmethod
    def _read_frame(client: socket.socket) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = client.recv(4096)
            if not chunk:
                raise ConnectionError("client closed before completing AMI frame")
            data += chunk
        return data


class AmiSessionSupervisorTests(unittest.TestCase):
    def test_logs_in_and_serializes_submitted_frame(self) -> None:
        fake = FakeAmiServer()
        fake.start()
        config = RelayConfig(
            listen_host="127.0.0.1",
            listen_port=0,
            ami_host="127.0.0.1",
            ami_port=fake.port,
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
        session = AmiSessionSupervisor(config)
        frame = StrictAmiFrameNormalizer(1024, 64).normalize(
            b"Action: Originate\nActionID: delivery-1\nAsync: true\n"
        )
        session.start()
        try:
            deadline = time.monotonic() + 2
            result = SubmitResult.SESSION_UNAVAILABLE
            while result is SubmitResult.SESSION_UNAVAILABLE and time.monotonic() < deadline:
                time.sleep(0.02)
                result = session.submit(frame)
            self.assertEqual(result, SubmitResult.ACCEPTED)
            self.assertEqual(self.frames_or_timeout(fake), frame.payload)
        finally:
            session.stop()
            fake.close()

    def frames_or_timeout(self, fake: FakeAmiServer) -> bytes:
        return fake.frames.get(timeout=1)
