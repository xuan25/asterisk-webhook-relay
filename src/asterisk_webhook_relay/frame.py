from __future__ import annotations

from dataclasses import dataclass


class FrameError(ValueError):
    """The webhook body cannot be represented as a single AMI frame."""


@dataclass(frozen=True)
class ActionId:
    value: str


@dataclass(frozen=True)
class AmiFrame:
    payload: bytes
    action_id: ActionId


class StrictAmiFrameNormalizer:
    def __init__(self, max_body_bytes: int, max_action_id_bytes: int) -> None:
        self._max_body_bytes = max_body_bytes
        self._max_action_id_bytes = max_action_id_bytes

    def normalize(self, body: bytes) -> AmiFrame:
        if not body:
            raise FrameError("request body is empty")
        if len(body) > self._max_body_bytes:
            raise FrameError("request body exceeds configured limit")
        if b"\r" in body.replace(b"\r\n", b""):
            raise FrameError("bare CR is not valid AMI framing")

        lines = body.replace(b"\r\n", b"\n").split(b"\n")
        while lines and lines[-1] == b"":
            lines.pop()
        if not lines:
            raise FrameError("request body contains no AMI headers")

        action_ids: list[bytes] = []
        for line in lines:
            if b":" not in line:
                continue
            name, value = line.split(b":", 1)
            if name.lower() == b"actionid":
                action_ids.append(value.strip())
        if len(action_ids) != 1 or not action_ids[0]:
            raise FrameError("exactly one non-empty ActionID header is required")
        if len(action_ids[0]) > self._max_action_id_bytes:
            raise FrameError("ActionID exceeds configured limit")
        try:
            action_id = ActionId(action_ids[0].decode("ascii"))
        except UnicodeDecodeError as exc:
            raise FrameError("ActionID must be ASCII") from exc

        return AmiFrame(payload=b"\r\n".join(lines) + b"\r\n\r\n", action_id=action_id)
