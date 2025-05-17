# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class ImportOfferQueue(models.Model):
    _name = 'import.offer.queue'
    _description = 'Import Offer Queue'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, default=_('New'))
    setting_id = fields.Many2one('shop.apotheke.connector.setting', string='Instance', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('partially_processed', 'Partially Processed'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ], default='draft', tracking=True)

    line_ids = fields.One2many('import.offer.queue.line', 'queue_id', string='Offer Lines')
    log_ids = fields.One2many('import.offer.queue.log', 'queue_id', string='Logs')
    has_missing_products = fields.Boolean(
        string='Has Missing Products',
        compute='_compute_has_missing_products'
    )
    offers_created = fields.Boolean(default=False)

    @api.depends('line_ids.product_id')
    def _compute_has_missing_products(self):
        for queue in self:
            queue.has_missing_products = any(not line.product_id for line in queue.line_ids)

    @api.model
    def create(self, vals):
        if not vals.get('name') or vals['name'] == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('import.offer.queue.sequence') or _('New')
        return super().create(vals)

    def _create_log(self, status, message):
        self.env['import.offer.queue.log'].create({
            'queue_id': self.id,
            'status': status,
            'message': message,
        })

    def action_update_apotheke_products(self):
        OfferModel = self.env['apotheke.product.offer']

        total = len(self.line_ids.filtered(lambda l: l.state == 'draft'))
        proceeded = 0
        failed = 0

        for line in self.line_ids:
            if line.state == 'processed':
                continue
            product_name = line.product_id.name if line.product_id else 'Unknown Product'
            try:
                if not line.product_id:
                    line.state = 'failed'
                    self._create_log('error', f"[{product_name}] No related Apotheke Product found.")
                    failed += 1
                    continue

                vals = {
                    'shop_id': line.shop_id.id,
                    'offer_sku': line.offer_sku or '',
                    'offer_active': line.offer_active,
                    'shop_offer_id': line.shop_offer_id,
                    'product_id': line.product_id.id,
                    'product_sku': line.product_sku,
                    'product_ean': line.product_ean,
                    'price': line.price,
                    'quantity': line.quantity,
                    'state_code': line.state_code or '',
                    'start_date': line.start_date,
                    'end_date': line.end_date,
                    'channel_ids': [(6, 0, line.channel_ids.ids)],
                }

                # Check for existing offer by shop_offer_id + shop_id
                existing = OfferModel.search([
                    ('shop_offer_id', '=', line.shop_offer_id),
                    ('shop_id', '=', line.shop_id.id)
                ], limit=1)

                if existing:
                    existing.write(vals)
                    self._create_log('success', f"[{product_name}] Updated existing offer ID {existing.id}.")
                else:
                    OfferModel.create(vals)
                    self._create_log('success', f"[{product_name}] Created new offer.")

                line.state = 'processed'
                proceeded += 1

            except Exception as e:
                line.state = 'failed'
                failed += 1
                error_message = f"[Line {line.id}] Error: {str(e)}"
                self._create_log('error', error_message)
                _logger.exception(error_message)

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

        # Send notification to user
        try:
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': notif_type,
                'sticky': False,
                'message': _("Update complete: %d succeeded, %d failed.") % (proceeded, failed),
            })
        except Exception as notif_err:
            _logger.error(f"Failed to send notification: {notif_err}")

        return True
    def create_offers(self):
        OfferModel = self.env['apotheke.product.offer']

        total = len(self.line_ids.filtered(lambda l: l.state == 'draft'))
        proceeded = 0
        failed = 0

        for line in self.line_ids:
            product_name = line.product_id.name if line.product_id else 'Unknown Product'
            try:
                if not line.product_id:
                    line.state = 'failed'
                    self._create_log('error', f"[{product_name}] No related Apotheke Product found.")
                    failed += 1
                    continue

                vals = {
                    'shop_id': line.shop_id.id,
                    'offer_sku': line.offer_sku or '',
                    'offer_active': line.offer_active,
                    'shop_offer_id': line.shop_offer_id,
                    'product_id': line.product_id.id,
                    'product_sku': line.product_sku,
                    'product_ean': line.product_ean,
                    'price': line.price,
                    'quantity': line.quantity,
                    'state_code': line.state_code or '',
                    'start_date': line.start_date,
                    'end_date': line.end_date,
                    'channel_ids': [(6, 0, line.channel_ids.ids)],
                }

                # Check for existing offer by shop_offer_id + shop_id
                existing = OfferModel.search([
                    ('shop_offer_id', '=', line.shop_offer_id),
                    ('shop_id', '=', line.shop_id.id)
                ], limit=1)

                if existing:
                    existing.write(vals)
                    self._create_log('success', f"[{product_name}] Updated existing offer ID {existing.id}.")
                else:
                    OfferModel.create(vals)
                    self._create_log('success', f"[{product_name}] Created new offer.")

                line.state = 'processed'
                proceeded += 1

            except Exception as e:
                line.state = 'failed'
                failed += 1
                error_message = f"[Line {line.id}] Error: {str(e)}"
                self._create_log('error', error_message)
                _logger.exception(error_message)

        # Update queue state
        if (proceeded == total and total > 0) or all(l.state == 'processed' for l in self.line_ids):
            self.state = 'processed'
            notif_type = 'success'
            self.offers_created = True
        elif proceeded > 0 or any(l.state == 'processed' for l in self.line_ids):
            self.state = 'partially_processed'
            notif_type = 'warning'
        else:
            self.state = 'failed'
            notif_type = 'danger'

        # Send notification to user
        try:
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': notif_type,
                'sticky': False,
                'message': _("Update complete: %d succeeded, %d failed.") % (proceeded, failed),
            })
        except Exception as notif_err:
            _logger.error(f"Failed to send notification: {notif_err}")

        return True

    def action_generate_products(self):
        ApothekeProduct = self.env['apotheke.product']
        created_count = 0
        failed_count = 0

        for queue in self:
            for line in queue.line_ids.filtered(lambda l: not l.product_id):
                try:
                    product_name = line.product_ean or line.product_sku or _('Unnamed Product')
                    product = ApothekeProduct.create({
                        'name': product_name,
                        'sku': line.product_sku,
                        'ean': line.product_ean,
                        'setting_id': queue.setting_id.id,
                        'shop_ids': [(4, line.shop_id.id)] if line.shop_id else [],
                    })
                    line.product_id = product.id
                    line.state = 'processed'

                    if line.product_ean:
                        msg = f"Created product for line {line.id} using EAN {line.product_ean}."
                    elif line.product_sku:
                        msg = f"Created product for line {line.id} using SKU {line.product_sku}."
                    else:
                        msg = f"Created product for line {line.id} with no EAN or SKU."

                    queue._create_log('success', msg)
                    created_count += 1
                except Exception as e:
                    line.state = 'failed'
                    queue._create_log('error', f"Failed to create product for line {line.id}: {str(e)}")
                    failed_count += 1
                    _logger.exception("Error creating product from offer queue line")

            # Update the queue state depending on line states
            total_lines = len(queue.line_ids)
            processed_lines = len(queue.line_ids.filtered(lambda l: l.state == 'processed'))
            failed_lines = len(queue.line_ids.filtered(lambda l: l.state == 'failed'))

            if processed_lines == total_lines and total_lines > 0:
                queue.state = 'processed'
                notif_type = 'success'
            elif processed_lines > 0:
                queue.state = 'partially_processed'
                notif_type = 'warning'
            else:
                queue.state = 'failed'
                notif_type = 'danger'

            # Send user notification via bus
            message = _("Product generation complete: %d created, %d failed.") % (created_count, failed_count)
            try:
                self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                    'type': notif_type,
                    'sticky': False,
                    'message': message,
                })
            except Exception as notif_err:
                _logger.error(f"Failed to send notification: {notif_err}")


class ImportOfferQueueLine(models.Model):
    _name = 'import.offer.queue.line'
    _description = 'Import Offer Queue Line'

    queue_id = fields.Many2one('import.offer.queue', string='Queue', required=True, ondelete='cascade')
    product_id = fields.Many2one('apotheke.product', string='Product', readonly=True)
    shop_id = fields.Many2one('shop.apotheke.shop', string='Shop', required=True, readonly=True)
    offer_sku = fields.Char(string='Offer SKU', readonly=True)
    offer_active = fields.Boolean(string='Active Offer', default=True, readonly=True)
    shop_offer_id = fields.Char(string='Shop Offer ID', readonly=True)
    product_sku = fields.Char(string='Product SKU', readonly=True)
    product_ean = fields.Char(string='Product EAN', readonly=True)
    price = fields.Float(string='Price', readonly=True)
    quantity = fields.Integer(string='Quantity', readonly=True)
    channel_ids = fields.Many2many(
        'shop.apotheke.shop.channel',
        'import_offer_queue_line_channel_rel',
        'queue_line_id',
        'channel_id',
        string='Channels',
        domain="[('shop_id', '=', shop_id)]",
        readonly=True
    )

    state_code = fields.Char(string='State Code', readonly=True)
    start_date = fields.Date(string='Start Date', readonly=True)
    end_date = fields.Date(string='End Date', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ], default='draft')

    company_currency_id = fields.Many2one('res.currency', compute='_compute_company_currency_id', readonly=True)
    apotheke_tax_id = fields.Many2one('apotheke.tax', string="Apotheke Tax")

    @api.depends_context('company')
    def _compute_company_currency_id(self):
        self.company_currency_id = self.env.company.currency_id


class ImportOfferQueueLog(models.Model):
    _name = 'import.offer.queue.log'
    _description = 'Import Offer Queue Log'

    queue_id = fields.Many2one('import.offer.queue', string='Queue', ondelete='cascade')
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now)
    message = fields.Text(string='Log Message')
    status = fields.Selection([('info', 'Info'), ('success', 'Success'), ('error', 'Error')], default='info')
