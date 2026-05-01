'use strict';

/**
 * ConfBridgePlayer — Asterisk ConfBridge audio receiver for Zabbix widget.
 *
 * REST calls go through the Zabbix PHP proxy (AriProxy action) to avoid CORS.
 * WebSocket connections go directly to Asterisk (no CORS restriction).
 *
 * Two-WebSocket architecture (must NOT share a socket):
 *   - ARI events WS : keeps Stasis channel alive, receives StasisStart
 *   - Media WS      : receives binary Opus frames
 */
class ConfBridgePlayer {

	constructor({ host, serverHost, port, apiKey, bridgeId, bufferMs, onStatus } = {}) {
		this._host       = host;
		this._serverHost = serverHost || host;  // falls back to host when both addresses are the same
		this._port       = port;
		this._apiKey   = apiKey;
		this._bridgeId = bridgeId;
		this._bufferMs = bufferMs ?? 100;
		this._onStatus = onStatus ?? (() => {});

		this._ariWs     = null;
		this._mediaWs   = null;
		this._audioCtx  = null;
		this._decoder   = null;
		this._channelId = null;
		this._connId    = null;
		this._nextPlay  = 0;

		this.frameCount = 0;
		this.running    = false;
	}

	// ── Public ──────────────────────────────────────────────────────────────

	async start() {
		this.running    = true;
		this.frameCount = 0;
		this._nextPlay  = 0;

		try {
			// 1. WASM Opus decoder
			this._status('Initializing decoder…');
			const { OpusDecoder } = OpusDecoderLib;
			this._decoder = new OpusDecoder();
			await this._decoder.ready;

			// 2. AudioContext (must be inside a user gesture)
			this._audioCtx = new AudioContext({ sampleRate: 48000 });
			await this._audioCtx.resume();

			// 3. ARI events WebSocket (keeps Stasis channel alive; auth via query param)
			this._status('Connecting ARI events WS…');
			const wsBase = `ws://${this._host}:${this._port}`;
			const ariUrl = `${wsBase}/ari/events?api_key=${encodeURIComponent(this._apiKey)}&app=confbridge_monitor&subscribeAll=true`;
			this._ariWs  = await this._openWs(ariUrl);
			this._status('ARI events WS connected');

			// 4. Create externalMedia channel via Zabbix PHP proxy (avoids CORS)
			this._status('Creating externalMedia channel…');
			const ch = await this._proxyPost(
				'/channels/externalMedia' +
				'?app=confbridge_monitor' +
				'&encapsulation=none' +
				'&transport=websocket' +
				'&connection_type=server' +
				'&format=opus' +
				'&direction=both'
			);
			this._channelId = ch.id;
			this._connId    = ch.channelvars.MEDIA_WEBSOCKET_CONNECTION_ID;

			// 5. Media WebSocket (connecting answers the channel, triggers StasisStart)
			this._status('Connecting Media WS…');
			const mediaUrl = `${wsBase}/media/${this._connId}?api_key=${encodeURIComponent(this._apiKey)}`;
			this._mediaWs  = await this._openWs(mediaUrl, (ws) => {
				ws.binaryType = 'arraybuffer';
				ws.onmessage  = (e) => this._onFrame(e);
				ws.onclose    = () => { if (this.running) this._status('Media WS disconnected'); };
			});

			// 6. Wait for StasisStart
			this._status('Waiting for StasisStart…');
			await this._waitStasisStart();

			// 7. Set channel var → continue into ConfBridge
			await this._proxyPost(`/channels/${this._channelId}/variable?variable=MEETME_ROOMNUM&value=${this._bridgeId}`);
			await this._proxyPost(`/channels/${this._channelId}/continue?context=ext-meetme&extension=STARTMEETME&priority=1`);
			this._status(`Listening to bridge '${this._bridgeId}'…`);

		} catch (e) {
			// Ensure any partially-created Asterisk channel is deleted before surfacing the error.
			await this.stop();
			throw e;
		}
	}

	async stop() {
		this.running = false;

		if (this._channelId) {
			try { await this._proxyRequest('DELETE', `/channels/${this._channelId}`); } catch { /* ignore */ }
			this._channelId = null;
		}

		this._mediaWs?.close();  this._mediaWs = null;
		this._ariWs?.close();    this._ariWs   = null;
		await this._audioCtx?.close();  this._audioCtx = null;
		this._decoder?.free();   this._decoder = null;
		this._status('Stopped');
	}

	// ── Private ─────────────────────────────────────────────────────────────

	_onFrame(event) {
		if (!this.running) return;
		if (!(event.data instanceof ArrayBuffer)) return; // text frames (MEDIA_START etc.)

		let decoded;
		try {
			decoded = this._decoder.decodeFrame(new Uint8Array(event.data));
		} catch (e) {
			console.warn('[cbm decode error]', e);
			return;
		}

		const { channelData, samplesDecoded } = decoded;
		if (samplesDecoded === 0) return;

		// Mix down to mono
		const nch = channelData.length;
		const pcm = channelData[0].slice();
		for (let c = 1; c < nch; c++) {
			for (let i = 0; i < pcm.length; i++) pcm[i] += channelData[c][i];
		}
		if (nch > 1) for (let i = 0; i < pcm.length; i++) pcm[i] /= nch;

		const buf = this._audioCtx.createBuffer(1, samplesDecoded, 48000);
		buf.copyToChannel(pcm, 0);

		const src = this._audioCtx.createBufferSource();
		src.buffer = buf;
		src.connect(this._audioCtx.destination);

		const now = this._audioCtx.currentTime;
		if (this._nextPlay < now + 0.010) {
			this._nextPlay = now + this._bufferMs / 1000;
		}
		src.start(this._nextPlay);
		this._nextPlay += buf.duration;

		this.frameCount++;
		if (this.frameCount % 50 === 0) {
			const sec = (this.frameCount * 20 / 1000).toFixed(1);
			this._status(`Listening… ${sec}s`, false);
		}
	}

	_waitStasisStart() {
		const channelId = this._channelId;
		return new Promise((resolve, reject) => {
			const timer = setTimeout(
				() => reject(new Error('StasisStart timeout (10s)')),
				10_000
			);
			const handler = (ev) => {
				let event;
				try { event = JSON.parse(ev.data); } catch { return; }
				if (event.type === 'StasisStart' && event.channel?.id === channelId) {
					clearTimeout(timer);
					this._ariWs.removeEventListener('message', handler);
					resolve();
				}
			};
			this._ariWs.addEventListener('message', handler);
		});
	}

	_openWs(url, setup) {
		return new Promise((resolve, reject) => {
			const ws = new WebSocket(url);
			if (setup) setup(ws);
			ws.onopen  = () => resolve(ws);
			ws.onerror = () => reject(new Error(`WebSocket connection failed: ${url.replace(/api_key=[^&]+/, 'api_key=***')}`));
		});
	}

	// REST via Zabbix PHP proxy to avoid CORS
	_proxyPost(path) {
		return this._proxyRequest('POST', path);
	}

	async _proxyRequest(method, path) {
		const curl = new Curl('zabbix.php');
		curl.setArgument('action', 'widget.confbridge_monitor.proxy');

		const r = await fetch(curl.getUrl(), {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				method,
				path,
				host:    this._serverHost,
				port:    this._port,
				api_key: this._apiKey
			})
		});

		const text = await r.text();
		if (!r.ok && r.status !== 204) {
			throw new Error(`ARI ${method} ${path} failed (${r.status}): ${text}`);
		}
		if (!text || text === '{}') return {};
		try { return JSON.parse(text); } catch { return {}; }
	}

	_status(msg, log = true) {
		if (log) console.log('[cbm]', msg);
		this._onStatus(msg);
	}
}
