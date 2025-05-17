# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api
import logging
import re

_logger = logging.getLogger(__name__)


class ShopApothekeConnectorSetting(models.Model):
    _name = 'shop.apotheke.connector.setting'
    _description = 'Shop Apotheke Connector Setting'
    _inherit = ['mail.thread']
    _rec_name = 'display_name'

    server = fields.Char(string='Server URL', required=True)
    api_key = fields.Char(string='API Key', required=True)
    shop_ids = fields.One2many('shop.apotheke.shop', 'setting_id', string='Shops', required=True)
    display_name = fields.Char(string='Name', compute='_compute_display_name', store=True)
    create_product_if_not_found = fields.Boolean(
        string='Create Product if Not Found in Odoo',
        help='If checked, the connector will create a product in Odoo when a matching one is not found.'
    )

    @api.depends('server')
    def _compute_display_name(self):
        for rec in self:
            if rec.server:
                try:
                    domain = re.sub(r'^https?://', '', rec.server)
                    rec.display_name = domain.split('.')[0]
                except Exception as e:
                    _logger.warning(f"Failed to compute display_name: {e}")
                    rec.display_name = ''
            else:
                rec.display_name = ''

    @api.model
    def create(self, vals):
        record = super().create(vals)
        if record.shop_ids:
            for shop in record.shop_ids:
                shop.fetch_shop_channels()
                shop.fetch_delivery_methods()
        return record

    def write(self, vals):
        res = super().write(vals)
        if self.shop_ids:
            for shop in self.shop_ids:
                shop.fetch_shop_channels()
                shop.fetch_delivery_methods()
        return res