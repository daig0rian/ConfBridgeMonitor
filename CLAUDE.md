# ConfBridgeMonitor for Zabbix

Asterisk の ConfBridge にミックスされた音声を、Zabbix ダッシュボード上のウィジェットとしてブラウザで聴取するためのツール。

## プロジェクト概要

運用者・監視者が SIP UA や WebRTC クライアントをインストールすることなく、Zabbix の管理画面を開くだけで Asterisk の会議ブリッジの音声を確認できるようにする Zabbix 7.0+ 用のカスタムウィジェット。

## 動機・背景

- 既存の社内 SIP+RTP 配信システムで、複数台(規模感としては最大40台)の PC 音源を Asterisk ConfBridge でミックスしている運用がある
- ミックス結果を「聴くだけ」のために SIP UA や WebRTC クライアントを配布するのは配布・運用コストが大きい
- 運用者は既に Zabbix ダッシュボードを常用しているので、ここに音声プレーヤーを統合できれば配布障壁がゼロになる
- この用途は特定の社内システム固有ではなく、**Asterisk + Zabbix を併用している現場で広く有用**と考えられるため、汎用 OSS として開発する

## 環境制約(重要・変更しないこと)

これらの制約が技術選定の根拠になっている。Claude Code はこの前提を覆さないこと。

- **Asterisk 環境は DNS 配下にない**(IP アドレスのみでアクセスされる)
- **TLS 証明書は発行できない**(Let's Encrypt も内部 CA も運用上使えない環境を想定)
- したがって、すべての HTTP/WebSocket 通信は**平文(`http://`、`ws://`)** で行う
- **Zabbix も平文 HTTP で運用されている前提**(Mixed Content 回避のため、双方とも HTTP に揃える必要がある)

この制約から、ブラウザの **WebCodecs API は使用できない**(WebCodecs は Secure Context 必須)。代わりに **WASM ベースの Opus デコーダ + Web Audio API** を組み合わせる。Web Audio API と WebAssembly は平文 HTTP でも動作するため、この組み合わせで制約を満たせる。

## 技術スタック

### Asterisk 側

- **Asterisk 22.8.0+ または 23.2.0+**(`chan_websocket` の安定動作のため)
- `chan_websocket` チャンネルドライバ(メディア WebSocket 配信)
- ARI (Asterisk REST Interface)(制御用)
- ConfBridge アプリケーション(既存ミキサーとして利用)

### ブラウザ側

- **Zabbix 7.0+ ウィジェットフレームワーク**(CWidget クラスを JavaScript で継承)
- **WASM Opus デコーダ**(`opus-decoder` パッケージを esbuild で IIFE バンドル化)
- **Web Audio API**(AudioContext + AudioBufferSourceNode によるスケジュール再生)
- **WebSocket × 2 本**(ARI 制御用と Media 用は必ず分離)

### Zabbix 側

- Zabbix 7.0+(7.0、7.2、7.4 を動作対象とする)
- PHP 8.0+
- ウィジェット設定保存は Zabbix 標準のストレージ機構に従う

## アーキテクチャ

```
[ブラウザ]                  [Zabbix サーバ]         [Asterisk :8088]
    │                            │                        │
    │── ① HTTP (Zabbix UI) ─────►│                        │
    │                            │                        │
    │── ② ws:// ARI events ──────┼───────────────────────►│
    │                            │                        │
    │── ③ ws:// Media (Opus) ────┼───────────────────────►│
    │                            │                        │
    │── ④ HTTP (AriProxy) ──────►│── ⑤ HTTP curl REST ───►│
    │      PHP プロキシ経由       │                        │
```

### データフロー

1. Listen ボタンクリックで 2 本の WebSocket を開く(ARI 制御用、Media 用)
2. ARI に `POST /channels/externalMedia` を PHP プロキシ経由で発行（`transport=websocket`、`encapsulation=none`、`format=opus`、`connection_type=server`）
3. レスポンスの `channelvars.MEDIA_WEBSOCKET_CONNECTION_ID` で Media WebSocket URL を構築
4. Media WebSocket 接続がチャンネルを answer し StasisStart をトリガーする
5. `continue` API で `ext-meetme/STARTMEETME/1` に送りチャンネルを ConfBridge に参加させる
6. Media WebSocket に Opus パケット(20ms フレーム)がバイナリで届き始める
7. `opus-decoder` の `decodeFrame()` で PCM に変換し AudioBufferSourceNode でスケジュール再生

## 重要な技術的注意点

### 絶対に守るべきルール

- **ARI 用 WebSocket と Media 用 WebSocket を絶対に共有しないこと**。Asterisk 公式ドキュメントが明示的に "Bad things will happen" と警告している
- **Web Audio API のユーザジェスチャ要求**を満たすため、`AudioContext.resume()` は必ずユーザのクリックハンドラ内で呼ぶ。ウィジェットには明示的な「Listen」ボタンを置き、Auto-connect 機能は実装しない

### ARI 認証

WebSocket URL には `?api_key=user:pass` クエリパラメータで認証情報を渡す（`ws://user:pass@host/...` 形式はブラウザによって不安定）。REST 呼び出しは PHP プロキシ側で `CURLOPT_USERPWD` を使用。

### CORS と WebSocket

- REST (`fetch`) はブラウザが CORS を強制する → PHP AriProxy 経由でプロキシ
- WebSocket は CORS 非適用 → ブラウザから Asterisk へ直接接続。オリジン検査は Asterisk の `allowed_origins` でサーバ側制御

### Asterisk Host の2フィールド構成

WebSocket（ブラウザ発）と REST プロキシ（Zabbix サーバ発）で Asterisk へのアドレスが異なる場合に対応するため、設定フィールドを分離している:
- `asterisk_host` — ブラウザが WebSocket 接続に使うアドレス
- `asterisk_host_server` — Zabbix PHP が curl で使うアドレス（空欄なら `asterisk_host` にフォールバック）

### nginx の `conf` ブロック問題

Zabbix のデフォルト nginx 設定 `location ~ /(conf[^\.]|api\/|include|locale)` がパスに `conf`（直後が `.` 以外）を含む URL をすべてブロックする。モジュールのディレクトリ名・ファイル名に `conf` を含めてはいけない。

- デプロイ先: `/usr/share/zabbix/modules/cbm_monitor/`（`confbridge_monitor` ではない）
- JS ファイル: `cbm-player.js`（`confbridge-player.js` ではない）

### CSP(Content Security Policy)

Zabbix Web サーバに CSP が設定されている場合、`connect-src` ディレクティブに Asterisk のオリジンを追加する必要がある:

```
Content-Security-Policy: connect-src 'self' ws://192.168.x.x:8088;
```

### リソースリーク防止

`start()` が途中で失敗した場合、作成済みの Asterisk チャンネルを確実に DELETE するため、`cbm-player.js` の `start()` メソッド全体を try-catch で囲み、catch で `stop()` を呼んでから re-throw する。

### ジッタバッファ

AudioBufferSourceNode のスケジュール時刻 (`this._nextPlay`) で実装。デフォルト 100ms、設定で調整可能。

## ファイル構造(実際)

```
ConfBridgeMonitor/
├── README.md                  # 英語版 README
├── README.ja.md               # 日本語版 README
├── LICENSE                    # MIT
├── CLAUDE.md                  # このファイル
├── module/                    # Zabbix モジュール本体（デプロイ対象）
│   ├── manifest.json          # id: confbridge_monitor, namespace: ConfBridgeMonitor
│   ├── Widget.php
│   ├── actions/
│   │   ├── WidgetView.php     # CControllerDashboardWidgetView を継承
│   │   └── AriProxy.php      # CController を継承、CSRF 無効、$proxy_input を使用
│   ├── includes/
│   │   └── WidgetForm.php
│   ├── views/
│   │   ├── widget.view.php
│   │   └── widget.edit.php
│   └── assets/
│       ├── js/
│       │   ├── opus-decoder.bundle.js  # esbuild IIFE, --global-name=OpusDecoderLib
│       │   ├── cbm-player.js           # ConfBridgePlayer クラス
│       │   └── class.widget.js        # CWidgetConfBridgeMonitor クラス
│       └── css/
│           └── widget.css
├── docs/
│   ├── asterisk-setup.md      # Asterisk/FreePBX セットアップ（英語）
│   ├── asterisk-setup.ja.md  # Asterisk/FreePBX セットアップ（日本語）
│   ├── zabbix-setup.md       # Zabbix セットアップ（英語）
│   └── zabbix-setup.ja.md   # Zabbix セットアップ（日本語）
└── dev/                       # 開発用 PoC（リリース対象外）
    ├── phase1/                # Python での Opus 受信 PoC
    └── phase2/                # ブラウザ単体 PoC（Zabbix なし）
```

## ウィジェット設定項目(実装済み)

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|-----------|------|
| `asterisk_host` | TextBox (必須) | — | ブラウザ → Asterisk WebSocket |
| `asterisk_host_server` | TextBox (任意) | 空欄 | Zabbix PHP → Asterisk REST（空欄なら asterisk_host を使用）|
| `ari_port` | IntegerBox | 8088 | ARI ポート |
| `ari_user` | TextBox (必須) | admin | ARI ユーザ名 |
| `ari_password` | TextBox | — | ARI パスワード |
| `bridge_id` | TextBox (必須) | 8000 | ConfBridge 名 |
| `buffer_ms` | IntegerBox | 100 | ジッタバッファ (ms) |

## 開発フェーズ

### Phase 1: Asterisk スタンドアロン PoC ✅ 完了

- Python で ConfBridge から Opus フレームを受信・ファイル保存・再生確認
- externalMedia、ARI WebSocket、Media WebSocket の接続順序を確認

### Phase 2: ブラウザ単体 PoC ✅ 完了

- 静的 HTML + JavaScript で `WebSocket → WASM Opus デコーダ → AudioContext` パイプライン構築
- esbuild で opus-decoder を IIFE バンドル化

### Phase 3: Zabbix ウィジェット化 ✅ 完了

- CWidget 拡張として実装、動作確認済み
- PHP AriProxy で CORS 回避
- リソースリーク対策（start() 失敗時の自動 DELETE）

### Phase 4: 公開準備 🔄 進行中

- [x] ディレクトリ構成整理（module/、dev/、docs/）
- [x] README.md / README.ja.md
- [x] LICENSE (MIT)
- [x] docs/asterisk-setup.md / .ja.md
- [x] docs/zabbix-setup.md / .ja.md

## 既知の問題

### StasisStart timeout (10s) — 短時間再接続時

ブラウザを閉じるなどの荒い操作をした直後に再接続すると発生することがある。孤立チャンネルは残らない（`stop()` が DELETE を送る）。通常の Listen → Stop → Listen 操作では発生しない。

## ライセンス方針

**MIT** で確定。WASM Opus デコーダ（`opus-decoder` は MIT）の依存ライセンスと両立。

## アーキテクチャ判断のサマリ(Claude Code への補足)

1. **なぜ MediaMTX/HLS ではなく Asterisk + chan_websocket か** — ConfBridge のミキシングは Asterisk の強みであり、MediaMTX はメディアルータでありミキサーではない。HLS だと数秒の遅延が発生するが、本プロジェクトはサブ秒の遅延を狙う
2. **なぜ WebRTC ではなく WebSocket + WASM Opus か** — WebRTC は受信側に SIP/WebRTC スタックが必要で、ブラウザ単体では SIP.js などの実装が必要になる。chan_websocket + WASM Opus なら受信実装が大幅に薄くなる
3. **なぜ WebCodecs ではなく WASM Opus デコーダか** — WebCodecs API は Secure Context(HTTPS)を必須とするが、本プロジェクトは平文 HTTP 環境を前提とするため使用不可
4. **なぜ Zabbix ウィジェットか** — 運用者は既に Zabbix ダッシュボードを常用しており、配布障壁がゼロになる。また Zabbix と Asterisk のセキュリティコンテキスト(両方 HTTP)が揃うため、Mixed Content 問題が発生しない
5. **なぜ WebSocket を PHP でプロキシしないか** — PHP-FPM はリクエスト・レスポンス前提で、長期接続がワーカーを占有する。Media WS は 20ms ごとにバイナリフレームが届くため PHP 中継は遅延・品質劣化につながる。WebSocket は CORS 非適用のためブラウザ直接接続で問題ない

## 参考ドキュメント

- Asterisk `chan_websocket`: https://docs.asterisk.org/Configuration/Channel-Drivers/WebSocket/
- Asterisk External Media and ARI: https://docs.asterisk.org/Development/Reference-Information/Asterisk-Framework-and-API-Examples/External-Media-and-ARI/
- Asterisk WebSocket examples: https://github.com/asterisk/asterisk-websocket-examples
- Zabbix Widget Tutorial: https://www.zabbix.com/documentation/current/en/devel/modules/tutorials/widget
- Zabbix manifest.json Reference: https://www.zabbix.com/documentation/7.0/en/devel/modules/file_structure/manifest
- `opus-decoder` (wasm-audio-decoders): https://github.com/eshaz/wasm-audio-decoders
- WebCodecs Secure Context 制約(回避理由): https://developer.mozilla.org/en-US/docs/Web/API/AudioDecoder
