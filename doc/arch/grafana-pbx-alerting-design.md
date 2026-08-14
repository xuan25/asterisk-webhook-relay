# Grafana PBX Alerting Design

## 1. Purpose

This design delivers a Grafana firing alert as a PBX phone call. Grafana
renders the AMI `Originate` action, `asterisk-webhook-relay` delivers that
action to Asterisk AMI, and Asterisk plays the announcement.

The initial design uses one alert instance per phone call. Announcements use
controlled recordings and Asterisk `Say*()` applications; TTS is not required.

## 2. Responsibilities

Each component owns one layer of the workflow.

| Component | Owns | Does not own |
| --- | --- | --- |
| Grafana | alert evaluation, notification policy, recipient/channel selection, AMI action template, alert-specific prompt and field values | AMI credentials or PBX media execution |
| asterisk-webhook-relay | Webhook authentication, AMI framing, persistent AMI connection, serialized writes, response/event correlation | alert-specific interpretation or AMI business-field changes |
| Asterisk | call origination, Dialplan execution, recordings, `Say*()` rendering, SIP media | Grafana routing or Webhook authentication |

The ownership rule is simple: Grafana decides what phone action to request; the
relay delivers it; Asterisk executes and plays it.

## 3. End-to-end flow

```text
Grafana Alert Rule fires
        │
        ▼
Notification Policy matches phone_alert=true
        │
        ▼
Webhook Contact Point renders one AMI Originate frame
        │  POST /ami, Content-Type: text/plain, HMAC-SHA256
        ▼
asterisk-webhook-relay
        │  authenticated persistent AMI TCP session
        ▼
Asterisk
        │  Context: alert-notify, Exten: s
        ▼
alert-notify Dialplan
        │
        ▼
PJSIP endpoint plays recordings and dynamic values
```

The relay returns `202 Accepted` after it writes the normalized AMI frame to
an authenticated AMI TCP connection. It does not wait for the phone to answer
or for the call to finish.

## 4. Grafana notification model

### 4.1 Routing

An Alert Rule that should make a phone call carries this label:

```text
phone_alert = true
```

A child Notification Policy matching that label routes the notification to the
PBX Webhook Contact Point. Rules without the label follow their other normal
notification routes.

### 4.2 One alert instance per request

The PBX Notification Policy sets:

```text
Group by: [...]
```

`[...]` disables Grafana grouping. This is required in the initial design:
the template renders one alert instance and the Dialplan accepts one title and
up to three fields for one call. The Contact Point also uses `Max alerts: 1`
as a guard rail and disables resolved notifications.

The resulting mapping is linear:

```text
one firing alert instance
    → one Webhook request
    → one AMI Originate action
    → one phone call
```

### 4.3 Rendered AMI action

The Grafana Notification Template renders a complete AMI frame. Fixed call
routing fields are the recipient `Channel`, `Context: alert-notify`,
`Exten: s`, and `Priority: 1`. Alert-specific data is carried by AMI
`Variable:` headers.

```text
Action: Originate
ActionID: grafana-<fingerprint>-<firing-start-time>
Channel: PJSIP/<endpoint-from-pbx_endpoint-annotation>
Context: alert-notify
Exten: s
Priority: 1
Timeout: 30000
CallerID: PBX Alert <999>
Variable: __ALERT_ID=<fingerprint>
Variable: __ALERT_SEVERITY=<critical-or-warning>
Variable: __ALERT_TITLE_TYPE=<renderer-type>
Variable: __ALERT_TITLE_VALUE=<recording-or-value>
Async: true

```

An optional dynamic field uses this group, where `n` is 1 through 3:

```text
Variable: __ALERT_FIELDn_LABEL=<recording>
Variable: __ALERT_FIELDn_TYPE=<renderer-type>
Variable: __ALERT_FIELDn_VALUE=<value>
Variable: __ALERT_FIELDn_SUFFIX=<optional-recording>
```

`ActionID` combines the Grafana alert fingerprint and firing start time. It
remains constant for reminders in the same firing cycle and changes when that
alert fires in a later cycle.

### 4.4 Advanced logical-destination routing

The simple mode uses `Channel: PJSIP/<endpoint>` and therefore couples the
Grafana template to one endpoint implementation. The advanced mode uses:

```text
Channel: Local/<logical-destination>@<ami-ingress-context>/n
```

This moves destination resolution into Asterisk. The AMI ingress context marks
the call source, runs site-specific accounting if required, and transfers the
logical destination to the PBX's canonical routing context. That context can
then choose a local endpoint, ENUM resolution, or any outbound trunk without a
Grafana template change.

```text
Grafana logical destination
    → Local channel
    → AMI ingress context
    → canonical PBX number routing
    → selected endpoint or outbound peer
```

`/n` keeps the Local channel after answer, preserving ingress variables and
call lifecycle visibility. The call's `CallerID`, the outbound PJSIP
`from_domain`, and transport signalling/media addresses remain separate
concerns: respectively channel identity, endpoint SIP identity, and transport
reachability.

## 5. Asterisk rendering contract

The AMI action enters `alert-notify,s,1`. The Dialplan plays the announcement
in this order:

```text
header
severity recording
title
field 1, if present
field 2, if present
field 3, if present
hang up
```

`alert-render` maps the four permitted renderer types to Asterisk behaviour:

| Type | Asterisk action |
| --- | --- |
| `playback` | `Playback()` of a controlled recording |
| `digits` | `SayDigits()` |
| `number` | `SayNumber()` |
| `alpha` | `SayAlpha()` |

The Dialplan does not branch on alert names. Adding an alert normally means
adding or reusing a prompt and selecting the title and fields in that Alert
Rule's Grafana annotations.

## 6. Relay contract

Grafana sends the AMI frame as the `text/plain` request body to `POST /ami`,
with an HMAC-SHA256 signature. The relay verifies the signature over the exact
raw body before processing it.

The relay accepts LF or CRLF, rejects bare CR, removes only surplus terminal
empty lines, and finishes with exactly one `CRLF CRLF`. It reads `ActionID`
only to correlate AMI traffic. AMI header order, duplicate `Variable:`
headers, names, and values remain unchanged. It does not select prompts,
modify severity, or translate an alert schema.

AMI credentials are relay-local configuration; Grafana does not send an AMI
`Login` action.

## 7. Delivery and failure semantics

The initial delivery model is at least once:

```text
202
    the complete frame was written to the authenticated AMI TCP session

non-2xx
    the relay did not confirm that write; Grafana may retry
```

An `Originate` action with `Async: true` has two later AMI outcomes: the
synchronous action response and an `OriginateResponse` event. The relay reads
and correlates both by `ActionID`, but neither changes an already returned
HTTP `202`.

If the AMI write succeeds but the HTTP response is lost before Grafana receives
it, Grafana can retry and create another call. The initial release has no
durable idempotency record or end-to-end exactly-once guarantee. Reuse of an
ActionID while it is pending is rejected to protect in-flight response
correlation; this is not deduplication across retries or process restarts.

## 8. Initial boundary and future work

The initial release includes HMAC authentication, one alert per call,
controlled recordings, dynamic digit/number/alphabet rendering, AMI reconnect,
and bounded in-memory request handling.

Grouped alert announcements, durable retry/idempotency, call-result callbacks,
TTS, and other alert sources need their own design before implementation. They
must preserve the responsibilities in section 2 rather than move alert-specific
mapping into the relay.
