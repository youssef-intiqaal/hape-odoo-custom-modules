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
                    'order_state_codes': 'WAITING_ACCEPTANCE',
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

            if not all_orders:
                self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                    'type': 'info',
                    'sticky': False,
                    'message': _("No new orders to import."),
                })
                return

            queue = self.env['import.order.queue'].create({
                'setting_id': setting.id,
                'shop_id': shop.id,
                'channel_id': channel.id,
                'change_state_on_apotheke': self.change_state_on_apotheke,
            })
            partner_model = self.env['res.partner']
            queue_line_vals = []
            for order in all_orders:
                try:
                    customer_data = order.get('customer') or {}
                    partner = self.env['res.partner'].search([
                        ('apotheke_customer_id', '=', customer_data.get('customer_id'))
                    ], limit=1)

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
                        ('type', '=', 'invoice')
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
                        ('type', '=', 'delivery')
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

                    # Taxes
                    tax_ids = []
                    for group in ('order_taxes', 'shipping_taxes', 'commission_taxes'):
                        for tax in order.get(group) or []:
                            code = tax.get('code')
                            rate = float(tax.get('rate', 0))
                            if code:
                                ap_tax = self.env['apotheke.tax'].search([
                                    ('code', '=', code), ('value', '=', rate), ('company_id', '=', self.env.company.id)

                                ], limit=1)
                                if not ap_tax:
                                    ap_tax = self.env['apotheke.tax'].create({'code': code, 'value': rate, 'company_id': self.env.company.id})
                                if ap_tax.id not in tax_ids:
                                    tax_ids.append(ap_tax.id)

                    line_lines = []
                    for line in order.get('order_lines', []):
                        try:
                            product = self.env['product.product'].search([
                                ('default_code', '=', line.get('product_sku'))
                            ], limit=1)

                            if product:
                                template = product.product_tmpl_id
                                apotheke_product_obj = self.env['apotheke.product']
                                apotheke_product = apotheke_product_obj.search([
                                    ('sku', '=', line.get('product_sku'))
                                ], limit=1)

                                # Case 1: Apotheke product found
                                if apotheke_product:
                                    if not apotheke_product.odoo_product_id:
                                        apotheke_product.odoo_product_id = template.id
                                        template.transferred_to_apotheke = True
                                        apotheke_product.shop_ids = [(4, shop.id)]

                                # Case 2: Not found in apotheke.product
                                else:
                                    # Create a new apotheke.product and link to template
                                    apotheke_product_obj.create({
                                        'name': product.name or line.get('product_title'),
                                        'sku': line.get('product_sku'),
                                        'ean': product.product_tmpl_id.ean,
                                        'brand': product.product_brand_id.name if hasattr(product,
                                                                                          'product_brand_id') else '',
                                        'odoo_product_id': template.id,
                                        'state_sync_odoo': 'synchronized',
                                        'setting_id': setting.id,
                                        'shop_ids': [(4, shop.id)]
                                    })
                                    template.transferred_to_apotheke = True

                            else:
                                # Case 3: Product not found in Odoo, create template and product
                                product_template = self.env['product.template'].create({
                                    'name': line.get('product_title') or 'Unnamed Apotheke Product',
                                    'default_code': line.get('product_sku'),
                                    'type': 'consu',
                                    'is_storable': True,
                                    'transferred_to_apotheke': True,
                                })
                                product = product_template.product_variant_id

                                # Then create apotheke.product linked to this new template
                                self.env['apotheke.product'].create({
                                    'name': product_template.name,
                                    'sku': product_template.default_code,
                                    'ean': product_template.barcode,
                                    'odoo_product_id': product_template.id,
                                    'state_sync_odoo': 'synchronized',
                                    'setting_id': setting.id,
                                    'shop_ids': [(4, shop.id)]
                                })

                            # Line-level taxes
                            line_tax_ids = []
                            for tax in line.get('taxes', []):
                                code = tax.get('code')
                                rate = float(tax.get('rate', 0))
                                if code:
                                    ap_tax = self.env['apotheke.tax'].search([
                                        ('code', '=', code), ('value', '=', rate), ('company_id', '=', self.env.company.id)
                                    ], limit=1)
                                    if not ap_tax:
                                        ap_tax = self.env['apotheke.tax'].create({'code': code, 'value': rate, 'company_id': self.env.company.id})
                                    if ap_tax.id not in tax_ids:
                                        tax_ids.append(ap_tax.id)
                                    if ap_tax.id not in line_tax_ids:
                                        line_tax_ids.append(ap_tax.id)

                            quantity = float(line.get("quantity", 1))
                            total_price = float(line.get("price", 0))
                            tax_amount = sum(t.get("amount", 0) for t in line.get("taxes", []))
                            subtotal = total_price - tax_amount

                            line_lines.append((0, 0, {
                                'product_id': product.id if product else False,
                                'product_uom_qty': quantity,
                                'price_unit': subtotal/quantity,
                                'commission': line.get('total_commission', 0),
                                'name': line.get('product_title'),
                                'apotheke_line_id': line.get('order_line_id'),
                                'tax_id': [(6, 0, line_tax_ids)],
                                'product_sku': line.get('product_sku') or line.get('product_shop_sku'),
                                'apotheke_state': order.get('order_state'),
                            }))

                        except Exception as line_error:
                            self.env['import.order.queue.line.log'].create({
                                'order_line_queue_id': False,
                                'message': _("Failed to process line: %s") % str(line_error),
                                'status': 'error',
                            })

                    queue_line = self.env['import.order.queue.line'].create({
                        'queue_id': queue.id,
                        'apotheke_order_id': order.get('order_id'),
                        'partner_id': partner.id if partner else False,
                        'order_reference_for_customer': (order.get('references') or {}).get(
                            'order_reference_for_customer'),
                        'apotheke_tax_ids': [(6, 0, tax_ids)],
                        'order_lines_ids': line_lines,
                    })

                    # Success log for the order
                    self.env['import.order.queue.log'].create({
                        'order_queue_id': queue.id,
                        'message': _("Order %s processed successfully.") % order.get('order_id'),
                        'status': 'success',
                    })

                    # Success log for the order lines
                    for order_line in queue_line.order_lines_ids:
                        self.env['import.order.queue.line.log'].create({
                            'order_line_queue_id': queue_line.id,
                            'message': _("Line %s successfully added to queue.") % order_line.apotheke_line_id,
                            'status': 'success',
                        })

                except Exception as order_error:
                    # Failure log (line and queue)
                    self.env['import.order.queue.line.log'].create({
                        'order_line_queue_id': False,
                        'message': _("Failed to process order %s: %s") % (order.get('order_id'), str(order_error)),
                        'status': 'error',
                    })

                    self.env['import.order.queue.log'].create({
                        'order_queue_id': queue.id,
                        'message': _("Error processing order %s: %s") % (order.get('order_id'), str(order_error)),
                        'status': 'error',
                    })

            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'success',
                'sticky': False,
                'message': _("Successfully queued %s orders.") % len(all_orders),
            })

            return {
                'type': 'ir.actions.act_window',
                'name': _('Order Import Queue'),
                'res_model': 'import.order.queue',
                'view_mode': 'form',
                'res_id': queue.id,
            }

        except Exception as e:
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'danger',
                'sticky': False,
                'message': _("Order import failed: %s") % str(e),
            })
