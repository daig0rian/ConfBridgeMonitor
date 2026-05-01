<?php declare(strict_types = 0);

/**
 * ConfBridge Monitor widget view.
 *
 * @var CView  $this
 * @var array  $data
 */

$view = new CWidgetView($data);

$body = (new CDiv(
	(new CDiv([
		(new CDiv([
			(new CButton('', _('▶  Listen')))
				->addClass('cbm-btn-listen')
				->addClass('btn-alt'),
			(new CButton('', _('■  Stop')))
				->addClass('cbm-btn-stop')
				->addClass('btn-danger')
				->setAttribute('disabled', 'disabled'),
		]))->addClass('cbm-controls'),
		(new CDiv(_('Ready')))
			->addClass('cbm-status'),
	]))->addClass('cbm-inner')
))->addClass('cbm-player');

$view
	->addItem($body)
	->setVar('fields', $data['fields'])
	->show();
