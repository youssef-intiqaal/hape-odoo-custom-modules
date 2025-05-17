# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api, _
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class ImportProductQueue(models.Model):
    _name = 'import.product.queue'
    _description = 'Import Product Queue'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=_('New'))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('partially_processed', 'Partially Processed'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ], default='draft', tracking=True)

    line_ids = fields.One2many('import.product.queue.line', 'queue_id', string='Product Lines')
    log_ids = fields.One2many('import.product.queue.log', 'queue_id', string='Logs')

    @api.model
    def create(self, vals):
        """
        Override create to assign a sequence number to the queue name if it's not set.
        """
        if not vals.get('name') or vals['name'] == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('import.product.queue.sequence') or _('New')
        return super().create(vals)

    def action_create_apotheke_products(self):
        """
        Process each queue line:
        - Validates required fields
        - Skips if product already exists
        - Creates new 'apotheke.product' records
        - Logs successes and failures
        - Updates queue state and sends user notification
        """
        ApothekeProduct = self.env['apotheke.product']
        total = len(self.line_ids.filtered(lambda l: l.state == 'draft'))
        proceeded = 0
        failed = 0

        for line in self.line_ids:
            if line.state == 'processed':
                continue

            try:
                if not line.name or (not line.sku and not line.ean):
                    line.state = 'failed'
                    self._create_log('error', f"[{line.sku or 'N/A'}] Missing name, SKU or EAN.")
                    failed += 1
                    continue

                # Check for existing product by SKU or EAN
                existing = ApothekeProduct.search([
                    '|',
                    ('sku', '=', line.sku),
                    ('ean', '=', line.ean),
                ], limit=1)
                if existing:
                    line.state = 'failed'
                    self._create_log('error', f"[{line.sku}] Already exists in Apotheke Products.")
                    failed += 1
                    continue

                # Create Apotheke Product
                ApothekeProduct.create({
                    'name': line.name,
                    'sku': line.sku,
                    'ean': line.ean,
                    'main_image': line.main_image,
                    'brand': line.brand,
                    'category_id': line.category_id.id,
                })

                line.state = 'processed'
                proceeded += 1
                self._create_log('success', f"[{line.sku}] Apotheke Product created successfully.")

            except Exception as e:
                line.state = 'failed'
                failed += 1
                self._create_log('error', f"[{line.sku}] Error during creation: {str(e)}")
                _logger.exception(f"Error creating apotheke.product for {line.sku}: {str(e)}")

        # Update queue state
        if (proceeded == total and total > 0) or all(l.state == 'processed' for l in self.line_ids):
            self.state = 'processed'
            notif_type = 'success'
        elif proceeded > 0 or any(l.state == 'processed' for l in self.line_ids):
            self.state = 'partially_processed'
            notif_type = 'warning'
        else:
            self.state = 'failed'
            notif_type = 'danger'

        self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
            'type': notif_type,
            'sticky': False,
            'message': _("Creation complete: %d succeeded, %d failed.") % (proceeded, failed),
        })

    def _create_log(self, status, message):
        """
        Utility method to create a log entry.
        :param status: Log type: info, success, or error
        :param message: Log message content
        """
        self.log_ids.create({
            'queue_id': self.id,
            'timestamp': datetime.now(),
            'status': status,
            'message': message,
        })


class ImportProductQueueLine(models.Model):
    _name = 'import.product.queue.line'
    _description = 'Import Product Queue Line'

    queue_id = fields.Many2one('import.product.queue', string='Queue', required=True, ondelete='cascade')
    category_id = fields.Many2one('product.category', string='Category')
    name = fields.Char(string='Name')
    sku = fields.Char(string='SKU')
    ean = fields.Char(string='EAN')
    brand = fields.Char(string='Brand')
    main_image = fields.Binary(string='Main Image')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ], default='draft')


class ImportProductQueueLog(models.Model):
    _name = 'import.product.queue.log'
    _description = 'Import Product Queue Log'

    queue_id = fields.Many2one('import.product.queue', string='Queue', ondelete='cascade')
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now)
    message = fields.Text(string='Log Message')
    status = fields.Selection([('info', 'Info'), ('success', 'Success'), ('error', 'Error')], default='info')
