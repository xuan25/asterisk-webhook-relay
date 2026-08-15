# Asterisk PBX Alert Dialplan

This guide installs the Dialplan that turns AMI alert variables into recorded
prompts and spoken dynamic values. It announces one alert per call and supports
up to three optional fields.

## Steps

### Step 1: Choose the language and recipient endpoint

Choose the Asterisk language identifier for the recording files and substitute
it for `<LANGUAGE_ID>` below. Choose a registered recipient endpoint and
substitute its extension for `<recipient-endpoint>` in the verification
commands.

### Step 2: Install the Dialplan

Add this complete configuration to `extensions.conf`, or a dedicated file
included by it. Replace `<LANGUAGE_ID>` before reloading.

```ini
[service-alert-notify]
exten => s,1,NoOp(PBX alert: ${ALERT_ID})
 same => n,Answer()
 same => n,Set(CHANNEL(language)=<LANGUAGE_ID>)

 same => n,Gosub(alert-render,s,1(playback,alert/header))
 same => n,Gosub(alert-render,s,1(playback,alert/severity/${ALERT_SEVERITY}))
 same => n,Gosub(alert-render,s,1(${ALERT_TITLE_TYPE},${ALERT_TITLE_VALUE}))

 same => n,GotoIf($["${ALERT_FIELD1_LABEL}" = ""]?field2)
 same => n,Gosub(alert-render,s,1(playback,${ALERT_FIELD1_LABEL}))
 same => n,Gosub(alert-render,s,1(${ALERT_FIELD1_TYPE},${ALERT_FIELD1_VALUE}))
 same => n,GotoIf($["${ALERT_FIELD1_SUFFIX}" = ""]?field2)
 same => n,Gosub(alert-render,s,1(playback,${ALERT_FIELD1_SUFFIX}))

 same => n(field2),GotoIf($["${ALERT_FIELD2_LABEL}" = ""]?field3)
 same => n,Gosub(alert-render,s,1(playback,${ALERT_FIELD2_LABEL}))
 same => n,Gosub(alert-render,s,1(${ALERT_FIELD2_TYPE},${ALERT_FIELD2_VALUE}))
 same => n,GotoIf($["${ALERT_FIELD2_SUFFIX}" = ""]?field3)
 same => n,Gosub(alert-render,s,1(playback,${ALERT_FIELD2_SUFFIX}))

 same => n(field3),GotoIf($["${ALERT_FIELD3_LABEL}" = ""]?done)
 same => n,Gosub(alert-render,s,1(playback,${ALERT_FIELD3_LABEL}))
 same => n,Gosub(alert-render,s,1(${ALERT_FIELD3_TYPE},${ALERT_FIELD3_VALUE}))
 same => n,GotoIf($["${ALERT_FIELD3_SUFFIX}" = ""]?done)
 same => n,Gosub(alert-render,s,1(playback,${ALERT_FIELD3_SUFFIX}))

 same => n(done),Hangup()

[alert-render]
exten => s,1,NoOp(Alert renderer: type=${ARG1} value=${ARG2})
 same => n,GotoIf($["${ARG2}" = ""]?return)
 same => n,GotoIf($["${ARG1}" = "playback"]?playback)
 same => n,GotoIf($["${ARG1}" = "digits"]?digits)
 same => n,GotoIf($["${ARG1}" = "number"]?number)
 same => n,GotoIf($["${ARG1}" = "alpha"]?alpha)
 same => n,NoOp(Unsupported alert renderer: ${ARG1})
 same => n,Goto(return)
 same => n(playback),Playback(${ARG2})
 same => n,Goto(return)
 same => n(digits),SayDigits(${ARG2})
 same => n,Goto(return)
 same => n(number),SayNumber(${ARG2})
 same => n,Goto(return)
 same => n(alpha),SayAlpha(${ARG2})
 same => n,Goto(return)
 same => n(return),Return()
```

`Gosub` arguments are inside parentheses after the priority: for example,
`Gosub(alert-render,s,1(playback,alert/header))` sets `ARG1=playback` and
`ARG2=alert/header`.

### Step 3: Install the prompt recordings

Place the recordings in the language directory selected in Step 1. Asterisk
uses the file path without its extension in `Playback()`.

```text
/var/lib/asterisk/sounds/<LANGUAGE_ID>/alert/header.wav
/var/lib/asterisk/sounds/<LANGUAGE_ID>/alert/severity/critical.wav
/var/lib/asterisk/sounds/<LANGUAGE_ID>/alert/severity/warning.wav
/var/lib/asterisk/sounds/<LANGUAGE_ID>/alert/event/bgp-session-down.wav
/var/lib/asterisk/sounds/<LANGUAGE_ID>/alert/event/disk-space-low.wav
/var/lib/asterisk/sounds/<LANGUAGE_ID>/alert/field/peer-as.wav
/var/lib/asterisk/sounds/<LANGUAGE_ID>/alert/field/usage-percent.wav
```

The initial renderer accepts these variable types: `playback` for a controlled
recording, `digits` for `SayDigits()`, `number` for `SayNumber()`, and `alpha`
for `SayAlpha()`.

### Step 4: Reload and inspect

Reload the Dialplan, verify both contexts, and confirm the recipient endpoint
has a current contact:

```sh
asterisk -rx 'dialplan reload'
asterisk -rx 'dialplan show service-alert-notify'
asterisk -rx 'dialplan show alert-render'
asterisk -rx 'pjsip show endpoint <recipient-endpoint>'
asterisk -rx 'pjsip show contacts'
```

## Advanced configuration: route AMI callouts by logical destination

The basic configuration originates directly to a PJSIP endpoint. Use this
advanced mode when a phone alert should reuse the PBX number-routing policy:
for example, when the destination can be a local extension, an external number
resolved through ENUM, or a future outbound trunk.

### 1. Add a dedicated AMI ingress context

Create one ingress context for AMI-originated callouts. Replace
`<AMI_INGRESS>` and `<CANONICAL_ROUTING>` with local context
names. The canonical routing context owns the numbering plan and selects the
actual PJSIP endpoint or outbound peer.

```ini
[<AMI_INGRESS>]
exten => _!,1,Set(CALL_SOURCE=ami)
 same => n,Set(CALL_DESTINATION=${EXTEN})
 same => n,Goto(<CANONICAL_ROUTING>,${EXTEN},1)
```

Add site-specific call logging or a hangup handler in this ingress context if
needed. `CALL_SOURCE` and `CALL_DESTINATION` are example channel-variable
names; map them to the local accounting convention if one exists. The final
`Goto()` passes the logical destination to `<CANONICAL_ROUTING>`.
Restrict the extension pattern instead of `_!` when that context does not
safely reject unsupported destinations.

## Examples

### Completed language and endpoint substitutions

For a deployment using language `en` and PJSIP endpoint `0001`, the
placeholders in Steps 2 through 4 become:

```ini
same => n,Set(CHANNEL(language)=en)
```

```text
/var/lib/asterisk/sounds/en/alert/header.wav
/var/lib/asterisk/sounds/en/alert/severity/critical.wav
/var/lib/asterisk/sounds/en/alert/severity/warning.wav
/var/lib/asterisk/sounds/en/alert/event/bgp-session-down.wav
/var/lib/asterisk/sounds/en/alert/event/disk-space-low.wav
/var/lib/asterisk/sounds/en/alert/field/peer-as.wav
/var/lib/asterisk/sounds/en/alert/field/usage-percent.wav
```

```sh
asterisk -rx 'pjsip show endpoint 0001'
```

### Completed AMI ingress context

For an ingress context named `in-call-ami` and a canonical routing context
named `route-call`, the advanced configuration becomes:

```ini
[in-call-ami]
exten => _!,1,Set(PBX_SOURCE=ami)
 same => n,Set(PBX_FROM=${CALLERID(num)})
 same => n,Set(PBX_TO=${EXTEN})
 same => n,Set(PBX_RESULT=UNKNOWN)
 same => n,Log(pbxevent,CALL_IN source=${PBX_SOURCE} from=${PBX_FROM} to=${PBX_TO} uniqueid=${UNIQUEID} linkedid=${CHANNEL(linkedid)})
 same => n,Set(CHANNEL(hangup_handler_push)=call-end,s,1)
 same => n,Goto(route-call,${EXTEN},1)
```

This configuration accepts a channel such as
`Local/1001@in-call-ami/n`; `route-call` must define how logical
destination `1001` is routed. It also assumes that the local Dialplan provides
the `call-end,s,1` hangup handler.

## Verification

Test the Dialplan and endpoint directly before testing Grafana or AMI:

```sh
asterisk -rx 'channel originate PJSIP/<recipient-endpoint> extension s@service-alert-notify'
```

For an end-to-end alert test, inspect Asterisk CLI output while the alert
source calls this Dialplan:

```sh
asterisk -rvvv
core set verbose 5
core set debug 3
```

Expected output includes `service-alert-notify`, `Playback`, a `Say*` application when
a dynamic field is present, and `Hangup`.

## References

- [AMI Originate action](https://docs.asterisk.org/Latest_API/API_Documentation/AMI_Actions/Originate/)
- [SayDigits, SayNumber, SayAlpha and SayPhonetic](https://docs.asterisk.org/Deployment/Basic-PBX-Functionality/Auto-attendant-and-IVR-Menus/SayDigits-SayNumber-SayAlpha-and-SayPhonetic-Applications/)
- [Return application](https://docs.asterisk.org/Latest_API/API_Documentation/Dialplan_Applications/Return)
