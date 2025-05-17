# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, _
import requests

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def send_to_shipper(self):
        res = super().send_to_shipper()

        for picking in self:
            sale_order = picking.sale_id
            if not sale_order or not sale_order.apotheke_order_id:
                self.env['bus.bus']._sendone(
                    self.env.user.partner_id, 'simple_notification', {
                        'type': 'danger',
                        'sticky': True,
                        'message': _("Missing sale order or Apotheke order ID for picking %s.") % picking.name,
                    })
                continue

            shop = sale_order.shop_id
            setting = shop.setting_id

            if not setting or not setting.server or not setting.api_key:
                self.env['bus.bus']._sendone(
                    self.env.user.partner_id, 'simple_notification', {
                        'type': 'danger',
                        'sticky': True,
                        'message': _("Missing API configuration for shop %s in picking %s.") % (shop.name, picking.name),
                    })
                continue

            order_id = sale_order.apotheke_order_id
            url = f"{setting.server}/api/orders/{order_id}/tracking"

            carrier = None
            channel_code = sale_order.channel_id.code

            if channel_code == 'INIT':
                carrier = 'DPD'
            elif channel_code == 'AT':
                carrier = 'POST'
            else:
                self.env['bus.bus']._sendone(
                    self.env.user.partner_id, 'simple_notification', {
                        'type': 'danger',
                        'sticky': True,
                        'message': _("Unknown channel code '%s' for order %s.") % (channel_code, order_id),
                    })
                continue

            payload = {
                "carrier_code": carrier,
                "carrier_name": carrier,
                "carrier_standard_code": carrier,
                "tracking_number": picking.carrier_tracking_ref or ''
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"{setting.api_key}"
            }

            try:
                response = requests.put(url, json=payload, headers=headers)
                if response.status_code == 204:
                    self.env['bus.bus']._sendone(
                        self.env.user.partner_id, 'simple_notification', {
                            'type': 'success',
                            'sticky': False,
                            'message': _("%s sent to shipper successfully.") % order_id,
                        })
                else:
                    error_data = response.json()
                    self.env['bus.bus']._sendone(
                        self.env.user.partner_id, 'simple_notification', {
                            'type': 'danger',
                            'sticky': True,
                            'message': _("Error sending %s: %s") % (order_id, error_data),
                        })
            except Exception as e:
                self.env['bus.bus']._sendone(
                    self.env.user.partner_id, 'simple_notification', {
                        'type': 'danger',
                        'sticky': True,
                        'message': _("Exception sending %s: %s") % (order_id, str(e)),
                    })

        return res
