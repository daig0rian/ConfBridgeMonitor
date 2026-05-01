'use strict';

class CWidgetConfBridgeMonitor extends CWidget {

	onInitialize() {
		this._player = null;
		this._config = null;
	}

	onActivate() {
	}

	onDeactivate() {
		if (this._player?.running) {
			this._stopListening();
		}
	}

	onDestroy() {
		if (this._player) {
			this._player.stop().catch(() => {});
			this._player = null;
		}
	}

	processUpdateResponse(response) {
		if (response.fields) {
			const prev = this._config;
			this._config = response.fields;

			// If config changed while player is running, stop to force reconnect.
			if (this._player?.running && prev !== null) {
				const changed = ['asterisk_host', 'asterisk_host_server', 'ari_port', 'ari_user', 'ari_password', 'bridge_id']
					.some(k => prev[k] !== response.fields[k]);
				if (changed) {
					this._stopListening();
				}
			}
		}

		// Only re-render the body when the player is not active to avoid interrupting audio.
		if (!this._player?.running) {
			super.processUpdateResponse(response);
			this._bindUI();
		} else {
			this._setHeaderName(response.name);
		}
	}

	// ── Private ─────────────────────────────────────────────────────────────

	_bindUI() {
		const btnListen = this._body.querySelector('.cbm-btn-listen');
		const btnStop   = this._body.querySelector('.cbm-btn-stop');

		if (!btnListen) return;

		btnListen.addEventListener('click', () => this._startListening());
		btnStop.addEventListener('click',   () => this._stopListening());
	}

	_startListening() {
		if (!this._config) return;

		const btnListen = this._body.querySelector('.cbm-btn-listen');
		const btnStop   = this._body.querySelector('.cbm-btn-stop');

		if (btnListen) btnListen.disabled = true;
		if (btnStop)   btnStop.disabled = true;

		this._player = new ConfBridgePlayer({
			host:       this._config.asterisk_host,
			serverHost: this._config.asterisk_host_server || this._config.asterisk_host,
			port:       this._config.ari_port,
			apiKey:     this._config.ari_user + ':' + this._config.ari_password,
			bridgeId:   this._config.bridge_id,
			bufferMs:   this._config.buffer_ms,
			onStatus:   (msg) => this._setStatus(msg),
		});

		this._player.start().then(() => {
			if (btnStop) btnStop.disabled = false;
		}).catch((e) => {
			this._setStatus('Error: ' + e.message, true);
			console.error('[cbm]', e);
			this._player = null;
			if (btnListen) btnListen.disabled = false;
		});
	}

	_stopListening() {
		const btnListen = this._body.querySelector('.cbm-btn-listen');
		const btnStop   = this._body.querySelector('.cbm-btn-stop');

		if (btnStop) btnStop.disabled = true;

		const player = this._player;
		this._player = null;

		if (player) {
			player.stop().finally(() => {
				if (btnListen) btnListen.disabled = false;
				if (btnStop)   btnStop.disabled = true;
			});
		}
	}

	_setStatus(msg, isError = false) {
		const el = this._body.querySelector('.cbm-status');
		if (!el) return;
		el.textContent = msg;
		el.classList.toggle('cbm-status-error', isError);
	}
}
