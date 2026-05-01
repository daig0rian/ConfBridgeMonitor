# Asterisk / FreePBX Setup Guide

> 🌐 [日本語版はこちら](asterisk-setup.ja.md)

Verified environment: FreePBX 17 + Asterisk 22.8.2 (x86_64 Linux)

## Prerequisites

| Module | Check command | Expected |
|--------|---------------|----------|
| `chan_websocket.so` | `asterisk -rx 'module show like chan_websocket'` | Running |
| `res_ari.so` | `asterisk -rx 'module show like res_ari'` | Running |

Both modules are built and loaded by default on Asterisk 22.8.0+.

---

## 1. HTTP Server Configuration

### Purpose
Make the ARI REST API and WebSocket accessible from external clients (browser, Python).

### FreePBX GUI steps
**Settings > Advanced Settings > Asterisk Builtin mini-HTTP server**

| Setting | Before | After |
|---------|--------|-------|
| HTTP Bind Address | `127.0.0.1` | `0.0.0.0` |
| HTTP Bind Port | `8088` | `8088` (no change) |

Click **Submit** then **Apply Changes**.

### Verify
```bash
ss -tlnp | grep 8088
# Expected: listening on 0.0.0.0:8088
```

### Generated file
Settings are written to `/etc/asterisk/http_additional.conf` (auto-generated — do not edit directly).

---

## 2. Enable WebSocket Transport (chan_pjsip)

### Purpose
Allow Asterisk's built-in HTTP server to accept WebSocket connections. Without this, `chan_websocket` cannot receive inbound WebSocket connections from the browser.

### FreePBX GUI steps
**Settings > Asterisk SIP Settings > SIP Settings [chan_pjsip]**

Scroll down to the **Transport** section and find the `ws` row (0.0.0.0 / All):

| Transport | Address | Protocol | Enabled (Before) | Enabled (After) |
|-----------|---------|----------|------------------|-----------------|
| `ws` | `0.0.0.0` | All | `No` | `Yes` |

Click **Submit** then **Apply Changes**.

### Verify
```bash
sudo asterisk -rx 'pjsip show transports'
# Expected: a row showing transport "ws" with State: Available
```

---

## 3. ARI (Asterisk REST Interface) Configuration

### Purpose
Enable ARI and allow WebSocket connections from external origins.

### FreePBX GUI steps
**Settings > Advanced Settings > Asterisk REST Interface**

| Setting | Before | After |
|---------|--------|-------|
| Enable the Asterisk REST Interface | `No` | `Yes` |
| Allowed Origins | `localhost:8088` | `192.168.x.x:80` |
| Pretty Print JSON Responses | `No` | `No` (no change) |
| Web Socket Write Timeout | `100` | `100` (no change) |

Replace `192.168.x.x` with the IP address (or hostname) of your Zabbix server **as seen by the browser**. If Zabbix is on a non-standard port, append it (e.g. `192.168.x.x:8080`). Multiple origins can be separated by commas.

Click **Submit** then **Apply Changes**.

### Verify
```bash
sudo asterisk -rx 'ari show status'
# Expected:
# Enabled: Yes
# Allowed Origins: 192.168.x.x:80
```

### Generated file
Settings are written to `/etc/asterisk/ari_general_additional.conf` (auto-generated — do not edit directly).

### Why restrict Allowed Origins

`allowed_origins` is checked against the `Origin` header that the browser sends when opening a WebSocket connection to Asterisk. Restricting it to the Zabbix server's origin means only browsers loading the Zabbix page can establish a WebSocket to ARI — any other origin is rejected by Asterisk.

Note: server-side PHP proxy calls (Zabbix → Asterisk via curl) do not send an `Origin` header and are not affected by this setting.

---

## 4. ARI User Configuration

### Purpose
Create a user account for the browser widget to authenticate with ARI.

### FreePBX GUI steps
**Settings > Asterisk REST Interface Users > Add User**

| Field | Value |
|-------|-------|
| User Name | Any (e.g. `ari_user`) |
| User Password | Any |
| Password Type | `Plain Text` |
| Read Only | `No` — write access is required for POST operations |

Click **Submit** then **Apply Changes**.

> **Important**: Setting Read Only to Yes will cause `POST /ari/channels/externalMedia`
> and other write operations to be rejected. Always set to No.

### Generated file
`/etc/asterisk/ari_additional.conf`

```ini
[ari_user]
type=user
password=yourpassword
password_format=plain
read_only=no
```

### Connection URL formats
```
# ARI control WebSocket (direct from browser)
ws://192.168.x.x:8088/ari/events?api_key=user:pass&app=confbridge_monitor&subscribeAll=true

# ARI REST API (via Zabbix PHP proxy)
http://192.168.x.x:8088/ari/
```

---

## 5. Verify ConfBridge

### Purpose
Confirm the target ConfBridge exists and is active.

### Check command
```bash
sudo asterisk -rx 'confbridge list'
# Example output:
# Conference Bridge Name           Users  Marked Locked Muted
# 8000                                  1      0 No     No
```

### Creating a ConfBridge in FreePBX
Go to **Admin > Conference Rooms** and create a conference room. The corresponding ConfBridge is created automatically.

---

## 6. Items that require no changes

The following work out of the box with Asterisk 22.8.x + FreePBX 17:

- `chan_websocket.so` — loaded, no extra configuration needed
- `res_ari.so` and related modules — loaded, no extra configuration needed
- TLS (port 8089) — not used; this project uses plain HTTP only

---

## 7. FreePBX custom configuration files

Files generated by FreePBX (`*_additional.conf`) are overwritten on every Apply Changes. To add settings not exposed in the GUI, use the corresponding `*_custom.conf` file:

| Custom file | Purpose |
|-------------|---------|
| `/etc/asterisk/http_custom.conf` | Additional HTTP settings |
| `/etc/asterisk/ari_general_custom.conf` | Additional ARI [general] settings |
| `/etc/asterisk/ari_additional_custom.conf` | Additional ARI users |

These files are not overwritten by FreePBX.

---

## Setup checklist

- [ ] `ss -tlnp | grep 8088` shows `0.0.0.0:8088` listening
- [ ] `sudo asterisk -rx 'pjsip show transports'` shows `ws` transport with State: Available
- [ ] `sudo asterisk -rx 'ari show status'` shows `Enabled: Yes` and `Allowed Origins: 192.168.x.x:80`
- [ ] ARI user created with `read_only=no`
- [ ] Target bridge visible in `confbridge list`
- [ ] `curl http://192.168.x.x:8088/ari/asterisk/info` returns a JSON response
