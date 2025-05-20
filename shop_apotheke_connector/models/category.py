# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class ApothekeCategory(models.Model):
    _name = 'apotheke.category'
    _description = 'Shop Apotheke Product'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    code = fields.Char(string="Code", required=True)
    name = fields.Char(string="Name", required=True)
    parent_id = fields.Many2one(
        'apotheke.category',
        string="Parent Category",
        ondelete='set null'
    )
    setting_id = fields.Many2one(
        'shop.apotheke.connector.setting',
        string="Instance",
        required=True
    )

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'The category code must be unique.'),
    ]

    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100):
        """
        Allows searching for categories by either name or code in search bars or Many2one fields.

        :param name: The string entered by the user.
        :param args: Additional domain filters.
        :param operator: Search operator (usually 'ilike').
        :param limit: Max number of records to return.
        :return: List of (id, display_name) tuples.
        """
        args = args or []
        domain = ['|', ('name', operator, name), ('code', operator, name)]
        return self.search(domain + args, limit=limit).name_get()
