# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
from datetime import datetime


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    apotheke_order_id = fields.Char(string="Apotheke Order ID", readonly=True)
    apotheke_offer_id = fields.Many2one('apotheke.product.offer', string="Apotheke Offer", readonly=True)
    order_reference_for_customer = fields.Char(string="Customer Order Reference")
    shop_id = fields.Many2one('shop.apotheke.shop', string="Shop", readonly=True)
    channel_id = fields.Many2one('shop.apotheke.shop.channel', string="Channel", readonly=True)
    from_apotheke = fields.Boolean(string="From Apotheke", default=False)
    apotheke_tax_ids = fields.Many2many('apotheke.tax', string="Apotheke Taxes")
    accepted_on_apotheke = fields.Boolean(
        string="Accepted on Apotheke",
        compute='_compute_accepted_on_apotheke',
        store=True
    )

    @api.depends('order_line.accepted_on_apotheke')
    def _compute_accepted_on_apotheke(self):
        for order in self:
            if order.order_line:
                order.accepted_on_apotheke = all(line.accepted_on_apotheke for line in order.order_line)
            else:
                order.accepted_on_apotheke = False

    def accept_on_apotheke(self):
        for order in self:
            setting = order.shop_id.setting_id
            api_key = setting.api_key
            server_url = setting.server
            shop_number = order.shop_id.shop_number
            ap_order_id = order.apotheke_order_id

            if not (api_key and server_url and shop_number and ap_order_id):
                raise UserError(_("Missing Apotheke configuration or order ID."))

            # Collect order lines for payload
            order_lines_payload = []
            for line in order.order_line:
                if line.apotheke_line_id:
                    order_lines_payload.append({
                        "accepted": True,
                        "id": line.apotheke_line_id,
                    })

            if not order_lines_payload:
                self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                    'type': 'warning',
                    'sticky': False,
                    'message': _("No valid order lines found for Apotheke order %s.") % order.name,
                })
                continue

            # Construct request
            url = f"{server_url}/api/orders/{ap_order_id}/accept"
            params = {
                "shop_id": shop_number
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": api_key
            }
            payload = {
                "order_lines": order_lines_payload
            }

            try:
                response = requests.put(url, json=payload, headers=headers, params=params)

                if response.status_code == 204:
                    for line in order.order_line:
                        line.accepted_on_apotheke = True
                        line.apotheke_state = 'SHIPPING'
                    self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                        'type': 'success',
                        'sticky': False,
                        'message': _("Order %s accepted successfully on Apotheke.") % order.name,
                    })

                else:
                    try:
                        data = response.json()
                        message = data.get("message") or str(data)
                    except Exception:
                        message = response.text
                    self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                        'type': 'danger',
                        'sticky': False,
                        'message': _("Failed to accept order %s: %s") % (order.name, message),
                    })

            except Exception as e:
                self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                    'type': 'danger',
                    'sticky': False,
                    'message': _("Error while accepting order %s: %s") % (order.name, str(e)),
                })

    def action_confirm(self):
        # 1) call the original confirm logic
        result = super().action_confirm()

        # 2) then for each confirmed order, pull in external info
        for order in self:
            try:
                if order.apotheke_order_id:
                    order.update_partner_infos()
            except Exception as e:
                # Catch any unexpected errors and notify
                self.env['bus.bus']._sendone(
                    self.env.user.partner_id, 'simple_notification', {
                        'type': 'danger',
                        'sticky': True,
                        'message': _("Failed to update external info for %s: %s") % (order.name, e)
                    })

        return result

    def update_partner_infos(self):
        """Fetches the order from the external API and writes all updatable
        partner & address fields plus commitment_date."""
        self.ensure_one()

        # Sanity checks
        setting = self.shop_id.setting_id
        if not self.apotheke_order_id:
            raise UserError(_("Order %s has no Apotheke order ID.") % self.name)
        if not setting or not setting.server or not setting.api_key:
            raise UserError(_("API configuration missing on Shop %s.") % (self.shop_id.name or _("(unknown)")))

        # API request config
        url = f"{setting.server}/api/orders"
        params = {'order_ids': self.apotheke_order_id}
        headers = {
            'Content-Type': 'application/json',
            'Authorization': setting.api_key,
        }

        # API call
        try:
            resp = requests.get(url, params=params, headers=headers)
        except Exception as e:
            self.env['bus.bus']._sendone(
                self.env.user.partner_id, 'simple_notification', {
                    'type': 'danger',
                    'sticky': True,
                    'message': _("API request failed: %s") % str(e),
                })
            return

        if resp.status_code != 200:
            self.env['bus.bus']._sendone(
                self.env.user.partner_id, 'simple_notification', {
                    'type': 'danger',
                    'sticky': True,
                    'message': _("Error fetching order %s: %s") % (self.apotheke_order_id, resp.text),
                })
            return

        payload = resp.json()
        orders = payload.get('orders') or []
        if not orders:
            self.env['bus.bus']._sendone(
                self.env.user.partner_id, 'simple_notification', {
                    'type': 'danger',
                    'sticky': True,
                    'message': _("No data returned for order %s.") % self.apotheke_order_id,
                })
            return

        data = orders[0]

        # Update billing address
        bill = data['customer']['billing_address']
        vals_bill = {
            'street': bill.get('street_1') or '',
            'street2': bill.get('street_2') or '',
            'zip': bill.get('zip_code') or '',
            'city': bill.get('city') or '',
        }
        if bill.get('country_iso_code'):
            country = self.env['res.country'].search([('code', '=', bill['country_iso_code'])], limit=1)
            if country:
                vals_bill['country_id'] = country.id

        self.partner_id.write(vals_bill)
        self.partner_invoice_id.write(vals_bill)

        # Update shipping address
        ship = data['customer']['shipping_address']
        vals_ship = {
            'street': ship.get('street_1') or '',
            'street2': ship.get('street_2') or '',
            'zip': ship.get('zip_code') or '',
            'city': ship.get('city') or '',
        }
        if ship.get('country_iso_code'):
            country = self.env['res.country'].search([('code', '=', ship['country_iso_code'])], limit=1)
            if country:
                vals_ship['country_id'] = country.id

        self.partner_shipping_id.write(vals_ship)

        # Update main partner (name + language if valid)
        cust = data['customer']
        partner_vals = {
            'name': "%s %s" % (cust.get('firstname') or '', cust.get('lastname') or ''),
        }

        locale = cust.get('locale')
        if locale:
            lang_code = locale.split('_')[0]
            lang = self.env['res.lang'].search([('code', '=', lang_code)], limit=1)
            if lang:
                partner_vals['lang'] = lang.code

        self.partner_id.write(partner_vals)

        # Update commitment date
        latest = data.get('delivery_date', {}).get('latest')
        if latest:
            try:
                dt = datetime.fromisoformat(latest.replace('Z', '+00:00'))
                self.commitment_date = fields.Datetime.to_string(dt)
            except Exception:
                pass  # Do not fail on parse error

        # Final success notification
        self.env['bus.bus']._sendone(
            self.env.user.partner_id, 'simple_notification', {
                'type': 'success',
                'sticky': False,
                'message': _("%s: partner information & delivery date updated.") % self.apotheke_order_id,
            })


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    apotheke_line_id = fields.Char(string="Apotheke Line ID")
    commission = fields.Monetary(string='Commission Fees', currency_field='currency_id')
    accepted_on_apotheke = fields.Boolean(string="Accepted on Apotheke")
    apotheke_state = fields.Selection([
        ('STAGING', 'Staging'),
        ('WAITING_ACCEPTANCE', 'Waiting Acceptance'),
        ('WAITING_DEBIT', 'Waiting Debit'),
        ('WAITING_DEBIT_PAYMENT', 'Waiting Debit Payment'),
        ('SHIPPING', 'Shipping'),
        ('SHIPPED', 'Shipped'),
        ('TO_COLLECT', 'To Collect'),
        ('RECEIVED', 'Received'),
        ('CLOSED', 'Closed'),
        ('REFUSED', 'Refused'),
        ('CANCELED', 'Canceled'),
    ], string='Apotheke State')
