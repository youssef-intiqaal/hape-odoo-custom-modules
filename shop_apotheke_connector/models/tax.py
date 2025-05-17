# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api

class ApothekeTax(models.Model):
    _name = 'apotheke.tax'
    _description = 'Shop Apotheke Tax'
    _inherit = ['mail.thread']
    _rec_name = 'code'

    tax_id = fields.Many2one('account.tax', string='Odoo Tax')
    code = fields.Char(string='Tax Code', required=True)
    value = fields.Float(string='Tax Value (%)', required=True)

    @api.model
    def create(self, vals):
        # Link with Odoo Tax
        if vals.get('value') is not None:
            tax = self.env['account.tax'].search([
                ('amount', '=', vals['value']),
                ('type_tax_use', '=', 'sale'),
            ], limit=1)
            if tax:
                vals['tax_id'] = tax.id

        return super(ApothekeTax, self).create(vals)
