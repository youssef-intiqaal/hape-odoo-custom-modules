# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api


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
    apotheke_tax_id = fields.Many2one('apotheke.tax', string="Apotheke Tax")

    @api.depends_context('company')
    def _compute_company_currency_id(self):
        self.company_currency_id = self.env.company.currency_id
