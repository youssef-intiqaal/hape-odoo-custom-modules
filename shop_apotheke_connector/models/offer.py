# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api
import requests
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ApothekeProductOffer(models.Model):
    _name = 'apotheke.product.offer'
    _description = 'Shop Apotheke Product Offer'
    _inherit = ['mail.thread']
    _rec_name = 'shop_offer_id'

    shop_id = fields.Many2one('shop.apotheke.shop', string='Shop', readonly=True)
    offer_sku = fields.Char(string='Offer SKU', required=False, readonly=True)
    offer_active = fields.Boolean(string='Active Offer', default=True, readonly=True)
    shop_offer_id = fields.Char(string='Shop Offer ID', readonly=True)
    product_sku = fields.Char(string='Product SKU', readonly=True)
    product_ean = fields.Char(string='Product EAN', readonly=True)
    price = fields.Float(string='Price', required=True)
    quantity = fields.Integer(string='Quantity', required=True)
    channel_ids = fields.Many2many(
        'shop.apotheke.shop.channel',
        'apotheke_offer_channel_rel',
        'offer_id',
        'channel_id',
        string='Channels',
        domain="[('shop_id', '=', shop_id)]",
        readonly=True
    )
    state_code = fields.Char(string='State Code', readonly=True)
    start_date = fields.Date(string='Start Date', readonly=True)
    end_date = fields.Date(string='End Date', readonly=True)

    product_id = fields.Many2one('apotheke.product', string='Related Product', required=True, ondelete='cascade',
                                 index=True, readonly=True)

    company_currency_id = fields.Many2one('res.currency', compute='_compute_company_currency_id')
    apotheke_tax_id = fields.Many2one('apotheke.tax', string="Apotheke Tax", readonly=True)
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Pricelist',
        tracking=True
    )
    computed_pricelist_price = fields.Float(
        string='Pricelist Price',
        compute='_compute_pricelist_price',
        store=False,
        readonly=True
    )

    _sql_constraints = [
        ('unique_offer_sku', 'unique(offer_sku)', 'Offer SKU must be unique.'),
        ('unique_shop_offer_id', 'unique(shop_offer_id)', 'Shop Offer ID must be unique.')
    ]

    @api.depends('pricelist_id', 'product_id.odoo_product_id')
    def _compute_pricelist_price(self):
        for rec in self:
            price = 0.0
            if rec.pricelist_id and rec.product_id.odoo_product_id:
                product = rec.product_id.odoo_product_id.product_variant_id
                quantity = 1.0
                try:
                    price = rec.pricelist_id._get_product_price(product, quantity=quantity)
                except Exception as e:
                    _logger.warning(f"Could not compute pricelist price: {e}")
            rec.computed_pricelist_price = price

    @api.onchange('pricelist_id')
    def _onchange_pricelist_id(self):
        """Update price based on selected pricelist when changed in the form view."""
        for rec in self:
            if rec.pricelist_id and rec.product_id.odoo_product_id:
                try:
                    # Using variant (product.product), not template
                    product = rec.product_id.odoo_product_id.product_variant_id

                    price = rec.pricelist_id._get_product_price(
                        product,
                        quantity=1.0,
                        uom=product.uom_id,
                        currency=rec.pricelist_id.currency_id,
                        date=fields.Date.context_today(self),
                    )

                    rec.price = price
                except Exception as e:
                    _logger.warning(f"Error getting product price from pricelist: {e}")
                    rec.price = 0.0

    @api.depends_context('company')
    def _compute_company_currency_id(self):
        self.company_currency_id = self.env.company.currency_id

    def write(self, vals):
        """
        Override the write method to automatically update the offer on Shop Apotheke
        if either the price or quantity is modified.
        """
        update_needed = False
        fields_to_check = ['price', 'quantity']

        for record in self:
            new_price = vals.get('price', record.price)
            new_quantity = vals.get('quantity', record.quantity)

            # Only send API update if price or quantity actually changed
            if 'price' in vals or 'quantity' in vals:
                update_needed = True

                try:
                    setting = record.shop_id.setting_id
                    if not setting:
                        raise UserError("No connector setting found for the shop.")

                    url = f"{setting.server}/api/offers"
                    headers = {
                        "Authorization": f"{setting.api_key}",
                        "Content-Type": "application/json",
                    }
                    params = {
                        "shop_id": record.shop_id.shop_number
                    }
                    payload = {
                        "offers": [
                            {
                                "price": new_price,
                                "product_id": record.product_ean,
                                "product_id_type": "EAN",
                                "quantity": new_quantity,
                                "state_code": record.state_code,
                                "shop_sku": record.offer_sku,
                            }
                        ]
                    }

                    response = requests.post(url, json=payload, headers=headers, params=params)
                    response.raise_for_status()
                    resp_data = response.json()

                    self._send_notification('success', f"Offer update successful for {record.offer_sku}")
                except Exception as e:
                    self._send_notification('danger', f"Offer update failed for {record.offer_sku}: {str(e)}")

        # Always proceed with the write after (or even if) API fails
        return super(ApothekeProductOffer, self).write(vals)

    def _send_notification(self, notif_type, message):
        self.env['bus.bus']._sendone(
            self.env.user.partner_id,
            'simple_notification',
            {
                'type': notif_type,
                'sticky': False,
                'message': message,
            }
        )
