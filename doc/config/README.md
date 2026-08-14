# Configuration Guide Index

`doc/config/` contains deployment and operator runbooks. These documents say
what to configure in Grafana, Asterisk, and the relay, and how to verify the
result.

## Steps

Use the configuration documents in this order:

1. [Asterisk AMI](asterisk-ami.md): enable AMI, create the restricted relay
   user, and verify the AMI listener and credentials.
2. [Dialplan](dialplan.md): install the alert renderer and voice prompts; test
   a call directly from Asterisk. It also documents the optional Local-channel
   mode that routes logical destinations through the existing PBX dialplan.
3. [Relay Webhook direct test](relay-webhook-test.md): send a signed curl
   request through the relay and verify the AMI/Dialplan call path.
4. [Grafana Webhook](grafana-webhook.md): create the template, Contact Point,
   and policy; then add PBX labels and annotations when creating alert rules.

## Examples

- [Voice prompt recording manifest](prompts-alert-voice.csv) lists the prompt
  names and English recording text used by the Dialplan.
- Every configuration guide uses placeholders such as `<LANGUAGE_ID>`,
  `<recipient-endpoint>`, and `REPLACE_WITH_*`. Replace them with
  deployment-specific values before applying a configuration.
