# Grafana Webhook Configuration for PBX Alerts

This guide configures self-hosted Grafana Alerting to render an AMI
`Originate` action as a signed `text/plain` Webhook request for
`asterisk-webhook-relay`. One firing alert produces one phone call.

## Steps

### Step 1: Generate and configure the HMAC secret

Generate one secret and set it in the relay `.env` file:

```sh
hmac_secret="$(openssl rand -hex 32)"
printf 'RELAY_WEBHOOK_HMAC_SECRET=%s\n' "$hmac_secret"
```

Keep this value for the Webhook Contact Point in Step 3. The signature covers
the exact request body, so no proxy between Grafana and the relay may rewrite
that body.

### Step 2: Create the notification template

Navigate to:

```text
Side bar → Alerting → Notification configuration → Templates
```

Create a template group and add this complete named template. Replace
`PBX Alert <999>` before saving.

```gotemplate
{{ define "pbx.ami.originate" -}}
{{- $alert := index .Alerts 0 -}}
Action: Originate
ActionID: grafana-{{ $alert.Fingerprint }}-{{ $alert.StartsAt.Unix }}
Channel: PJSIP/{{ $alert.Annotations.pbx_endpoint }}
Context: service-alert-notify
Exten: s
Priority: 1
Timeout: 30000
CallerID: PBX Alert <999>
Variable: __ALERT_ID={{ $alert.Fingerprint }}
Variable: __ALERT_SEVERITY={{ or $alert.Annotations.pbx_severity "warning" }}
Variable: __ALERT_TITLE_TYPE={{ $alert.Annotations.pbx_title_type }}
Variable: __ALERT_TITLE_VALUE={{ $alert.Annotations.pbx_title_value }}
{{- with $alert.Annotations.pbx_field1_label }}
Variable: __ALERT_FIELD1_LABEL={{ . }}
{{- end }}
{{- with $alert.Annotations.pbx_field1_type }}
Variable: __ALERT_FIELD1_TYPE={{ . }}
{{- end }}
{{- with $alert.Annotations.pbx_field1_value }}
Variable: __ALERT_FIELD1_VALUE={{ . }}
{{- end }}
{{- with $alert.Annotations.pbx_field1_suffix }}
Variable: __ALERT_FIELD1_SUFFIX={{ . }}
{{- end }}
{{- with $alert.Annotations.pbx_field2_label }}
Variable: __ALERT_FIELD2_LABEL={{ . }}
{{- end }}
{{- with $alert.Annotations.pbx_field2_type }}
Variable: __ALERT_FIELD2_TYPE={{ . }}
{{- end }}
{{- with $alert.Annotations.pbx_field2_value }}
Variable: __ALERT_FIELD2_VALUE={{ . }}
{{- end }}
{{- with $alert.Annotations.pbx_field2_suffix }}
Variable: __ALERT_FIELD2_SUFFIX={{ . }}
{{- end }}
{{- with $alert.Annotations.pbx_field3_label }}
Variable: __ALERT_FIELD3_LABEL={{ . }}
{{- end }}
{{- with $alert.Annotations.pbx_field3_type }}
Variable: __ALERT_FIELD3_TYPE={{ . }}
{{- end }}
{{- with $alert.Annotations.pbx_field3_value }}
Variable: __ALERT_FIELD3_VALUE={{ . }}
{{- end }}
{{- with $alert.Annotations.pbx_field3_suffix }}
Variable: __ALERT_FIELD3_SUFFIX={{ . }}
{{- end }}
Async: true
{{- end }}
```

The template renders exactly one AMI frame for the first alert in the
notification. In simple mode, `pbx_endpoint` is the PJSIP endpoint name
without the `PJSIP/` prefix. The policy in Step 4 disables grouping, making
that one alert the complete notification. `ActionID` combines fingerprint and
firing start time: repeated reminders within one firing cycle retain the same
ActionID.

### Advanced mode: route a logical destination through Asterisk

The template above is the simple mode: it directly creates a PJSIP channel for
the endpoint named by `pbx_endpoint`. Use the advanced mode when Grafana should
name a logical destination and let the PBX decide whether that number is local,
ENUM-routed, or sent to another outbound peer.

Replace only the `Channel:` line in the notification template with:

```gotemplate
Channel: Local/{{ $alert.Annotations.pbx_destination }}@<AMI_INGRESS>/n
```

Replace `<AMI_INGRESS>` with the dedicated AMI ingress context from
the advanced Dialplan configuration. For every rule sent through this template,
add a non-empty `pbx_destination` annotation containing the logical number to
call. The PBX Dialplan, not Grafana, validates and routes that number.

In an AMI `Originate`, `Channel` identifies who to call; the existing
`Context`, `Exten`, and `Priority` fields identify what runs after answer. The
`/n` suffix retains the Local channel after answer, preserving ingress
variables, logging, and channel lifecycle visibility.

Use a separate template and Contact Point when simple direct-endpoint rules and
advanced logical-destination rules must coexist. The Notification Policy can
route them with distinct labels.

### Step 3: Create the Webhook Contact Point

Navigate to:

```text
Side bar → Alerting → Notification configuration → Contact points
```

Create a Contact Point named `pbx-alerts`, add a **Webhook** integration, and
set these fields:

| Field | Value |
| --- | --- |
| URL | `https://relay.internal.example/ami` |
| HTTP method | `POST` |
| Extra header | `Content-Type: text/plain` |
| Max alerts | `1` |
| Disable resolved message | enabled |
| HMAC signature | enabled |
| HMAC secret | the value generated in Step 1 |
| Signature header | `X-Grafana-Alerting-Signature` |

When adding the extra header, click Grafana's confirmation check mark before
saving; otherwise it is not retained and the relay returns `415 Unsupported
Media Type` for Grafana's default JSON content type.

In **Custom Payload**, enter exactly:

```gotemplate
{{ template "pbx.ami.originate" . }}
```

### Step 4: Create the notification policy

Navigate to:

```text
Side bar → Alerting → Notification configuration → Notification policies
```

Create a child policy with these settings:

| Field | Value |
| --- | --- |
| Contact point | `pbx-alerts` |
| Matcher | `phone_alert = true` |
| Group by | `[...]` |
| Group wait | `30s` |
| Group interval | `5m` |
| Repeat interval | `4h` |

`[...]` disables grouping. It is required because the template selects one
alert and `Max alerts: 1` alone does not prevent Grafana from grouping alerts.

### Step 5: Configure a PBX alert rule

On each Alert Rule that should call the PBX, add the label:

```text
phone_alert = true
```

Add these annotations to the same rule:

| Annotation | Value | Required |
| --- | --- | --- |
| `pbx_title_type` | `playback` | yes |
| `pbx_title_value` | a recorded prompt name, for example `alert/event/bgp-session-down` | yes |
| `pbx_severity` | `critical` or `warning` | yes |
| `pbx_endpoint` | PJSIP endpoint name without `PJSIP/` | required in simple mode |
| `pbx_destination` | logical number accepted by the AMI ingress Dialplan | required in advanced mode |
| `pbx_field<n>_label` | a recorded prompt name; `n` is 1, 2, or 3 | only when that field is used |
| `pbx_field<n>_type` | `digits`, `number`, `alpha`, or `playback` | only when that field is used |
| `pbx_field<n>_value` | an Alert Rule template or literal value | only when that field is used |
| `pbx_field<n>_suffix` | a recorded prompt name | optional |

Each used field needs `label`, `type`, and `value`; `suffix` is optional. The
template renders all three field groups. Title and field prompt names must
exist in the Asterisk sounds directory. A `pbx_field<n>_value` is rendered by
the Alert Rule; it can use values such as `{{ $labels.peer_as }}` or
`{{ $values.A.Value | printf "%.0f" }}`.

## Examples

### BGP session-down rule

```text
phone_alert      = true
pbx_endpoint     = 0001
pbx_title_type   = playback
pbx_title_value  = alert/event/bgp-session-down
pbx_field1_label = alert/field/peer-as
pbx_field1_type  = digits
pbx_field1_value = {{ $labels.peer_as }}
pbx_severity     = critical
```

### Disk-space-low rule

```text
phone_alert      = true
pbx_endpoint     = 0001
pbx_title_type   = playback
pbx_title_value  = alert/event/disk-space-low
pbx_field1_label = alert/field/usage-percent
pbx_field1_type  = number
pbx_field1_value = {{ $values.A.Value | printf "%.0f" }}
pbx_severity     = warning
```

## Verification

Use the Contact Point **Test** function with a test alert containing the Step
5 annotations. The rendered body must contain one `ActionID`, begin with
`Action: Originate`, contain `Async: true`, and be sent as `text/plain`.

The relay should return `202 Accepted`. Asterisk should then show an
`OriginateResponse` and execute the `service-alert-notify` context. `202` confirms AMI
frame delivery, not that the phone answered.

## Troubleshooting

Use the shared [relay webhook troubleshooting table](relay-webhook-test.md#troubleshooting).

## References

- [Grafana webhook notifier configuration](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/configure-webhook-alerting/)
- [Grafana notification grouping](https://grafana.com/docs/grafana/latest/alerting/fundamentals/notifications/group-alert-notifications/)
- [Grafana notification template reference](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/template-notifications/reference/)
