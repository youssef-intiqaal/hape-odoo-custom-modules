# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields

class ProductCategory(models.Model):
    _inherit = 'product.category'

    code = fields.Char(string='Code', required=True)
