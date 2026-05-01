# Zabbix Setup Guide

> 🌐 [日本語版はこちら](zabbix-setup.ja.md)

Verified environment: Zabbix 7.0 (nginx + PHP 8.0)

---

## 1. Module Installation

### Copy files

```bash
cp -r module/ /usr/share/zabbix/modules/cbm_monitor
```

> **Directory name note**: Zabbix's default nginx config blocks any URL path containing `conf` followed by a non-dot character. The name `cbm_monitor` avoids this restriction. For the same reason, no file inside the module contains `conf` in its name.

### Register in Zabbix

1. Go to **Administration → General → Modules**
2. Click **Scan directory**
3. Find **ConfBridge Monitor** and click **Enable**

---

## 2. Content Security Policy (CSP)

If your Zabbix web server sets a CSP header, the browser will block WebSocket connections to Asterisk unless you add the Asterisk origin to `connect-src`.

### nginx

Edit the `add_header Content-Security-Policy` line in `/etc/nginx/conf.d/zabbix.conf` (or wherever it is set):

```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-eval'; connect-src 'self' ws://192.168.x.x:8088; ...";
```

Then reload:

```bash
nginx -t && systemctl reload nginx
```

### Apache

Add the same `connect-src` directive to your `Header set Content-Security-Policy` line in the VirtualHost config or `.htaccess`.

### No CSP configured

No change needed.

---

## 3. Database registration check

When the module is enabled, Zabbix writes a record to the `module` table:

| Column | Value |
|--------|-------|
| `id` | `confbridge_monitor` |
| `relative_path` | `modules/cbm_monitor` |
| `status` | `1` (enabled) |

If you move or rename the module directory manually, `relative_path` may become stale. Fix by disabling and re-enabling the module in the UI, or update the DB directly:

```sql
UPDATE module SET relative_path='modules/cbm_monitor' WHERE id='confbridge_monitor';
```

---

## 4. Widget configuration fields

| Field | Description | Default |
|-------|-------------|---------|
| Asterisk Host (browser) | Address the browser uses for WebSocket connections to Asterisk | `10.0.0.1` |
| Asterisk Host (server-side proxy) | Address the Zabbix server's PHP uses for REST calls to Asterisk. Leave blank if the same as the browser-facing address | *(same as browser)* |
| ARI Port | ARI HTTP port | `8088` |
| ARI Username | ARI username | `admin` |
| ARI Password | ARI password | — |
| Bridge ID | Name of the target ConfBridge (e.g. `8000`) | `8000` |
| Buffer (ms) | Jitter buffer size. 50–100 ms for LAN, 200 ms for WAN | `100` |

### About the two Asterisk Host fields

There are two separate network paths from the widget to Asterisk:

- **WebSocket (ARI events + Media)**: the browser connects directly to Asterisk — no proxy possible
- **REST (POST/DELETE)**: routed through the Zabbix server's PHP to avoid browser CORS restrictions

If NAT or a reverse proxy sits between the browser and Asterisk, the address the browser uses may differ from the address the Zabbix server uses. Set each field to the appropriate address for its network path. In a flat LAN where all three parties share the same subnet, both addresses are identical — leave **Asterisk Host (server-side proxy)** blank.

---

## 5. Troubleshooting

### Widget placement fails and returns to the settings dialog

JS assets are returning 404. Open the browser developer tools (F12) and check the Network tab.

- A path containing `conf` is being blocked by nginx → verify the module directory is named `cbm_monitor`
- The DB `relative_path` does not match the actual directory name → see section 3

### Error: ARI POST failed (500)

The PHP AriProxy action is failing. Check the Zabbix PHP error log:

```bash
tail -f /var/log/php-fpm/www-error.log
# or
tail -f /var/log/nginx/error.log
```

Common causes:
- **Asterisk Host (server-side proxy)** is unreachable from the Zabbix server
- ARI credentials are incorrect
- `disableCsrfValidation()` is missing (if you modified the module)

### Error: WebSocket connection failed

- Confirm Asterisk HTTP is listening on `0.0.0.0:8088`: `ss -tlnp | grep 8088`
- Confirm `allowed_origins` includes the Zabbix server's origin (or is `*`)
- Confirm CSP `connect-src` includes `ws://asterisk-host:8088`

### Error: StasisStart timeout (10s)

Occurs when a reconnect is attempted before Asterisk has finished processing the previous disconnect (e.g. immediately after a force-close of the browser). Wait a few seconds and press Listen again.

### Audio not playing (no error shown)

- Confirm the Bridge ID matches the actual ConfBridge name: `asterisk -rx 'confbridge list'`
- Check browser audio output permissions for the Zabbix site
- Reload the page and try again
