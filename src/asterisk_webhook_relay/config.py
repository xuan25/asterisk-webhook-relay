from __future__ import annotations

from dataclasses import dataclass
import os


def _integer(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _float(name: str, default: float) -> float:
    value = os.getenv(name, str(default))
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


@dataclass(frozen=True)
class RelayConfig:
    listen_host: str
    listen_port: int
    ami_host: str
    ami_port: int
    ami_username: str
    ami_password: str
    webhook_hmac_secret: bytes
    signature_header: str
    max_body_bytes: int
    max_action_id_bytes: int
    write_queue_size: int
    connect_timeout: float
    login_timeout: float
    write_timeout: float
    submit_timeout: float
    pending_timeout: float
    reconnect_min_delay: float
    reconnect_max_delay: float

    @classmethod
    def from_env(cls) -> "RelayConfig":
        secret = os.getenv("RELAY_WEBHOOK_HMAC_SECRET", "")
        username = os.getenv("RELAY_AMI_USERNAME", "")
        password = os.getenv("RELAY_AMI_PASSWORD", "")
        if not secret:
            raise ValueError("RELAY_WEBHOOK_HMAC_SECRET must be set")
        if not username:
            raise ValueError("RELAY_AMI_USERNAME must be set")
        if not password:
            raise ValueError("RELAY_AMI_PASSWORD must be set")

        min_delay = _float("RELAY_RECONNECT_MIN_DELAY", 1.0)
        max_delay = _float("RELAY_RECONNECT_MAX_DELAY", 30.0)
        if max_delay < min_delay:
            raise ValueError("RELAY_RECONNECT_MAX_DELAY must be >= minimum delay")

        return cls(
            listen_host=os.getenv("RELAY_LISTEN_HOST", "::"),
            listen_port=_integer("RELAY_LISTEN_PORT", 8080),
            ami_host=os.getenv("RELAY_AMI_HOST", "asterisk"),
            ami_port=_integer("RELAY_AMI_PORT", 5038),
            ami_username=username,
            ami_password=password,
            webhook_hmac_secret=secret.encode("utf-8"),
            signature_header=os.getenv(
                "RELAY_WEBHOOK_SIGNATURE_HEADER", "X-Grafana-Alerting-Signature"
            ),
            max_body_bytes=_integer("RELAY_MAX_BODY_BYTES", 65536),
            max_action_id_bytes=_integer("RELAY_MAX_ACTION_ID_BYTES", 256),
            write_queue_size=_integer("RELAY_WRITE_QUEUE_SIZE", 100),
            connect_timeout=_float("RELAY_CONNECT_TIMEOUT", 5.0),
            login_timeout=_float("RELAY_LOGIN_TIMEOUT", 5.0),
            write_timeout=_float("RELAY_WRITE_TIMEOUT", 5.0),
            submit_timeout=_float("RELAY_SUBMIT_TIMEOUT", 10.0),
            pending_timeout=_float("RELAY_PENDING_TIMEOUT", 300.0),
            reconnect_min_delay=min_delay,
            reconnect_max_delay=max_delay,
        )
