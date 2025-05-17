# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    apotheke_customer_id = fields.Char(string="Apotheke ID", readonly=True)

