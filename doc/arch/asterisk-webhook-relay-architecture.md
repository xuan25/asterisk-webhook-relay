# asterisk-webhook-relay Architecture

## 1. Purpose

`asterisk-webhook-relay` accepts a signed HTTP webhook body containing one AMI
action and writes it to a persistent, authenticated Asterisk Manager Interface
(AMI) TCP session. The service is an AMI transport relay: it does not interpret
or transform alert-specific AMI fields.

The initial implementation is a standard-library Python service with one HTTP
listener and one process-wide AMI session supervisor.

## 2. Boundary and invariants

The relay owns HTTP authentication, AMI text framing, AMI connection lifecycle,
serialized writes, and in-memory `ActionID` correlation.

It must preserve these invariants:

- HMAC verification uses the exact received request body, before normalization.
- One accepted HTTP body becomes one normalized AMI frame.
- Only line endings and final frame termination change; AMI header order,
  duplicate headers, names, and values are preserved.
- Only the AMI session supervisor accesses the AMI socket.
- At most one writer sends frames on that shared socket at a time.
- `ActionID` is required and unique while its in-memory transaction is pending.

The relay does not validate the meaning of `Action`, `Channel`, `Context`, or
`Variable` headers; Asterisk remains responsible for accepting or rejecting a
validly framed AMI action.

## 3. Components and ownership

```text
Grafana or another internal sender
  │ POST /ami, text/plain, HMAC-SHA256
  ▼
WebhookHandler
  │ raw-body authentication and HTTP status mapping
  ▼
StrictAmiFrameNormalizer
  │ framing normalization and ActionID extraction
  ▼
AmiSessionSupervisor
  │ persistent socket, login, reader, FIFO writer, pending registry
  ▼
Asterisk AMI TCP :5038
```

| Component | Responsibility |
| --- | --- |
| `HmacRequestAuthenticator` | verifies the configured signature header against raw bytes using HMAC-SHA256 and constant-time comparison |
| `StrictAmiFrameNormalizer` | enforces body/framing limits and creates an immutable normalized `AmiFrame` plus `ActionId` |
| `WebhookHandler` | validates the HTTP request and maps a submit result to an HTTP response |
| `AmiSessionSupervisor` | owns AMI state, reconnects, logs in, manages the writer queue and reader, and submits frames |
| `PendingTransactionRegistry` | tracks in-flight ActionIDs for correlation and expiry |
| `AmiProtocolCodec` | reads the AMI banner and CRLF-delimited messages, and builds the AMI Login frame |

## 4. HTTP request contract

The only accepted application request is:

```text
POST /ami
Content-Type: text/plain
Content-Length: <body-size>
X-Grafana-Alerting-Signature: <hex-hmac-sha256>

<one AMI action frame>
```

`Content-Length` is required. The handler checks method, path, content type,
and declared size before reading the body. The following request pipeline then
runs in order:

```text
read raw body
    → verify HMAC over raw bytes
    → normalize AMI framing and extract ActionID
    → reserve ActionID and enqueue frame on the AMI session
    → wait for a complete TCP write or known failure
    → send HTTP status
```

The signature authenticates the sender but does not, by itself, provide replay
prevention. The initial protocol has no timestamp or nonce header.

### Response status

| Status | Meaning |
| --- | --- |
| `202 Accepted` | the complete normalized frame was written to a ready AMI TCP session |
| `400 Bad Request` | invalid or missing AMI framing/ActionID, empty body, or oversized body after read |
| `401 Unauthorized` | missing or invalid HMAC signature |
| `405 Method Not Allowed` | non-POST request; response includes `Allow: POST` |
| `411 Length Required` | missing or invalid `Content-Length` |
| `413 Content Too Large` | declared body exceeds the configured body limit |
| `415 Unsupported Media Type` | content type is not `text/plain` |
| `409 Conflict` | the ActionID is already pending on this relay process |
| `503 Service Unavailable` | AMI is unavailable, the write queue is full, a write fails, or submission times out |

`202` is an AMI transport acknowledgement. It does not mean an AMI action
response was successful, a phone answered, or a Dialplan completed.

## 5. AMI frame handling

AMI messages use `CRLF` line endings and an empty `CRLF` line as the message
terminator. The normalizer processes a webhook body as follows:

1. reject an empty body, body larger than `max_body_bytes`, or a bare CR;
2. convert accepted LF and CRLF input into logical lines;
3. remove trailing empty lines;
4. require exactly one non-empty ASCII `ActionID` within
   `max_action_id_bytes`;
5. join the preserved lines with CRLF and append exactly one `CRLF CRLF`.

It does not convert headers into a map, so duplicate `Variable:` headers and
their original ordering survive the write unchanged.

## 6. AMI session lifecycle

The supervisor holds one long-lived AMI connection. It does not create a new
AMI connection for each webhook request.

```text
Disconnected
    │ connect
    ▼
AwaitBanner
    │ valid Asterisk Call Manager banner
    ▼
AwaitLoginResponse
    │ successful AMI Login response
    ▼
Ready
    │ read or write failure
    ▼
Disconnected → exponential backoff → connect
```

The AMI username and password come only from relay configuration. After a
successful Login, the supervisor starts a reader loop and drains a bounded FIFO
queue. A disconnect clears the current pending registry, fails queued work
that has not written, closes the socket, and starts reconnect backoff.

## 7. Submission, concurrency, and correlation

HTTP handlers may run concurrently, but they interact with AMI through
`AmiSessionSupervisor.submit()`:

1. the supervisor requires state `Ready`;
2. it reserves the frame's ActionID in `PendingTransactionRegistry`;
3. it puts an `OutboundTransaction` into the bounded FIFO queue;
4. the single writer uses `sendall()` for the whole frame;
5. the HTTP handler receives `Accepted` only after that write succeeds.

The writer removes a reservation when queueing fails. The reader continuously
parses AMI messages and records matching `ActionID` messages in the associated
pending transaction. Pending records expire after `pending_timeout`; unrelated
AMI events are simply consumed.

For `Async: true` `Originate`, Asterisk later emits a synchronous response and
an `OriginateResponse` event. The reader can correlate them, but the initial
service has no public status endpoint or callback and never changes a response
that has already returned `202`.

## 8. Delivery semantics

The delivery guarantee is at least once:

```text
202      write completed; sender treats the frame as accepted
non-2xx  write was not confirmed; sender may retry
```

A TCP connection can fail after a remote peer receives bytes but before the
relay returns an HTTP response. A sender retry can therefore create a duplicate
AMI action. The relay intentionally does not retry an uncertain local write,
and its pending ActionID table is neither durable nor an idempotency store.
Restarting the relay loses pending correlation state.

## 9. Configuration and network listener

`RelayConfig` is loaded from environment variables at startup. Required values
are AMI username/password and the webhook HMAC secret. Other values configure
the AMI endpoint, HTTP listener, size limits, queue size, timeouts, and
reconnect backoff.

The listen host determines address-family behaviour:

| `RELAY_LISTEN_HOST` | Listener |
| --- | --- |
| `::` | IPv6 socket with `IPV6_V6ONLY=0`; accepts IPv6 and IPv4 when platform support is available |
| IPv6 literal other than `::` | IPv6-only socket |
| IPv4 literal or hostname | standard IPv4 listener |

The process fails at startup when `::` dual-stack mode is requested but the
platform cannot provide it. This avoids silently exposing a listener on only
one address family.

## 10. Python object design

The implementation has a compact object graph:

```text
main()
 ├── RelayConfig.from_env()
 ├── AmiSessionSupervisor(config)
 │    ├── queue.Queue[OutboundTransaction]
 │    ├── PendingTransactionRegistry
 │    └── AMI manager and reader threads
 └── create_http_server(config, session)
      ├── HmacRequestAuthenticator
      ├── StrictAmiFrameNormalizer
      └── configured WebhookHandler class
```

`RelayConfig`, `ActionId`, and `AmiFrame` are immutable values. The supervisor
is the only mutable AMI owner and protects session state and the pending
registry with a re-entrant lock. `OutboundTransaction` carries a completion
event, allowing the HTTP thread to wait only for the write result without
reading the AMI socket.

This separation makes unit tests straightforward: authentication and framing
are pure local operations; a fake AMI server can exercise login, serialization,
and reconnect behaviour without an HTTP framework or production Asterisk.

## 11. Verification focus

The initial test suite covers raw-body HMAC verification, frame normalization,
ActionID validation, AMI Login and serialized writes, and IPv4/IPv6 listener
behaviour. The next high-value tests are queue saturation, disconnect timing,
interleaved AMI events, and pending-record expiry.

Operational verification should separately confirm that Grafana receives
`202`, Asterisk receives the expected AMI action, and the target Dialplan and
PJSIP endpoint execute the call. Those are successive checks; none alone
proves the entire path.
