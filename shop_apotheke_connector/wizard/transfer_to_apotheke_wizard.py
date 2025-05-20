# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
import requests
import logging
from openpyxl import load_workbook
from io import BytesIO

_logger = logging.getLogger(__name__)


class TransferToApothekeWizard(models.TransientModel):
    _name = 'transfer.to.apotheke.wizard'
    _description = 'Transfer Products to Shop Apotheke'

    setting_id = fields.Many2one('shop.apotheke.connector.setting', string='Connector Setting', required=True)
    product_ids = fields.Many2many('product.template', string='Products')

    def action_confirm_transfer(self):
        ApothekeProduct = self.env['apotheke.product']
        partner_id = self.env.user.partner_id

        for product in self.product_ids:
            with self.env.cr.savepoint():
                sku = product.default_code or product.ean
                if not sku:
                    self.env['bus.bus']._sendone(partner_id, 'simple_notification', {
                        'type': 'warning',
                        'sticky': False,
                        'message': _(f'❌ Product "{product.name}" skipped: missing EAN and SKU.'),
                    })
                    continue

                duplicate = ApothekeProduct.search([
                    '&',
                    ('setting_id', '=', self.setting_id.id),
                    '|',
                    ('ean', '=', product.ean),
                    ('sku', '=', sku)
                ], limit=1)

                if duplicate:
                    self.env['bus.bus']._sendone(partner_id, 'simple_notification', {
                        'type': 'warning',
                        'sticky': False,
                        'message': _(
                            f'⚠️ Product "{product.name}" skipped: already exists in Apotheke for the instance "{self.setting_id.display_name}".'),
                    })
                    continue

                apotheke_vals = {
                    'setting_id': self.setting_id.id,
                    'name': product.name,
                    'ean': product.ean,
                    'sku': sku,
                    'main_image': product.image_1920,
                    'odoo_product_id': product.id,
                    'state_sync_odoo': 'synchronized',
                }

                ApothekeProduct.create(apotheke_vals)
                product.transferred_to_apotheke = True

                self.env['bus.bus']._sendone(partner_id, 'simple_notification', {
                    'type': 'success',
                    'sticky': False,
                    'message': _(f'✅ Product "{product.name}" transferred successfully.'),
                })
