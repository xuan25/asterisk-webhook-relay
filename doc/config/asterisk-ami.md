# Asterisk AMI Configuration and Test Guide

This guide configures the Asterisk Manager Interface (AMI) listener and the
restricted `asterisk-webhook-relay` AMI user. The relay connects to AMI over
persistent TCP on port `5038` and submits asynchronous `Originate` actions.

## Steps

### Step 1: Generate the AMI password

Generate an AMI password and retain the printed value for both
`manager.conf` and the relay `.env` file:

```sh
ami_password="$(openssl rand -base64 36 | tr -d '\n' | tr '+/' '-_')"
printf 'RELAY_AMI_PASSWORD=%s\n' "$ami_password"
```

### Step 2: Configure `manager.conf`

Edit `/etc/asterisk/manager.conf`, or an included file that Asterisk loads.
Add the following configuration, replacing every `<...>` placeholder:

```ini
[general]
enabled = yes
port = 5038
bindaddr = <asterisk-listen-address>

[asterisk-webhook-relay]
secret = <generated-ami-password>
deny = <deny-all-for-address-family>
permit = <relay-source-network>
read = call
write = originate
```

Set `bindaddr` to the Asterisk address used by the relay: an IPv4 address (or
`0.0.0.0`), an IPv6 address, or `::` for a dual-stack attempt. The relay user
must have one `deny`/`permit` pair for each address family it uses:

- IPv4: `deny = 0.0.0.0/0.0.0.0`, followed by `permit = <relay-ipv4-network>`.
- IPv6: `deny = ::/0`, followed by `permit = <relay-ipv6-prefix>`.

`secret` is the value generated in Step 1. `read = call` allows the
call-related events used to correlate asynchronous originates; `write =
originate` allows only the action submitted by this relay. Do not put these
user fields in `[general]`, and do not use `read = all` or `write = all`.

### Step 3: Reload and inspect AMI

Reload the manager module and confirm the effective listener and user:

```sh
asterisk -rx 'manager reload'
asterisk -rx 'manager show settings'
asterisk -rx 'manager show users'
ss -ltnp | grep ':5038'
```

`manager show settings` should report `Manager (AMI): Yes` and the configured
TCP bind address. If Asterisk runs in Docker, run the same commands in its
container.

## Examples

### IPv4-only listener

```ini
[general]
enabled = yes
port = 5038
bindaddr = 0.0.0.0

[asterisk-webhook-relay]
secret = REPLACE_WITH_GENERATED_AMI_PASSWORD
deny = 0.0.0.0/0.0.0.0
permit = 172.18.0.0/255.255.0.0
read = call
write = originate
```

### IPv6-only listener

```ini
[general]
enabled = yes
port = 5038
bindaddr = 2001:db8:100::10

[asterisk-webhook-relay]
secret = REPLACE_WITH_GENERATED_AMI_PASSWORD
deny = ::/0
permit = 2001:db8:100:20::/64
read = call
write = originate
```

### Dual-stack listener

```ini
[general]
enabled = yes
port = 5038
bindaddr = ::

[asterisk-webhook-relay]
secret = REPLACE_WITH_GENERATED_AMI_PASSWORD
deny = 0.0.0.0/0.0.0.0
permit = 172.18.0.0/255.255.0.0
deny = ::/0
permit = 2001:db8:100:20::/64
read = call
write = originate
```

On Linux, this relies on IPv4-mapped connections being accepted by the IPv6
socket. Check `sysctl net.ipv6.bindv6only`: `0` usually accepts both families;
`1` makes the listener IPv6-only.

## Verification

### Test TCP reachability

Run from the relay host or container:

```sh
nc -vz <asterisk-ipv4-or-hostname> 5038
nc -vz <asterisk-ipv6-address> 5038
```

For Compose services on the same network, set `RELAY_AMI_HOST` to the
Asterisk service name, not `localhost`.

### Test AMI login

Connect from the relay network:

```sh
nc <asterisk-address> 5038
```

Paste this block, including the final empty line:

```text
Action: Login
ActionID: manual-login-001
Username: asterisk-webhook-relay
Secret: REPLACE_WITH_GENERATED_AMI_PASSWORD
Events: on

```

Expected result:

```text
Response: Success
ActionID: manual-login-001
Message: Authentication accepted
```

Then test an allowed action:

```text
Action: Originate
ActionID: manual-originate-001
Channel: PJSIP/<test-endpoint>
Context: <existing-test-context>
Exten: <existing-test-extension>
Priority: 1
Timeout: 30000
Async: true

```

With `Async: true`, AMI first acknowledges the action and later emits an
`OriginateResponse` carrying the same `ActionID`.

## Troubleshooting

| Symptom | Checks |
| --- | --- |
| AMI is bound to an unexpected address | Check every included `manager.conf` file; use `manager show settings` as the effective configuration. |
| Login fails | Confirm username, secret, relay source ACL, and that `manager reload` completed. |
| IPv4 works but IPv6 fails | Check `bindaddr`, ACLs, firewall rules, container IPv6 networking, and `net.ipv6.bindv6only`. |
| IPv6 works but IPv4 fails with `bindaddr = ::` | Check `net.ipv6.bindv6only`; use an IPv4 path or a dual-stack proxy when it is `1`. |

## References

- [Asterisk Manager TCP/IP API](https://docs.asterisk.org/Configuration/Interfaces/Asterisk-Manager-Interface-AMI/The-Asterisk-Manager-TCP-IP-API/)
- [AMI v2 configuration reference](https://docs.asterisk.org/Configuration/Interfaces/Asterisk-Manager-Interface-AMI/AMI-v2-Specification/)
- [AMI Originate action](https://docs.asterisk.org/Latest_API/API_Documentation/AMI_Actions/Originate/)
