<?php declare(strict_types = 0);

/**
 * ConfBridge Monitor widget edit form view.
 *
 * @var CView  $this
 * @var array  $data
 */

$form = new CWidgetFormView($data);

$form
	->addField(
		new CWidgetFieldTextBoxView($data['fields']['asterisk_host'])
	)
	->addField(
		(new CWidgetFieldTextBoxView($data['fields']['asterisk_host_server']))
			->setPlaceholder(_('same as Asterisk Host (browser)'))
	)
	->addField(
		new CWidgetFieldIntegerBoxView($data['fields']['ari_port'])
	)
	->addField(
		new CWidgetFieldTextBoxView($data['fields']['ari_user'])
	)
	->addField(
		new CWidgetFieldTextBoxView($data['fields']['ari_password'])
	)
	->addField(
		new CWidgetFieldTextBoxView($data['fields']['bridge_id'])
	)
	->addField(
		new CWidgetFieldIntegerBoxView($data['fields']['buffer_ms'])
	)
	->show();
