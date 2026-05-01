<?php declare(strict_types = 0);

namespace Modules\ConfBridgeMonitor\Includes;

use Zabbix\Widgets\CWidgetForm;

use Zabbix\Widgets\Fields\{
	CWidgetFieldIntegerBox,
	CWidgetFieldTextBox
};

class WidgetForm extends CWidgetForm {

	public function addFields(): self {
		return $this
			->addField(
				(new CWidgetFieldTextBox('asterisk_host', _('Asterisk Host (from Browser)')))
					->setDefault('10.0.0.1')
					->setFlags(CWidgetFieldTextBox::FLAG_NOT_EMPTY)
			)
			->addField(
				(new CWidgetFieldTextBox('asterisk_host_server', _('Asterisk Host (from Zabbix)')))
					->setDefault('')
			)
			->addField(
				(new CWidgetFieldIntegerBox('ari_port', _('ARI Port'), 1, 65535))
					->setDefault(8088)
			)
			->addField(
				(new CWidgetFieldTextBox('ari_user', _('ARI Username')))
					->setDefault('MY_ARI_USERNAME')
					->setFlags(CWidgetFieldTextBox::FLAG_NOT_EMPTY)
			)
			->addField(
				(new CWidgetFieldTextBox('ari_password', _('ARI Password')))
					->setDefault('MY_ARI_PASSWORD')
			)
			->addField(
				(new CWidgetFieldTextBox('bridge_id', _('Bridge ID')))
					->setDefault('8000')
					->setFlags(CWidgetFieldTextBox::FLAG_NOT_EMPTY)
			)
			->addField(
				(new CWidgetFieldIntegerBox('buffer_ms', _('Buffer (ms)'), 20, 2000))
					->setDefault(100)
			);
	}
}
