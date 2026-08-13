from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import queue
import socket
import threading
import time
from typing import Optional

from .config import RelayConfig
from .frame import ActionId, AmiFrame


LOG = logging.getLogger(__name__)


class SessionState(str, Enum):
    DISCONNECTED = "disconnected"
    AWAIT_BANNER = "await_banner"
    AWAIT_LOGIN_RESPONSE = "await_login_response"
    READY = "ready"
    STOPPED = "stopped"


class SubmitResult(str, Enum):
    ACCEPTED = "accepted"
    SESSION_UNAVAILABLE = "session_unavailable"
    QUEUE_FULL = "queue_full"
    ACTION_ID_CONFLICT = "action_id_conflict"
    WRITE_FAILED = "write_failed"
    TIMEOUT = "timeout"


@dataclass
class PendingTransaction:
    action_id: ActionId
    registered_at: float
    written: bool = False
    observed_messages: list[dict[str, str]] = field(default_factory=list)


class PendingTransactionRegistry:
    def __init__(self, pending_timeout: float) -> None:
        self._pending_timeout = pending_timeout
        self._items: dict[str, PendingTransaction] = {}

    def reserve(self, action_id: ActionId) -> bool:
        self.expire()
        if action_id.value in self._items:
            return False
        self._items[action_id.value] = PendingTransaction(action_id, time.monotonic())
        return True

    def remove(self, action_id: ActionId) -> None:
        self._items.pop(action_id.value, None)

    def mark_written(self, action_id: ActionId) -> None:
        if pending := self._items.get(action_id.value):
            pending.written = True

    def observe(self, headers: dict[str, str]) -> None:
        action_id = headers.get("actionid")
        if action_id and (pending := self._items.get(action_id)):
            pending.observed_messages.append(headers)

    def expire(self) -> None:
        cutoff = time.monotonic() - self._pending_timeout
        for key, pending in list(self._items.items()):
            if pending.registered_at < cutoff:
                self._items.pop(key, None)

    def clear(self) -> None:
        self._items.clear()


@dataclass
class OutboundTransaction:
    frame: AmiFrame
    completion: threading.Event = field(default_factory=threading.Event)
    result: Optional[SubmitResult] = None


class AmiProtocolCodec:
    @staticmethod
    def read_banner(connection: socket.socket, buffer: bytes) -> tuple[str, bytes]:
        while b"\r\n" not in buffer:
            chunk = connection.recv(4096)
            if not chunk:
                raise ConnectionError("AMI connection closed before banner")
            buffer += chunk
        raw_banner, remaining = buffer.split(b"\r\n", 1)
        banner = raw_banner.decode("ascii", "replace")
        if not banner.startswith("Asterisk Call Manager/"):
            raise ConnectionError(f"unexpected AMI banner: {banner!r}")
        return banner, remaining

    @staticmethod
    def read_message(connection: socket.socket, buffer: bytes) -> tuple[dict[str, str], bytes]:
        while b"\r\n\r\n" not in buffer:
            chunk = connection.recv(4096)
            if not chunk:
                raise ConnectionError("AMI connection closed")
            buffer += chunk
        raw_message, remaining = buffer.split(b"\r\n\r\n", 1)
        headers: dict[str, str] = {}
        for line in raw_message.split(b"\r\n"):
            if b":" not in line:
                continue
            key, value = line.split(b":", 1)
            headers[key.decode("ascii", "replace").lower()] = value.strip().decode(
                "utf-8", "replace"
            )
        return headers, remaining

    @staticmethod
    def login_frame(username: str, password: str) -> bytes:
        return (
            f"Action: Login\r\nUsername: {username}\r\nSecret: {password}\r\n"
            "Events: on\r\n\r\n"
        ).encode("utf-8")


class AmiSessionSupervisor:
    """Single owner of the AMI socket, write queue, reader, and state."""

    def __init__(self, config: RelayConfig) -> None:
        self._config = config
        self._state = SessionState.DISCONNECTED
        self._state_lock = threading.RLock()
        self._stop = threading.Event()
        self._queue: queue.Queue[OutboundTransaction] = queue.Queue(config.write_queue_size)
        self._registry = PendingTransactionRegistry(config.pending_timeout)
        self._connection: Optional[socket.socket] = None
        self._manager = threading.Thread(target=self._run, name="ami-manager", daemon=True)

    def start(self) -> None:
        self._manager.start()

    def stop(self) -> None:
        self._stop.set()
        self._disconnect()
        self._manager.join(timeout=self._config.connect_timeout + 1)
        with self._state_lock:
            self._state = SessionState.STOPPED

    def submit(self, frame: AmiFrame) -> SubmitResult:
        transaction = OutboundTransaction(frame)
        with self._state_lock:
            if self._state is not SessionState.READY:
                return SubmitResult.SESSION_UNAVAILABLE
            if not self._registry.reserve(frame.action_id):
                return SubmitResult.ACTION_ID_CONFLICT
            try:
                self._queue.put_nowait(transaction)
            except queue.Full:
                self._registry.remove(frame.action_id)
                return SubmitResult.QUEUE_FULL

        if not transaction.completion.wait(self._config.submit_timeout):
            return SubmitResult.TIMEOUT
        return transaction.result or SubmitResult.WRITE_FAILED

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                self._connect_and_login()
                failures = 0
                self._serve_connection()
            except (OSError, ConnectionError, TimeoutError) as exc:
                LOG.warning("AMI session unavailable: %s", exc)
            finally:
                self._disconnect()
            if self._stop.is_set():
                break
            delay = min(
                self._config.reconnect_min_delay * (2**failures),
                self._config.reconnect_max_delay,
            )
            failures += 1
            self._stop.wait(delay)

    def _connect_and_login(self) -> None:
        with self._state_lock:
            self._state = SessionState.AWAIT_BANNER
        connection = socket.create_connection(
            (self._config.ami_host, self._config.ami_port), self._config.connect_timeout
        )
        connection.settimeout(self._config.login_timeout)
        with self._state_lock:
            self._connection = connection
        _, remainder = AmiProtocolCodec.read_banner(connection, b"")
        with self._state_lock:
            self._state = SessionState.AWAIT_LOGIN_RESPONSE
        connection.sendall(AmiProtocolCodec.login_frame(self._config.ami_username, self._config.ami_password))
        response, remainder = AmiProtocolCodec.read_message(connection, remainder)
        if response.get("response", "").lower() != "success":
            raise ConnectionError(f"AMI login failed: {response.get('message', 'unknown error')}")
        connection.settimeout(None)
        self._reader_remainder = remainder
        with self._state_lock:
            self._state = SessionState.READY
        LOG.info("AMI session is ready")

    def _serve_connection(self) -> None:
        with self._state_lock:
            connection = self._connection
        if connection is None:
            raise ConnectionError("AMI connection disappeared")
        reader = threading.Thread(target=self._reader_loop, args=(connection,), name="ami-reader", daemon=True)
        reader.start()
        try:
            while not self._stop.is_set() and reader.is_alive():
                try:
                    transaction = self._queue.get(timeout=0.25)
                except queue.Empty:
                    with self._state_lock:
                        self._registry.expire()
                    continue
                self._write_transaction(connection, transaction)
        finally:
            self._disconnect()
            reader.join(timeout=1)

    def _write_transaction(self, connection: socket.socket, transaction: OutboundTransaction) -> None:
        try:
            connection.settimeout(self._config.write_timeout)
            connection.sendall(transaction.frame.payload)
            connection.settimeout(None)
            with self._state_lock:
                self._registry.mark_written(transaction.frame.action_id)
            transaction.result = SubmitResult.ACCEPTED
        except OSError as exc:
            transaction.result = SubmitResult.WRITE_FAILED
            raise ConnectionError("AMI write failed") from exc
        finally:
            transaction.completion.set()

    def _reader_loop(self, connection: socket.socket) -> None:
        buffer = self._reader_remainder
        try:
            while not self._stop.is_set():
                try:
                    headers, buffer = AmiProtocolCodec.read_message(connection, buffer)
                except socket.timeout:
                    continue
                with self._state_lock:
                    self._registry.observe(headers)
        except (OSError, ConnectionError) as exc:
            LOG.warning("AMI reader stopped: %s", exc)
            self._disconnect()

    def _disconnect(self) -> None:
        with self._state_lock:
            connection, self._connection = self._connection, None
            if self._state is not SessionState.STOPPED:
                self._state = SessionState.DISCONNECTED
            self._registry.clear()
            while True:
                try:
                    transaction = self._queue.get_nowait()
                except queue.Empty:
                    break
                transaction.result = SubmitResult.WRITE_FAILED
                transaction.completion.set()
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
