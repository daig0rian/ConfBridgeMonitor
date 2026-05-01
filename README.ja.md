# ConfBridge Monitor — Zabbix ウィジェット

> 🌐 [English version](README.md)

Asterisk ConfBridge の音声を Zabbix ダッシュボード上でブラウザ再生できるカスタムウィジェット。SIP クライアント・WebRTC スタック・追加ソフトウェアは不要。

![ConfBridge Monitor ウィジェット](docs/screenshot.png)

## 概要

Zabbix ダッシュボードを日常的に使用している運用チームが、追加のクライアントソフトウェアをインストールすることなく、Asterisk の会議ブリッジ音声をモニタリングできます。ウィジェットは WebSocket で Asterisk に接続し、WebAssembly ベースの Opus デコーダで音声をデコードして Web Audio API で再生します。すべて Zabbix ダッシュボードのページ内で完結します。

**主な設計方針:**

- 平文 HTTP で動作（TLS 不要）— WebCodecs API は Secure Context が必須なため意図的に回避
- Asterisk の要件に従い ARI 制御用と Media 用の WebSocket を必ず分離
- REST 呼び出しは CORS 制限を回避するため PHP アクション経由でプロキシ
- WebSocket 接続はブラウザから Asterisk へ直接（CORS 非適用、Asterisk の `allowed_origins` でサーバ側制御）

## 動作要件

| コンポーネント | バージョン |
|---------------|-----------|
| Zabbix | 7.0、7.2、または 7.4 |
| Asterisk | 22.8.0+ または 23.2.0+ |
| ブラウザ | モダンブラウザ（Chrome、Firefox、Edge） |

> Asterisk は `chan_websocket` と `res_ari` モジュールがロードされている必要があります。  
> Zabbix と Asterisk の両方が平文 HTTP で提供されている必要があります（Mixed Content の制約）。

## インストール

### 1. モジュールを Zabbix に配置

```bash
cp -r module/ /usr/share/zabbix/modules/cbm_monitor
```

> ディレクトリ名に `conf`（直後が `.` 以外）を含めてはいけません。Zabbix のデフォルト nginx 設定がそのようなパスをブロックします。`cbm_monitor` はこの制限を回避した名前です。

### 2. Zabbix に登録

1. **Administration → General → Modules** を開く
2. **Scan directory** をクリック
3. **ConfBridge Monitor** を見つけて **Enable** をクリック

### 3. Asterisk を設定

ステップごとの手順は [docs/asterisk-setup.ja.md](docs/asterisk-setup.ja.md)（FreePBX GUI 対応）を参照してください。

必要な設定:

- ARI を有効化（`enabled = yes`）
- HTTP サーバを `0.0.0.0:8088` でリスン
- `read_only = no` の ARI ユーザを作成
- `allowed_origins` に Zabbix サーバのオリジンを含める（または内部利用なら `*`）

### 4. ダッシュボードにウィジェットを追加

1. ダッシュボードを編集 → **Add widget** → **ConfBridge Monitor** を選択
2. 設定を入力:
   - **Asterisk Host (from Browser)** — ブラウザが WebSocket 接続に使う Asterisk の IP アドレス
   - **Asterisk Host (from Zabbix)** — Zabbix サーバが REST 呼び出しに使う Asterisk の IP アドレス。同じアドレスの場合は空欄
   - **ARI Port** — デフォルト `8088`
   - **ARI Username / Password** — ARI ユーザの認証情報
   - **Bridge ID** — ConfBridge 名（例: `8000`）
   - **Buffer (ms)** — ジッタバッファサイズ。LAN では `100` が目安
3. 保存して **▶ Listen** をクリック

## Content Security Policy

Zabbix Web サーバに CSP ヘッダが設定されている場合は、`connect-src` に Asterisk のオリジンを追加してください:

```
Content-Security-Policy: connect-src 'self' ws://192.168.x.x:8088;
```

詳細は [docs/zabbix-setup.ja.md](docs/zabbix-setup.ja.md) を参照してください。

## 通信経路

3 者（ブラウザ、Zabbix サーバ、Asterisk サーバ）が関与します。

```
[ブラウザ]               [Zabbix サーバ]          [Asterisk サーバ :8088]
    │                         │                           │
    │── ① HTTP (Zabbix UI) ──►│                           │
    │                         │                           │
    │── ② ws:// ARI events ───┼──────────────────────────►│
    │                         │                           │
    │── ③ ws:// Media (Opus) ─┼──────────────────────────►│
    │                         │                           │
    │── ④ HTTP (AriProxy) ───►│── ⑤ HTTP curl (REST) ───►│
    │      PHP プロキシ経由    │                           │
```

| 経路 | 送信元 | 宛先 | 目的 |
|------|--------|------|------|
| ① | ブラウザ | Zabbix サーバ :80 | Zabbix ダッシュボード（既存の要件） |
| ②③ | ブラウザ | Asterisk :8088 | WebSocket（直接接続、CORS 非適用） |
| ④⑤ | ブラウザ → Zabbix PHP → Asterisk | — | REST 呼び出し（CORS 回避のため PHP 経由） |

WebSocket はブラウザから Asterisk へ**直接**接続します。REST は CORS 制限により PHP プロキシ経由です。

**Asterisk Host (from Browser)** と **Asterisk Host (from Zabbix)** が異なる値になるのは、NAT やリバースプロキシでブラウザと Zabbix サーバから見た Asterisk のアドレスが異なる場合です。

### 必要な通信経路

| 接続 | ポート | プロトコル |
|------|--------|-----------|
| ブラウザ → Zabbix サーバ | 80 | HTTP |
| ブラウザ → Asterisk サーバ | 8088 | WebSocket (ws://) |
| Zabbix サーバ → Asterisk サーバ | 8088 | HTTP |

## 既知の制限事項

- **StasisStart タイムアウト** — ブラウザを強制終了した直後に再接続しようとすると `StasisStart timeout (10s)` エラーが発生することがある。孤立チャンネルは自動的に削除される。数秒待ってから Listen を押し直す。
- **平文 HTTP のみ** — HTTPS に移行する場合は Asterisk 側も TLS（`wss://`）対応が必要。

## ライセンス

MIT — [LICENSE](LICENSE) を参照。

依存ライブラリ:

- [`opus-decoder`](https://github.com/eshaz/wasm-audio-decoders)（MIT）— WASM Opus デコーダ
