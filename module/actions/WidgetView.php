<?php declare(strict_types = 0);

namespace Modules\ConfBridgeMonitor\Actions;

use CControllerDashboardWidgetView,
	CControllerResponseData;

class WidgetView extends CControllerDashboardWidgetView {

	protected function doAction(): void {
		$this->setResponse(new CControllerResponseData([
			'name'   => $this->getInput('name', $this->widget->getDefaultName()),
			'fields' => [
				'asterisk_host'        => $this->fields_values['asterisk_host'],
				'asterisk_host_server' => $this->fields_values['asterisk_host_server'],
				'ari_port'             => (int) $this->fields_values['ari_port'],
				'ari_user'      => $this->fields_values['ari_user'],
				'ari_password'  => $this->fields_values['ari_password'],
				'bridge_id'     => $this->fields_values['bridge_id'],
				'buffer_ms'     => (int) $this->fields_values['buffer_ms'],
			],
			'user' => [
				'debug_mode' => $this->getDebugMode()
			]
		]));
	}
}
