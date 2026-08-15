# Relay Webhook Direct Test

This runbook tests the complete relay path before Grafana is configured:

```text
curl
    → asterisk-webhook-relay
    → Asterisk AMI
    → service-alert-notify Dialplan
    → recipient endpoint
```

Complete the AMI and Dialplan runbooks first. This test uses the same HMAC
secret that Grafana will later use for the Webhook Contact Point.

## Steps

### Step 1: Configure and start the relay

Create `.env` from the example only when it does not already exist. Set the
AMI host, AMI credentials, and a generated `RELAY_WEBHOOK_HMAC_SECRET`.

```sh
[ -f .env ] || cp .env.example .env
docker compose up -d --build
docker compose logs -f app
```

Continue only after the relay logs:

```text
AMI session is ready
```

For this shell session, export the same HMAC secret that is in `.env`:

```sh
export RELAY_WEBHOOK_HMAC_SECRET='<the-value-from-.env>'
```

### Step 2: Set the test values

Set `AMI_CHANNEL` first, then set every value used by the AMI action. Replace
`<recipient-endpoint>` and select a prompt name installed by the Dialplan.

```sh
export AMI_CHANNEL='PJSIP/<recipient-endpoint>'
export AMI_CONTEXT='service-alert-notify'
export AMI_EXTENSION='s'
export AMI_PRIORITY='1'
export AMI_TIMEOUT='30000'
export AMI_CALLER_ID='PBX Alert <999>'
export ALERT_ID='relay-curl-test'
export ALERT_SEVERITY='critical'
export ALERT_TITLE_TYPE='playback'
export ALERT_TITLE_VALUE='<recording-name>'
```

For advanced logical-destination routing, set `AMI_CHANNEL` to the following
value instead, using the ingress context configured in the Dialplan:

```sh
export AMI_CHANNEL='Local/<logical-destination>@<AMI_INGRESS>/n'
```

### Step 3: Create, sign, and send the AMI action

Run this command only after the values above are set. Each execution generates
a new `AMI_ACTION_ID`, constructs the body, calculates HMAC-SHA256 over that
exact body, and sends it immediately.

```sh
AMI_ACTION_ID="relay-curl-$(date +%s)"; \
body="$(printf \
  'Action: Originate
ActionID: %s
Channel: %s
Context: %s
Exten: %s
Priority: %s
Timeout: %s
CallerID: %s
Variable: __ALERT_ID=%s
Variable: __ALERT_SEVERITY=%s
Variable: __ALERT_TITLE_TYPE=%s
Variable: __ALERT_TITLE_VALUE=%s
Async: true' \
  "$AMI_ACTION_ID" "$AMI_CHANNEL" "$AMI_CONTEXT" "$AMI_EXTENSION" "$AMI_PRIORITY" "$AMI_TIMEOUT" "$AMI_CALLER_ID" \
  "$ALERT_ID" "$ALERT_SEVERITY" "$ALERT_TITLE_TYPE" "$ALERT_TITLE_VALUE")"; \
signature="$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$RELAY_WEBHOOK_HMAC_SECRET" -hex | sed 's/^.* //')"; \
curl -i --data-binary "$body" \
  -H 'Content-Type: text/plain' \
  -H "X-Grafana-Alerting-Signature: $signature" \
  https://relay.internal.example/ami
```

## Examples

### Completed channel selections

For direct endpoint `0001` and the BGP-session-down recording, set the test
values as follows:

```sh
export AMI_CHANNEL='PJSIP/0001'
export ALERT_TITLE_VALUE='alert/event/bgp-session-down'
```

For logical destination `1001` and an AMI ingress context named
`in-call-ami`, set the channel as follows instead:

```sh
export AMI_CHANNEL='Local/1001@in-call-ami/n'
```

Use the actual ingress context configured in the advanced Dialplan rather than
`in-call-ami` when it has a different name.

### Completed direct-endpoint body

With `AMI_CHANNEL='PJSIP/0001'`, the body generated in Step 3 has this shape:

```text
Action: Originate
ActionID: relay-curl-<unix-time>
Channel: PJSIP/0001
Context: service-alert-notify
Exten: s
Priority: 1
Timeout: 30000
CallerID: PBX Alert <999>
Variable: __ALERT_ID=relay-curl-test
Variable: __ALERT_SEVERITY=critical
Variable: __ALERT_TITLE_TYPE=playback
Variable: __ALERT_TITLE_VALUE=alert/event/bgp-session-down
Async: true

```

## Verification

The HTTP response must be:

```text
HTTP/1.0 202 Accepted
```

`202` means the complete frame was written to the authenticated AMI session.
Check Asterisk CLI output for the `Originate` action and execution of
`service-alert-notify`; then answer the endpoint and confirm the recorded alert plays.

## Troubleshooting

| Status or symptom | Check |
| --- | --- |
| `401` | The configured HMAC secrets differ, the signature header differs, or the body changed after signing. |
| `400` | Confirm the body is non-empty and contains exactly one non-empty `ActionID`. |
| `409` | Generate another ActionID; an identical one is still pending. For Grafana, check notification timings. |
| `415` | Confirm the Contact Point has the saved extra header `Content-Type: text/plain`. |
| `503` | Wait for `AMI session is ready`, then check AMI host, credentials, ACL, relay logs, and queue capacity. |
| `202`, but no phone call | Check Asterisk `OriginateResponse`, endpoint contact state, and the `service-alert-notify` Dialplan. |
| Phone rings without audio | Verify prompt names, `CHANNEL(language)`, audio formats/codecs, and RTP reachability. |
