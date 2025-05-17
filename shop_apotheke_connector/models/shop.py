# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api, _
import requests
import logging

_logger = logging.getLogger(__name__)


class ShopApothekeShop(models.Model):
    _name = 'shop.apotheke.shop'
    _description = 'Shop Apotheke Shop'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    setting_id = fields.Many2one('shop.apotheke.connector.setting', string='Instance')
    shop_number = fields.Char(string='Shop ID', required=True)
    name = fields.Char(string='Name', required=True)
    channel_ids = fields.One2many('shop.apotheke.shop.channel', 'shop_id', string='Channels')
    delivery_method_ids = fields.Many2many(
        'delivery.carrier',
        'shop_apotheke_delivery_rel',
        'shop_id',
        'carrier_id',
        string='Delivery Methods'
    )
    product_ids = fields.Many2many(
        'apotheke.product',
        'apotheke_product_shop_rel',
        'shop_id',
        'apotheke_product_id',
        string='Products'
    )

    def fetch_shop_channels(self):
        for shop in self:
            if not shop.shop_number:
                continue

            try:
                setting = shop.setting_id
                if not setting or not setting.server or not setting.api_key:
                    return

                url = f"{setting.server.rstrip('/')}/api/channels"
                headers = {
                    "Authorization": setting.api_key,
                    "Accept": "application/json"
                }
                query = {"shop_id": shop.shop_number}
                response = requests.get(url, headers=headers, params=query)

                if response.status_code != 200:
                    raise Exception(f"HTTP {response.status_code} - {response.text}")

                data = response.json()
                channels = data.get("channels", [])

                # Clear existing channels before update
                shop.channel_ids.unlink()

                for channel in channels:
                    shop.channel_ids.create({
                        'shop_id': shop.id,
                        'code': channel.get('code'),
                        'description': channel.get('description'),
                        'label': channel.get('label'),
                    })

                self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                    'type': 'success',
                    'sticky': False,
                    'message': _("Channels synchronized successfully for shop '%s'.") % shop.name,
                })

            except Exception as e:
                _logger.exception("Failed to fetch channels for shop %s", shop.name)
                self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                    'type': 'danger',
                    'sticky': False,
                    'message': _("Failed to fetch channel data: %s") % str(e),
                })

    def fetch_delivery_methods(self):
        for shop in self:
            if not shop.shop_number:
                continue

            try:
                setting = shop.setting_id
                if not setting or not setting.server or not setting.api_key:
                    raise Exception(_("Missing API credentials for shop '%s'.") % shop.name)

                url = f"{setting.server.rstrip('/')}/api/shipping/types"
                headers = {
                    "Authorization": setting.api_key,
                    "Accept": "application/json"
                }
                query = {"shop_id": shop.shop_number}
                response = requests.get(url, headers=headers, params=query)

                if response.status_code != 200:
                    raise Exception(f"HTTP {response.status_code} - {response.text}")

                data = response.json()
                shipping_types = data.get("shipping_types", [])
                created = 0
                linked = 0

                for shipping in shipping_types:
                    code = shipping.get('code')
                    description = shipping.get('description')
                    label = shipping.get('label')
                    standard_code = shipping.get('standard_code')

                    if not code:
                        continue

                    carrier = self.env['delivery.carrier'].search([('code', '=', code)], limit=1)

                    if not carrier:
                        # Create related product
                        product = self.env['product.product'].create({
                            'name': label or description or code,
                            'type': 'service',
                            'default_code': code,
                        })

                        # Create new delivery.carrier
                        carrier = self.env['delivery.carrier'].create({
                            'name': label or description or code,
                            'product_id': product.id,
                            'code': code,
                            'carrier_description': description or standard_code,
                        })
                        created += 1

                    # Link the shop
                    if shop.id not in carrier.shop_ids.ids:
                        carrier.shop_ids = [(4, shop.id)]
                        linked += 1

                shop.delivery_method_ids = [
                    (6, 0, self.env['delivery.carrier'].search([('shop_ids', 'in', shop.id)]).ids)]

                msg = _("Delivery methods fetched for shop '%s'. %d created, %d linked.") % (shop.name, created, linked)
                _logger.info(msg)
                self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                    'type': 'success',
                    'sticky': False,
                    'message': msg,
                })

            except Exception as e:
                _logger.exception("Failed to fetch delivery methods for shop %s", shop.name)
                self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                    'type': 'danger',
                    'sticky': False,
                    'message': _("Failed to fetch delivery methods for shop '%s': %s") % (shop.name, str(e)),
                })


class ShopApothekeShopChannel(models.Model):
    _name = 'shop.apotheke.shop.channel'
    _description = 'Shop Apotheke Shop Channel'
    _rec_name = 'label'

    shop_id = fields.Many2one('shop.apotheke.shop', string="Shop", ondelete='cascade')
    code = fields.Char(string="Code", required=True)
    description = fields.Char(string="Description")
    label = fields.Char(string="Name")
