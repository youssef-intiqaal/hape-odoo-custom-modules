# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields

class ApothekeImportOperationLog(models.Model):
    _name = 'apotheke.import.operation.log'
    _description = 'Apotheke Import Operation Log'
    _order = 'create_date desc'

    setting_id = fields.Many2one('shop.apotheke.connector.setting', string='Instance', required=True)
    shop_id = fields.Many2one('shop.apotheke.shop', string='Shop', required=True)
    channel_id = fields.Many2one('shop.apotheke.shop.channel', string='Channel', required=True)

    state = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed')
    ], string='State', required=True)

    imported_order_count = fields.Integer(string='Imported Orders', default=0)
    error_message = fields.Text(string='Error Message')

    create_date = fields.Datetime(string='Execution Time', readonly=True)
