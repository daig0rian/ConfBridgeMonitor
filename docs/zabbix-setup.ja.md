# Zabbix セットアップガイド

> 🌐 [English version](zabbix-setup.md)

検証環境: Zabbix 7.0 (nginx + PHP 8.0)

---

## 1. モジュールのインストール

### ファイルの配置

```bash
cp -r module/ /usr/share/zabbix/modules/cbm_monitor
```

> **ディレクトリ名の注意**: Zabbix の nginx デフォルト設定はパスに `conf`（直後が `.` 以外）を含む URL をブロックする。`cbm_monitor` という名前はこの制限を回避している。同様の理由でモジュール内のファイル名にも `conf` を含めていない。

### Zabbix 管理画面での登録

1. **Administration → General → Modules** を開く
2. **Scan directory** をクリック
3. **ConfBridge Monitor** が一覧に表示されたら **Enable** をクリック

---

## 2. Content Security Policy (CSP) の調整

Zabbix Web サーバに CSP が設定されている場合、ブラウザから Asterisk への WebSocket 接続がブロックされる。

### nginx の場合

`/etc/nginx/conf.d/zabbix.conf`（または該当の設定ファイル）の `add_header Content-Security-Policy` 行を編集し、`connect-src` に Asterisk のオリジンを追加する:

```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-eval'; connect-src 'self' ws://192.168.x.x:8088; ...";
```

変更後:

```bash
nginx -t && systemctl reload nginx
```

### Apache の場合

`.htaccess` または VirtualHost 設定の `Header set Content-Security-Policy` に同様に追加する。

### CSP が設定されていない場合

特に変更は不要。

---

## 3. データベース登録の確認

モジュールを有効化すると Zabbix DB の `module` テーブルに以下のように記録される:

| カラム | 値 |
|--------|---|
| `id` | `confbridge_monitor` |
| `relative_path` | `modules/cbm_monitor` |
| `status` | `1`（有効） |

モジュールを手動で移動・リネームした場合は `relative_path` がずれることがある。その場合は管理画面で一度 Disable → Enable し直すか、DB を直接修正する:

```sql
UPDATE module SET relative_path='modules/cbm_monitor' WHERE id='confbridge_monitor';
```

---

## 4. ウィジェットの設定項目

| 項目 | 説明 | デフォルト |
|------|------|-----------|
| Asterisk Host (from Browser) | ブラウザが WebSocket 接続に使う Asterisk の IP アドレス | `10.0.0.1` |
| Asterisk Host (from Zabbix) | Zabbix サーバの PHP が REST 呼び出しに使う Asterisk の IP アドレス。ブラウザから見たアドレスと同じ場合は空欄でよい | *(from Browser と同じ)* |
| ARI Port | ARI HTTP ポート番号 | `8088` |
| ARI Username | Asterisk REST Interface に登録したユーザ名 | `MY_ARI_USERNAME` |
| ARI Password | Asterisk REST Interface に登録したパスワード | `MY_ARI_PASSWORD` |
| Bridge ID | 監視対象 ConfBridge 名 (例: `8000`) | `8000` |
| Buffer (ms) | ジッタバッファサイズ。LAN は 50〜100ms、WAN は 200ms 推奨 | `100` |

### Asterisk Host の使い分けについて

このウィジェットでは Asterisk への通信が 2 経路ある:

- **WebSocket（ARI events・Media）**: ブラウザが Asterisk に直接接続する
- **REST（POST/DELETE）**: CORS 制限を回避するため、Zabbix サーバ上の PHP がブラウザの代わりに Asterisk を呼び出す

したがって、NAT やリバースプロキシが介在して「ブラウザから見た Asterisk のアドレス」と「Zabbix サーバから見た Asterisk のアドレス」が異なる場合は、両フィールドに別々のアドレスを設定する必要がある。同一 LAN の典型的な構成では両者は同じなので、**Asterisk Host (from Zabbix)** 欄は空欄でよい。

---

## 5. トラブルシューティング

### ウィジェットを配置しようとすると設定画面に戻される

JS アセットが 404 になっている。ブラウザの開発者ツール（F12）でネットワークタブを確認する。

- パスに `conf` が含まれていると nginx がブロックする → ディレクトリ名が `cbm_monitor` になっているか確認
- モジュールの `relative_path` が DB とディレクトリ名と一致しているか確認

### Error: ARI POST failed (500)

PHP の AriProxy が失敗している。Zabbix の PHP エラーログを確認:

```bash
tail -f /var/log/php-fpm/www-error.log
# または
tail -f /var/log/nginx/error.log
```

よくある原因:
- server-side proxy のアドレスが Zabbix サーバから到達できない
- ARI ユーザの認証情報が誤っている
- `disableCsrfValidation()` が呼ばれていない（モジュールの改造時）

### Error: WebSocket connection failed

- Asterisk の HTTP サーバが `0.0.0.0:8088` でリスンしているか確認: `ss -tlnp | grep 8088`
- `allowed_origins` にブラウザのオリジン（Zabbix の URL）が含まれているか確認
- CSP の `connect-src` に `ws://asterisk-host:8088` が含まれているか確認

### Error: StasisStart timeout (10s)

ブラウザを強制終了した直後など、Asterisk が前回の切断を処理しきる前に再接続しようとすると発生する。数秒待ってから Listen を押し直す。

### 音声が再生されない（エラーなし）

- Bridge ID が実際の ConfBridge 名と一致しているか確認: `asterisk -rx 'confbridge list'`
- ブラウザのオーディオ出力が許可されているか確認
- ページをリロードして再試行
