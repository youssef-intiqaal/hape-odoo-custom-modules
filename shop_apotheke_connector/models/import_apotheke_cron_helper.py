# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, api
import logging
import traceback

_logger = logging.getLogger(__name__)

class ImportApothekeCronHelper(models.TransientModel):
    _name = 'import.apotheke.cron.helper'
    _description = 'Apotheke Order Import Cron Helper'

    @api.model
    def cron_import_apotheke_orders(self):
        Setting = self.env['shop.apotheke.connector.setting']
        Wizard = self.env['import.apotheke.order.wizard']
        Log = self.env['apotheke.import.operation.log']

        settings = Setting.search([])
        _logger.info("Starting Apotheke cron job for %s settings", len(settings))

        for setting in settings:
            if not setting.shop_ids:
                _logger.warning("No shops found for setting ID %s", setting.id)
                continue

            for shop in setting.shop_ids:
                if not shop.channel_ids:
                    _logger.warning("No channels found for shop ID %s", shop.id)
                    continue

                for channel in shop.channel_ids:
                    try:
                        _logger.info("Processing instance %s | shop %s | channel %s",
                                     setting.display_name, shop.name, channel.label)

                        wizard = Wizard.create({
                            'setting_id': setting.id,
                            'shop_id': shop.id,
                            'channel_id': channel.id,
                            'change_state_on_apotheke': False,
                        })
                        wizard_result = wizard.action_import_orders()

                        # Safely parse domain to get number of imported orders
                        imported_order_ids = []
                        if wizard_result:
                            domain = wizard_result.get('domain')
                            if isinstance(domain, list) and len(domain) > 1:
                                domain_filter = domain[1]
                                if isinstance(domain_filter, (list, tuple)) and len(domain_filter) > 2:
                                    imported_order_ids = domain_filter[2]

                        imported_count = len(imported_order_ids)

                        Log.create({
                            'setting_id': setting.id,
                            'shop_id': shop.id,
                            'channel_id': channel.id,
                            'state': 'success',
                            'imported_order_count': imported_count,
                        })

                        _logger.info("Successfully imported %s orders", imported_count)

                    except Exception as e:
                        error_trace = traceback.format_exc()
                        _logger.error("Failed to import orders for setting %s | shop %s | channel %s\n%s",
                                      setting.display_name, shop.name, channel.label, error_trace)

                        Log.create({
                            'setting_id': setting.id,
                            'shop_id': shop.id,
                            'channel_id': channel.id,
                            'state': 'failed',
                            'error_message': error_trace,
                        })
