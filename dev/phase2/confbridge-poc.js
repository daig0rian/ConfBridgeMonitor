/**
 * Phase 2 PoC: ConfBridge ブラウザ音声プレーヤー
 *
 * WebSocket 2本構成:
 *   - ARI events WS : /ari/events?api_key=...  (Stasis 維持・制御)
 *   - Media WS      : /media/<connection_id>    (Opus フレーム受信)
 *
 * デコード: WASM OpusDecoder (opus-decoder パッケージ)
 * 再生    : AudioBufferSourceNode + スケジューリングによる簡易ジッタバッファ
 */

import { OpusDecoder } from "./opus-decoder.bundle.js";

// ---- Asterisk 接続設定 ----
const ASTERISK_HOST = "192.168.11.31";
const ASTERISK_PORT = 8088;
const ARI_API_KEY   = "confbridge_poc:confbridge_poc_pass";
const APP_NAME      = "confbridge_poc";
// ---------------------------

const SAMPLE_RATE  = 48000;
const JITTER_MS    = 100;   // 初期バッファ(ms)
const ARI_WS_BASE  = `ws://${ASTERISK_HOST}:${ASTERISK_PORT}`;
const API_BASE     = "/ari"; // serve.py プロキシ経由

export class ConfBridgePlayer {
  constructor({ onStatus } = {}) {
    this._onStatus = onStatus ?? (() => {});
    this._ariWs       = null;
    this._mediaWs     = null;
    this._audioCtx    = null;
    this._decoder     = null;
    this._channelId   = null;
    this._connId      = null;
    this._nextPlay    = 0;
    this.frameCount   = 0;
    this.running      = false;
  }

  // ── Public ──────────────────────────────────────────────────────────────

  async start(bridgeId) {
    this.running    = true;
    this.frameCount = 0;
    this._nextPlay  = 0; // 新しい AudioContext は currentTime=0 から始まるので必ずリセット

    // 1. WASM Opus デコーダ初期化
    this._status("Opus デコーダ初期化中...");
    this._decoder = new OpusDecoder();
    await this._decoder.ready;
    this._status("デコーダ準備完了");

    // 2. AudioContext (ユーザジェスチャ内で呼ぶ必要あり)
    this._audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
    await this._audioCtx.resume();

    // 3. ARI events WebSocket 接続 (Stasis チャンネルを生かし続ける)
    this._status("ARI events WS 接続中...");
    const ariUrl = `${ARI_WS_BASE}/ari/events?api_key=${ARI_API_KEY}&app=${APP_NAME}&subscribeAll=true`;
    this._ariWs  = await this._openWs(ariUrl);
    this._status("ARI events WS 接続済");

    // 4. externalMedia チャンネル作成 (REST via プロキシ)
    this._status("externalMedia チャンネル作成中...");
    const ch = await this._post(
      `/channels/externalMedia` +
      `?app=${APP_NAME}` +
      `&encapsulation=none` +
      `&transport=websocket` +
      `&connection_type=server` +
      `&format=opus` +
      `&direction=both`
    );
    this._channelId = ch.id;
    this._connId    = ch.channelvars.MEDIA_WEBSOCKET_CONNECTION_ID;
    this._status(`チャンネル作成済 (${this._channelId.substring(0, 20)}...)`);

    // 5. Media WebSocket 接続 (これが channel を "answer" → StasisStart をトリガー)
    this._status("Media WS 接続中...");
    const mediaUrl = `${ARI_WS_BASE}/media/${this._connId}?api_key=${ARI_API_KEY}`;
    this._mediaWs  = await this._openWs(mediaUrl, (ws) => {
      ws.binaryType       = "arraybuffer";
      ws.onmessage        = (e) => this._onFrame(e);
      ws.onclose          = () => { if (this.running) this._status("Media WS 切断"); };
    });
    this._status("Media WS 接続済。StasisStart 待機中...");

    // 6. StasisStart 待機
    await this._waitStasisStart();

    // 7. チャンネル変数セット → ConfBridge へ continue
    await this._post(`/channels/${this._channelId}/variable?variable=MEETME_ROOMNUM&value=${bridgeId}`);
    await this._post(`/channels/${this._channelId}/continue?context=ext-meetme&extension=STARTMEETME&priority=1`);
    this._status(`ConfBridge '${bridgeId}' に参加。受信中...`);
  }

  async stop() {
    this.running = false;
    if (this._channelId) {
      try { await this._delete(`/channels/${this._channelId}`); } catch { /* ignore */ }
      this._channelId = null;
    }
    this._mediaWs?.close();  this._mediaWs = null;
    this._ariWs?.close();    this._ariWs   = null;
    await this._audioCtx?.close();  this._audioCtx = null;
    this._decoder?.free();  this._decoder = null;
    this._status("停止しました");
  }

  // ── Private ─────────────────────────────────────────────────────────────

  _onFrame(event) {
    if (!this.running) return; // Stop 処理中に届いたフレームは捨てる
    if (!(event.data instanceof ArrayBuffer)) {
      console.log("[media text]", event.data); // MEDIA_START など
      return;
    }

    let decoded;
    try {
      decoded = this._decoder.decodeFrame(new Uint8Array(event.data));
    } catch (e) {
      console.warn("[decode error]", e);
      return;
    }
    const { channelData, samplesDecoded } = decoded;
    if (samplesDecoded === 0) return;

    // mono に mix-down (チャンネル数に依存)
    const nch = channelData.length;
    const pcm = channelData[0];
    if (nch > 1) {
      for (let i = 0; i < pcm.length; i++) {
        let s = pcm[i];
        for (let c = 1; c < nch; c++) s += channelData[c][i];
        pcm[i] = s / nch;
      }
    }

    const buf = this._audioCtx.createBuffer(1, samplesDecoded, SAMPLE_RATE);
    buf.copyToChannel(pcm, 0);

    const src = this._audioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(this._audioCtx.destination);

    const now = this._audioCtx.currentTime;
    if (this._nextPlay < now + 0.010) {
      // バッファアンダーラン → 再同期
      this._nextPlay = now + JITTER_MS / 1000;
    }
    src.start(this._nextPlay);
    this._nextPlay += buf.duration;

    this.frameCount++;
    if (this.frameCount % 50 === 0) {
      const sec = (this.frameCount * 20 / 1000).toFixed(1);
      this._status(`受信中... ${sec}s`, false);
    }
  }

  _waitStasisStart() {
    const channelId = this._channelId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error("StasisStart タイムアウト (10秒)")),
        10_000
      );
      const handler = (ev) => {
        let event;
        try { event = JSON.parse(ev.data); } catch { return; }
        if (event.type === "StasisStart" && event.channel?.id === channelId) {
          clearTimeout(timer);
          this._ariWs.removeEventListener("message", handler);
          resolve();
        }
      };
      this._ariWs.addEventListener("message", handler);
    });
  }

  _openWs(url, setup) {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      if (setup) setup(ws);
      ws.onopen  = () => resolve(ws);
      ws.onerror = () => reject(new Error(`WebSocket 接続失敗: ${url.replace(/api_key=[^&]+/, "api_key=***")}`));
    });
  }

  async _post(path) {
    const r = await fetch(`${API_BASE}${path}`, { method: "POST" });
    if (!r.ok && r.status !== 204) {
      const body = await r.text().catch(() => "");
      throw new Error(`POST ${path} 失敗 (${r.status}): ${body}`);
    }
    if (r.status === 204 || r.headers.get("Content-Length") === "0") return {};
    return r.json().catch(() => ({}));
  }

  async _delete(path) {
    await fetch(`${API_BASE}${path}`, { method: "DELETE" }).catch(() => {});
  }

  _status(msg, log = true) {
    if (log) console.log(`[poc] ${msg}`);
    this._onStatus(msg);
  }
}
