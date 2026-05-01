<?php declare(strict_types = 0);

namespace Modules\ConfBridgeMonitor\Actions;

use CController,
	CControllerResponseData;

/**
 * Proxies REST calls from the browser to Asterisk ARI.
 * Avoids browser CORS restrictions when Zabbix and Asterisk are on different origins.
 *
 * POST /zabbix.php?action=widget.confbridge_monitor.proxy
 * Body (JSON): { method, path, host, port, api_key }
 */
class AriProxy extends CController {

	private array $proxy_input = [];

	protected function init(): void {
		$this->disableCsrfValidation();
	}

	protected function checkInput(): bool {
		$body = file_get_contents('php://input');
		$data = $body ? json_decode($body, true) : null;

		if (!is_array($data)) {
			$this->sendError('Invalid JSON body');
			return false;
		}

		foreach (['method', 'path', 'host', 'port', 'api_key'] as $key) {
			if (!array_key_exists($key, $data)) {
				$this->sendError("Missing field: $key");
				return false;
			}
		}

		if (!in_array($data['method'], ['POST', 'DELETE'], true)) {
			$this->sendError('Invalid method');
			return false;
		}

		$this->proxy_input = $data;
		return true;
	}

	protected function checkPermissions(): bool {
		return $this->getUserType() >= USER_TYPE_ZABBIX_USER;
	}

	protected function doAction(): void {
		$method  = $this->proxy_input['method'];
		$path    = $this->proxy_input['path'];
		$host    = $this->proxy_input['host'];
		$port    = (int) $this->proxy_input['port'];
		$api_key = $this->proxy_input['api_key'];

		$url = 'http://' . $host . ':' . $port . '/ari' . $path;

		$ch = curl_init($url);
		curl_setopt_array($ch, [
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_CUSTOMREQUEST  => $method,
			CURLOPT_USERPWD        => $api_key,
			CURLOPT_TIMEOUT        => 10,
		]);

		$body   = curl_exec($ch);
		$status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
		$err    = curl_error($ch);
		curl_close($ch);

		if ($err) {
			$this->sendError($err);
			return;
		}

		http_response_code($status);

		$out = ($body !== false && $body !== '') ? $body : '{}';
		$this->setResponse(new CControllerResponseData(['main_block' => $out]));
	}

	private function sendError(string $msg): void {
		$this->setResponse(
			new CControllerResponseData(['main_block' => json_encode(['error' => $msg])])
		);
	}
}
