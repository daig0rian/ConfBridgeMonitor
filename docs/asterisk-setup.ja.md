# Asterisk / FreePBX セットアップガイド

> 🌐 [English version](asterisk-setup.md)

検証環境: FreePBX 17 + Asterisk 22.8.2 (x86_64 Linux)

## 前提条件

| モジュール | 確認コマンド | 期待値 |
|---|---|---|
| `chan_websocket.so` | `asterisk -rx 'module show like chan_websocket'` | Running |
| `res_ari.so` | `asterisk -rx 'module show like res_ari'` | Running |

Asterisk 22.8.0+ では両モジュールは標準でビルド済み・ロード済み。

---

## 1. HTTP サーバ設定

### 目的
ARI の REST API と WebSocket を外部(ブラウザ、Python クライアント)から到達可能にする。

### FreePBX GUI での手順
**Settings > Advanced Settings > Asterisk Builtin mini-HTTP server**

| 項目 | 変更前 | 変更後 |
|---|---|---|
| HTTP Bind Address | `127.0.0.1` | `0.0.0.0` |
| HTTP Bind Port | `8088` | `8088`(変更不要) |

Submit → Apply Changes を実行する。

### 確認
```bash
ss -tlnp | grep 8088
# 期待値: 0.0.0.0:8088 で LISTEN
```

### 生成されるファイル
`/etc/asterisk/http_additional.conf` に反映される(自動生成・直接編集禁止)。

---

## 2. WebSocket トランスポートの有効化 (chan_pjsip)

### 目的
Asterisk 内蔵 HTTP サーバが WebSocket 接続を受け付けられるようにする。この設定がないと `chan_websocket` がブラウザからの WebSocket 接続を受け付けられない。

### FreePBX GUI での手順
**Settings > Asterisk SIP Settings > SIP Settings [chan_pjsip]**

**Transport** セクションまでスクロールし、`ws` 行（0.0.0.0 / All）を見つけて有効化する:

| トランスポート | アドレス | プロトコル | 有効 (変更前) | 有効 (変更後) |
|--------------|---------|-----------|-------------|-------------|
| `ws` | `0.0.0.0` | All | `No` | `Yes` |

Submit → Apply Changes を実行する。

### 確認
```bash
sudo asterisk -rx 'pjsip show transports'
# 期待値: ws トランスポートの行が State: Available で表示される
```

---

## 3. ARI (Asterisk REST Interface) 設定

### 目的
ARI を有効化し、外部オリジンからの WebSocket 接続を許可する。

### FreePBX GUI での手順
**Settings > Advanced Settings > Asterisk REST Interface**

| 項目 | 変更前 | 変更後 |
|---|---|---|
| Enable the Asterisk REST Interface | `No` | `Yes` |
| Allowed Origins | `localhost:8088` | `192.168.x.x:80` |
| Pretty Print JSON Responses | `No` | `No`(変更不要) |
| Web Socket Write Timeout | `100` | `100`(変更不要) |

`192.168.x.x` は **ブラウザから見た** Zabbix サーバの IP アドレス（またはホスト名）に置き換えること。Zabbix が標準以外のポートで動いている場合はポートも含める（例: `192.168.x.x:8080`）。複数オリジンはカンマ区切りで列挙できる。

Submit → Apply Changes を実行する。

### 確認
```bash
sudo asterisk -rx 'ari show status'
# 期待値:
# Enabled: Yes
# Allowed Origins: 192.168.x.x:80
```

### 生成されるファイル
`/etc/asterisk/ari_general_additional.conf` に反映される(自動生成・直接編集禁止)。

### Allowed Origins を絞る理由

`allowed_origins` はブラウザが WebSocket 接続時に送る `Origin` ヘッダと照合される。Zabbix サーバのオリジンのみを許可することで、Zabbix ページを開いているブラウザ以外からの ARI WebSocket 接続を Asterisk が拒否できる。

なお、PHP プロキシ（Zabbix サーバ → Asterisk の curl）はサーバ間通信のため `Origin` ヘッダを送らず、この設定の影響を受けない。

---

## 4. ARI ユーザ設定

### 目的
ブラウザウィジェットが ARI に認証するためのユーザを作成する。

### FreePBX GUI での手順
**Settings > Asterisk REST Interface Users > Add User**

| 項目 | 値 |
|---|---|
| User Name | 任意(例: `ari_user`) |
| User Password | 任意 |
| Password Type | `Plain Text` |
| Read Only | `No` ※ POST 操作が必要なため |

Submit → Apply Changes を実行する。

> **重要**: Read Only を Yes にすると `POST /ari/channels/externalMedia` などの
> 書き込み操作が拒否される。必ず No に設定すること。

### 生成されるファイル
`/etc/asterisk/ari_additional.conf`

```ini
[ari_user]
type=user
password=yourpassword
password_format=plain
read_only=no
```

### 接続 URL フォーマット
```
# ARI 制御用 WebSocket (ブラウザから直接接続)
ws://192.168.x.x:8088/ari/events?api_key=user:pass&app=confbridge_monitor&subscribeAll=true

# ARI REST API (Zabbix PHP プロキシ経由)
http://192.168.x.x:8088/ari/
```

---

## 5. ConfBridge 確認

### 目的
音声を受信する対象の ConfBridge が存在することを確認する。

### 確認コマンド
```bash
sudo asterisk -rx 'confbridge list'
# 例:
# Conference Bridge Name           Users  Marked Locked Muted
# 8000                                  1      0 No     No
```

### FreePBX での ConfBridge 作成
**Admin > Conference Rooms** で会議室を作成すると、対応する ConfBridge が自動作成される。

---

## 6. 設定変更が不要な項目

以下は Asterisk 22.8.x + FreePBX 17 の標準状態で動作確認済み:

- `chan_websocket.so` — ロード済み・追加設定不要
- `res_ari.so` および関連モジュール群 — ロード済み・追加設定不要
- TLS(ポート 8089) — 本プロジェクトは平文 HTTP のみ使用するため設定不要

---

## 7. FreePBX カスタム設定ファイルについて

FreePBX が生成するファイル(`*_additional.conf`)は Apply Changes のたびに上書きされる。
GUI で設定できない項目を追加する場合は `*_custom.conf` を使用すること:

| カスタムファイル | 用途 |
|---|---|
| `/etc/asterisk/http_custom.conf` | HTTP 追加設定 |
| `/etc/asterisk/ari_general_custom.conf` | ARI [general] 追加設定 |
| `/etc/asterisk/ari_additional_custom.conf` | ARI ユーザ追加 |

これらのファイルは FreePBX に上書きされない。

---

## 設定完了チェックリスト

- [ ] `ss -tlnp | grep 8088` で `0.0.0.0:8088` がリスン中
- [ ] `sudo asterisk -rx 'pjsip show transports'` で `ws` トランスポートが `State: Available` で表示される
- [ ] `sudo asterisk -rx 'ari show status'` で `Enabled: Yes` と `Allowed Origins: 192.168.x.x:80` が確認できる
- [ ] ARI ユーザが `read_only=no` で作成済み
- [ ] `confbridge list` でモニタ対象の Bridge が確認できる
- [ ] `curl http://192.168.x.x:8088/ari/asterisk/info` でレスポンス確認
