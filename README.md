# asterisk-webhook-relay

`asterisk-webhook-relay` is a small internal service that accepts a signed Grafana Webhook containing a plain-text Asterisk Manager Interface (AMI) action and writes it to a persistent, authenticated AMI connection. It is designed for Grafana phone alerts: Grafana renders an `Originate` action, Asterisk executes the call, and the relay transports the action without interpreting alert-specific fields.

```text
Grafana Alerting
    → signed POST /ami
    → asterisk-webhook-relay
    → Asterisk AMI
    → alert-notify Dialplan
    → PJSIP phone call
```

## Features

- HMAC-SHA256 authentication over the exact raw Webhook body.
- `POST /ami` endpoint accepting a single `text/plain` AMI frame.
- LF/CRLF normalization with strict AMI frame termination and bare-CR
  rejection.
- Preservation of AMI header order, duplicate `Variable:` headers, and field
  values.
- One long-lived AMI TCP session with AMI Login, reconnect backoff, serialized
  frame writes, and continuous stream reading.
- In-memory `ActionID` correlation and conflict protection for concurrent
  transactions.
- Bounded request body, ActionID, queue, timeout, and reconnect settings.
- IPv4, IPv6, and automatic dual-stack listening when
  `RELAY_LISTEN_HOST=::` is supported by the host.
- Docker and Docker Compose deployment.

## Quick start

### 1. Prepare Asterisk

Complete the Asterisk configuration runbooks in order:

1. [Asterisk AMI configuration](doc/config/asterisk-ami.md)
2. [Alert Dialplan and recordings](doc/config/dialplan.md)

They create the AMI user, `alert-notify` Dialplan, recordings, and a reachable
PJSIP endpoint.

### 2. Create the relay environment file

```sh
cp .env.example .env
```

Set the AMI endpoint and credentials in `.env`; leave the listener and limit
defaults unchanged unless the deployment requires different values. Generate
and configure the shared Webhook HMAC secret using the
[Grafana Webhook configuration](doc/config/grafana-webhook.md).

See [.env.example](.env.example) for every available setting.

### 3. Start the service

```sh
docker compose up -d --build
docker compose logs -f app
```

The service listens on host port `8013` by default. Successful AMI login
produces this log entry:

```text
AMI session is ready
```

### 4. Configure Grafana

Follow the [Grafana Webhook configuration](doc/config/grafana-webhook.md) to
create the notification template, `pbx-alerts` Contact Point, policy, and
alert-rule annotations. Use the relay's reachable `/ami` URL and the same HMAC
secret configured in step 2.

### 5. Verify

Follow the verification sections in the Asterisk, Dialplan, and Grafana
runbooks. A successful relay transport returns `202 Accepted`.

## HTTP contract

```text
POST /ami
Content-Type: text/plain
Content-Length: <body-size>
X-Grafana-Alerting-Signature: <hex-hmac-sha256>

Action: Originate
ActionID: <unique-id>
...

```

The HMAC is calculated over the raw request body. An HTTP proxy between
Grafana and the relay must not rewrite that body.

| Status | Meaning |
| --- | --- |
| `202` | Frame written to a ready AMI session. |
| `400` | Invalid AMI framing or ActionID. |
| `401` | Missing or invalid HMAC signature. |
| `409` | ActionID is already pending. |
| `415` | Request is not `text/plain`. |
| `503` | AMI session unavailable, queue full, write failure, or timeout. |

## Documentation

- [Configuration guide index](doc/config/README.md)
- [Grafana PBX alerting design](doc/arch/grafana-pbx-alerting-design.md)
- [Relay architecture](doc/arch/asterisk-webhook-relay-architecture.md)

## Delivery semantics

The initial release provides at-least-once delivery. If the AMI write succeeds
but the HTTP response is lost, Grafana can retry and create a duplicate call.
The relay does not provide durable idempotency or end-to-end exactly-once
calling.
