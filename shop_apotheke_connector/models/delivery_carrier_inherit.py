# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import fields, models


class ProviderGelato(models.Model):
    _inherit = 'delivery.carrier'

    code = fields.Char(string='Code')
    shop_ids = fields.Many2many('shop.apotheke.shop', string='Shops')
