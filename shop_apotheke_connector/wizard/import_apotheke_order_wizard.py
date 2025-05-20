# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api, _
import requests


class ImportApothekeOrderWizard(models.TransientModel):
    _name = 'import.apotheke.order.wizard'
    _description = 'Import Apotheke Orders Wizard'

    setting_id = fields.Many2one('shop.apotheke.connector.setting', string='Instance', required=True)
    shop_id = fields.Many2one('shop.apotheke.shop', string='Shop', required=True,
                              domain="[('setting_id', '=', setting_id)]")
    channel_id = fields.Many2one('shop.apotheke.shop.channel', string='Channel', required=True,
                                 domain="[('shop_id', '=', shop_id)]")
    change_state_on_apotheke = fields.Boolean(string='Change state on Shop Apotheke', default=False)

    @api.onchange('setting_id')
    def _onchange_setting_id(self):
        if self.shop_id and self.shop_id.setting_id != self.setting_id:
            self.shop_id = False
        if self.channel_id and self.channel_id.shop_id.setting_id != self.setting_id:
            self.channel_id = False

    @api.onchange('shop_id')
    def _onchange_shop_id(self):
        if self.channel_id and self.channel_id.shop_id != self.shop_id:
            self.channel_id = False

    def action_import_orders(self):
        self.ensure_one()
        setting = self.setting_id
        shop = self.shop_id
        channel = self.channel_id
        imported_orders = self.env['sale.order'].browse()

        if not setting or not shop or not channel:
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'danger',
                'sticky': False,
                'message': _("Please select Instance, Shop, and Channel."),
            })
            return

        try:
            url = f"{setting.server}/api/orders"
            headers = {'Authorization': setting.api_key}

            max_items = 100
            offset = 0
            all_orders = []

            while True:
                params = {
                    'order_state_codes': 'STAGING,WAITING_ACCEPTANCE',
                    'channel_codes': channel.code,
                    'shop_id': shop.shop_number,
                    'max': max_items,
                    'offset': offset,
                }
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                orders_page = data.get('orders', [])

                if not orders_page:
                    break

                all_orders.extend(orders_page)

                if len(orders_page) < max_items:
                    break

                offset += max_items

            tax_model = self.env['apotheke.tax']
            partner_model = self.env['res.partner']
            sale_order_model = self.env['sale.order']
            sale_line_model = self.env['sale.order.line']

            success_count = 0

            for order in all_orders:

                # CHECK: Skip if order already exists
                existing_order = sale_order_model.search([('apotheke_order_id', '=', order.get('order_id'))], limit=1)
                if existing_order:
                    continue

                tax_ids = []

                # 1. Process order-level taxes (if any)
                for group in ('order_taxes', 'shipping_taxes', 'commission_taxes'):
                    group_taxes = order.get(group) or []
                    for tax in group_taxes:
                        code = tax.get('code')
                        rate = float(tax.get('rate', 0))
                        if not code:
                            continue
                        existing_tax = tax_model.search([
                            ('code', '=', code),
                            ('value', '=', rate),
                        ], limit=1)
                        if not existing_tax:
                            existing_tax = tax_model.create({'code': code, 'value': rate})
                        tax_ids.append(existing_tax.id)

                # 2. Add taxes from order lines
                for line in order.get('order_lines', []):
                    for tax in line.get('taxes', []):
                        code = tax.get('code')
                        rate = float(tax.get('rate', 0))
                        if not code:
                            continue
                        existing_tax = tax_model.search([
                            ('code', '=', code),
                            ('value', '=', rate),
                        ], limit=1)
                        if not existing_tax:
                            existing_tax = tax_model.create({'code': code, 'value': rate})
                        if existing_tax.id not in tax_ids:
                            tax_ids.append(existing_tax.id)

                customer_data = order.get('customer') or {}
                ap_customer_id = customer_data.get('customer_id')
                partner = partner_model.search([('apotheke_customer_id', '=', ap_customer_id)], limit=1)

                if not partner:
                    customer_data = order.get('customer') or {}

                    # Compose partner name from firstname + lastname if no organization name
                    org = customer_data.get('organization') or {}
                    if org.get('name'):
                        partner_name = org.get('name')
                    else:
                        firstname = customer_data.get('firstname') or ''
                        lastname = customer_data.get('lastname') or ''
                        partner_name = (firstname + ' ' + lastname).strip() or 'Apotheke Customer'

                    partner = partner_model.create({
                        'name': partner_name,
                        'street': org.get('street'),
                        'zip': org.get('zip'),
                        'city': org.get('city'),
                        'phone': customer_data.get('phone'),
                        'email': customer_data.get('email'),
                        'apotheke_customer_id': customer_data.get('customer_id'),
                        'type': 'contact',
                        'customer_rank': 1,
                    })

                # Create or search invoice partner to avoid duplicates
                billing = customer_data.get('billing_address') or {}
                invoice_partner = partner_model.search([
                    ('parent_id', '=', partner.id),
                    ('type', '=', 'invoice'),
                    ('street', '=', billing.get('street')),
                    ('zip', '=', billing.get('zip')),
                    ('city', '=', billing.get('city')),
                ], limit=1)
                if not invoice_partner:
                    invoice_partner = partner_model.create({
                        'name': ((customer_data.get('firstname', '') + ' ' + customer_data.get('lastname',
                                                                                               '')).strip()) or 'Billing Apotheke Customer',
                        'parent_id': partner.id,
                        'type': 'invoice',
                        'street': billing.get('street'),
                        'zip': billing.get('zip'),
                        'city': billing.get('city'),
                        'phone': billing.get('phone'),
                        'email': billing.get('email'),
                    })

                # Create or search shipping partner to avoid duplicates
                shipping = customer_data.get('shipping_address') or {}
                shipping_partner = partner_model.search([
                    ('parent_id', '=', partner.id),
                    ('type', '=', 'delivery'),
                    ('street', '=', shipping.get('street')),
                    ('zip', '=', shipping.get('zip')),
                    ('city', '=', shipping.get('city')),
                ], limit=1)
                if not shipping_partner:
                    shipping_partner = partner_model.create({
                        'name': ((customer_data.get('firstname', '') + ' ' + customer_data.get('lastname',
                                                                                               '')).strip()) or 'Billing Apotheke Customer',
                        'parent_id': partner.id,
                        'type': 'delivery',
                        'street': shipping.get('street'),
                        'zip': shipping.get('zip'),
                        'city': shipping.get('city'),
                        'phone': shipping.get('phone'),
                        'email': shipping.get('email'),
                    })

                order_reference_for_customer = (order.get('references') or {}).get('order_reference_for_customer')
                order_vals = {
                    'partner_id': partner.id,
                    'partner_invoice_id': invoice_partner.id,
                    'partner_shipping_id': shipping_partner.id,
                    'apotheke_order_id': order.get('order_id'),
                    'from_apotheke': True,
                    'channel_id': channel.id,
                    'shop_id': shop.id,
                    'order_reference_for_customer': order_reference_for_customer,
                    'apotheke_tax_ids': [(6, 0, tax_ids)],
                }

                sale_order = sale_order_model.create(order_vals)
                imported_orders |= sale_order

                for line in order.get('order_lines') or []:
                    offer = self.env['apotheke.product.offer'].search([('offer_sku', '=', line.get('offer_sku'))],
                                                                      limit=1)
                    sale_order.write({'apotheke_offer_id': offer.id if offer else False})
                    product = self.env['product.product'].search([
                        '|',
                        ('default_code', '=', line.get('product_sku')),
                        ('default_code', '=', line.get('product_shop_sku'))
                    ], limit=1)
                    if not product:
                        continue
                    # Collect taxes from line
                    line_tax_ids = []
                    for tax in line.get('taxes', []):
                        code = tax.get('code')
                        rate = float(tax.get('rate', 0))
                        if not code:
                            continue
                        apotheke_tax = tax_model.search([('code', '=', code), ('value', '=', rate)], limit=1)
                        if apotheke_tax and apotheke_tax.tax_id:
                            line_tax_ids.append(apotheke_tax.tax_id.id)


                    quantity = float(line.get("quantity", 1))
                    total_price = float(line.get("price", 0))
                    tax_amount = sum(t.get("amount", 0) for t in line.get("taxes", []))
                    subtotal = total_price - tax_amount

                    commission = float(line.get('total_commission', 0))

                    sale_line_model.create({
                        'order_id': sale_order.id,
                        'product_id': product.id,
                        'product_uom_qty': quantity,
                        'price_unit': subtotal/quantity,
                        'name': product.name or line.get('product_sku'),
                        'apotheke_line_id': line.get('order_line_id'),
                        'tax_id': [(6, 0, line_tax_ids)],
                        'commission': commission,
                        'apotheke_state': line.get('order_line_state'),
                    })

                success_count += 1

                if self.change_state_on_apotheke:
                    sale_order.accept_on_apotheke()

            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'success',
                'sticky': False,
                'message': _("Successfully imported %s orders.") % success_count,
            })

        except Exception as e:
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'danger',
                'sticky': False,
                'message': _("Order import failed: %s") % str(e),
            })

        return {
            'name': _('Imported Apotheke Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': ['|', ('id', 'in', imported_orders.ids), ('from_apotheke', '=', True)],
            'context': dict(self.env.context),
        }

