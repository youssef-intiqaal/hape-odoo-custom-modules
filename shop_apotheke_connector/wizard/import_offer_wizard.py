# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api, _
import requests


class ImportOfferWizard(models.TransientModel):
    _name = 'import.offer.wizard'
    _description = 'Import Offer Wizard'

    setting_id = fields.Many2one(
        'shop.apotheke.connector.setting',
        string='Instance',
        required=True
    )
    shop_id = fields.Many2one(
        'shop.apotheke.shop',
        string='Shop',
        required=True,
        domain="[('setting_id', '=', setting_id)]"
    )

    @api.onchange('setting_id')
    def _onchange_setting_id(self):
        if self.shop_id and self.shop_id.setting_id != self.setting_id:
            self.shop_id = False

    def action_import_offers(self):
        self.ensure_one()
        queue = self.env['import.offer.queue'].create({
            'setting_id': self.setting_id.id,
        })
        log_model = self.env['import.offer.queue.log']
        setting = self.setting_id

        if not setting or not self.shop_id:
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'danger',
                'sticky': False,
                'message': _("Missing Instance or Shop."),
            })
            return

        try:
            url = f"{setting.server}/api/offers"
            headers = {'Authorization': f'{setting.api_key}'}

            max_items = 100  # max per page supported by the API
            offset = 0
            all_offers = []

            # Loop to fetch all pages
            while True:
                params = {
                    'shop_id': self.shop_id.shop_number,
                    'max': max_items,
                    'offset': offset,
                }
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                offers_page = data.get('offers', [])

                if not offers_page:
                    break  # no more offers

                all_offers.extend(offers_page)

                if len(offers_page) < max_items:
                    break  # last page

                offset += max_items

            channel_model = self.env['shop.apotheke.shop.channel']
            tax_model = self.env['apotheke.tax']

            success_count = 0

            for offer in all_offers:

                sku = offer.get('product_sku')
                product = self.env['apotheke.product'].search([
                    ('sku', '=', sku),
                ], limit=1)

                ean = False
                product_references = offer.get('product_references', [])
                for ref in product_references:
                    if ref.get('reference_type') == 'EAN':
                        ean = ref.get('reference')

                # Fallback to EAN if product not found by SKU
                if not product and ean:
                    product = self.env['apotheke.product'].search([
                        ('ean', '=', ean),
                    ], limit=1)

                channel_ids = channel_model.search([
                    ('code', 'in', offer.get('channels', [])),
                    ('shop_id', '=', self.shop_id.id)
                ]).ids

                queue_line= self.env['import.offer.queue.line'].create({
                    'queue_id': queue.id,
                    'shop_id': self.shop_id.id,
                    'offer_sku': offer.get('shop_sku'),
                    'offer_active': offer.get('active', True),
                    'shop_offer_id': str(offer.get('offer_id')),
                    'price': offer.get('price'),
                    'quantity': offer.get('quantity'),
                    'state_code': offer.get('state_code'),
                    'start_date': offer.get('available_start_date'),
                    'end_date': offer.get('available_end_date'),
                    'product_id': product.id if product else False,
                    'product_sku': sku if sku else False,
                    'product_ean': ean if ean else False,
                    'channel_ids': [(6, 0, channel_ids)]
                })

                # === Tax check and create ===
                additional_fields = offer.get('offer_additional_fields', [])
                created_tax_codes = []

                for field in additional_fields:
                    code = field.get('code', '')
                    if 'tax' in code.lower():
                        existing_tax = tax_model.search([('code', '=', code), ('company_id', '=', self.env.company.id)], limit=1)
                        if not existing_tax:
                            tax = tax_model.create({
                                'tax_id': False,
                                'code': code,
                                'value': float(field.get('value') or 0),
                                'company_id': self.env.company.id
                            })
                            queue_line.write({'apotheke_tax_id': tax.id})
                            created_tax_codes.append(code)
                        else:
                            queue_line.write({'apotheke_tax_id': existing_tax.id})

                if created_tax_codes:
                    self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                        'type': 'success',
                        'sticky': False,
                        'message': _("Created new tax records for codes: %s") % ', '.join(created_tax_codes),
                    })

                success_count += 1

            log_model.create({
                'queue_id': queue.id,
                'message': _('Successfully imported %s offers.') % success_count,
                'status': 'success',
            })

            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'success',
                'sticky': False,
                'message': _("Offer import completed successfully. Total: %s") % success_count,
            })

        except Exception as e:
            queue.state = 'failed'
            log_model.create({
                'queue_id': queue.id,
                'message': f"Failed to fetch data: {str(e)}",
                'status': 'error',
            })
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'danger',
                'sticky': False,
                'message': _("Failed to import offers: %s") % str(e),
            })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Offer Queue'),
            'res_model': 'import.offer.queue',
            'view_mode': 'form',
            'res_id': queue.id,
            'target': 'current',
        }
