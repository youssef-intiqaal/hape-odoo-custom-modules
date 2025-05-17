# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api, _
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class ImportCategoryQueue(models.Model):
    _name = 'import.category.queue'
    _description = 'Import Category Queue'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, default= _('New'))
    setting_id = fields.Many2one(
        'shop.apotheke.connector.setting',
        string="Instance",
        required=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('partially_processed', 'Partially Processed'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ], default='draft', tracking=True)

    line_ids = fields.One2many('import.category.queue.line', 'queue_id', string='Category Lines')
    log_ids = fields.One2many('import.category.queue.log', 'queue_id', string='Logs')

    @api.model
    def create(self, vals):
        # Add the sequence
        if not vals.get('name') or vals['name'] == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('import.category.queue.sequence') or _('New')
        return super().create(vals)

    def action_synchronize_categories(self):
        ProductCategory = self.env['product.category']
        total = len(self.line_ids.filtered(lambda l: l.state == 'draft'))
        failed = 0
        proceeded = 0

        for line in self.line_ids:
            if line.state == 'processed':
                # Skip already processed line
                continue

            try:
                # Validate presence of required fields (name, code)
                if not line.code or not line.name:
                    line.state = 'failed'
                    self._create_log('error', f"[{line.code or 'N/A'}] Missing code or name.")
                    failed += 1
                    continue

                # Check for existing category in Odoo
                existing = ProductCategory.search([('code', '=', line.code)], limit=1)
                if existing:
                    line.state = 'failed'
                    self._create_log('error', f"[{line.code}] Already exists in Odoo.")
                    failed += 1
                    continue

                # Lookup parent if provided
                parent_id = False
                if line.parent_code:
                    parent = ProductCategory.search([('code', '=', line.parent_code)], limit=1)
                    if parent:
                        parent_id = parent.id
                    else:
                        self._create_log('error', f"[{line.code}] Parent with code {line.parent_code} not found.")

                # Create new category
                category = ProductCategory.create({
                    'name': line.name,
                    'code': line.code,
                    'parent_id': parent_id,
                })

                line.state = 'processed'
                proceeded += 1
                self._create_log('success', f"[{line.code}] Category '{line.name}' created successfully.")

            except Exception as e:
                line.state = 'failed'
                failed += 1
                self._create_log('error', f"[{line.code}] Error during synchronization: {str(e)}")
                _logger.exception(f"Error syncing category {line.code}: {str(e)}")

        # Update queue state based on results
        if (proceeded == total and total > 0) or all(line.state=='processed' for line in self.line_ids):
            self.state = 'processed'
            notif_type = 'success'
        elif proceeded > 0 or any(line.state=='processed' for line in self.line_ids):
            self.state = 'partially_processed'
            notif_type = 'warning'
        else:
            self.state = 'failed'
            notif_type = 'danger'

        # Show user notification with correct status
        self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
            'type': notif_type,
            'sticky': False,
            'message': _("Synchronization complete: %d succeeded, %d failed.") % (proceeded, failed),
        })

    def _create_log(self, status, message):
        self.log_ids.create({
            'queue_id': self.id,
            'timestamp': datetime.now(),
            'status': status,
            'message': message,
        })


class ImportCategoryQueueLine(models.Model):
    _name = 'import.category.queue.line'
    _description = 'Import Category Queue Line'

    queue_id = fields.Many2one('import.category.queue', string='Queue', required=True, ondelete='cascade')
    level = fields.Integer(string='Level')
    code = fields.Char(string='Code')
    name = fields.Char(string='Name')
    parent_code = fields.Char(string='Parent Code')
    parent_name = fields.Char(string='Parent Name')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ], default='draft')


class ImportCategoryQueueLog(models.Model):
    _name = 'import.category.queue.log'
    _description = 'Import Category Queue Log'

    queue_id = fields.Many2one('import.category.queue', string='Queue', ondelete='cascade')
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now)
    message = fields.Text(string='Log Message')
    status = fields.Selection([('info', 'Info'), ('success', 'Success'), ('error', 'Error')], default='info')
