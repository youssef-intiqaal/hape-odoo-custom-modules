from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ImportOrderQueue(models.Model):
    _name = 'import.order.queue'
    _description = 'Import Order Queue'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, copy=False, default=_('New'))
    setting_id = fields.Many2one('shop.apotheke.connector.setting', string='Instance', required=True, readonly=True, copy=False)
    shop_id = fields.Many2one('shop.apotheke.shop', string='Shop', domain="[('setting_id', '=', setting_id)]",
                              required=True, readonly=True)
    channel_id = fields.Many2one('shop.apotheke.shop.channel', string='Channel', domain="[('shop_id', '=', shop_id)]",
                                 required=True, readonly=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('partially_processed', 'Partially Processed'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ], compute='_compute_state', store=True, tracking=True)

    line_ids = fields.One2many('import.order.queue.line', 'queue_id', string='Orders', readonly=True)
    log_ids = fields.One2many('import.order.queue.log', 'order_queue_id', string='Logs', readonly=True)
    change_state_on_apotheke = fields.Boolean(string='Change state on Shop Apotheke', default=False)

    @api.depends('line_ids.state')
    def _compute_state(self):
        for record in self:
            states = record.line_ids.mapped('state')
            if not states:
                record.state = 'draft'
            elif all(state == 'processed' for state in states):
                record.state = 'processed'
            elif all(state == 'failed' for state in states):
                record.state = 'failed'
            elif any(state in ('processed', 'failed') for state in states):
                record.state = 'partially_processed'
            else:
                record.state = 'draft'

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('import.order.queue.sequence') or _('New')
        return super().create(vals)

    def action_create_orders(self):
        Bus = self.env['bus.bus']
        SaleOrder = self.env['sale.order']
        SaleOrderLine = self.env['sale.order.line']

        for queue in self:
            all_states = []
            for line in queue.line_ids:
                line_log_msgs = []
                # Search if the Sale Order already exists
                if SaleOrder.search_count([('apotheke_order_id', '=', line.apotheke_order_id)]):
                    line.state = 'failed'
                    msg = f"Order {line.apotheke_order_id} already exists. Skipping."
                    line_log_msgs.append((0, 0, {
                        'message': msg, 'status': 'error'
                    }))
                    line.log_ids = line_log_msgs
                    all_states.append(line.state)
                    line.order_lines_ids.write({'state': 'failed'})
                    continue

                if not line.partner_id:
                    line.state = 'failed'
                    msg = f"No customer linked for Apotheke Order {line.apotheke_order_id}."
                    line_log_msgs.append((0, 0, {
                        'message': msg, 'status': 'error'
                    }))
                    line.log_ids = line_log_msgs
                    all_states.append(line.state)
                    line.order_lines_ids.write({'state': 'failed'})
                    continue

                try:
                    sale_order_vals = {
                        'partner_id': line.partner_id.id,
                        'apotheke_order_id': line.apotheke_order_id,
                        'order_reference_for_customer': line.order_reference_for_customer,
                        'apotheke_tax_ids': [(6, 0, line.apotheke_tax_ids.ids)],
                        'from_apotheke': True,
                        'shop_id': queue.shop_id.id,
                        'channel_id': queue.channel_id.id,
                    }
                    order = SaleOrder.create(sale_order_vals)

                    line_states = []
                    for ol in line.order_lines_ids:
                        if not ol.product_id:
                            msg = f"Missing product for line {ol.name or ol.apotheke_line_id}."
                            ol.state = 'failed'
                            line_states.append('failed')
                            line_log_msgs.append((0, 0, {
                                'message': msg, 'status': 'error'
                            }))
                            continue

                        so_line = SaleOrderLine.create({
                            'order_id': order.id,
                            'product_id': ol.product_id.id,
                            'product_uom_qty': ol.product_uom_qty,
                            'price_unit': ol.price_unit,
                            'name': ol.name or ol.product_id.name,
                            'apotheke_line_id': ol.apotheke_line_id,
                            'commission': ol.commission,
                            'apotheke_state': ol.apotheke_state,
                            'tax_id': [(6, 0, ol.tax_id.mapped('tax_id').ids)],
                        })
                        ol.state = 'processed'
                        line_states.append('processed')

                    # Confirm the order and accept it in Shop Apotheke.
                    order.action_confirm()
                    if queue.change_state_on_apotheke:
                        order.accept_on_apotheke()

                    # Determine state of this line
                    if all(state == 'processed' for state in line_states):
                        line.state = 'processed'
                        line_log_msgs.append((0, 0, {
                            'message': f"Successfully created Order {order.name}.", 'status': 'success'
                        }))
                    elif any(state == 'processed' for state in line_states):
                        line.state = 'processed'
                        line_log_msgs.append((0, 0, {
                            'message': f"Partially created Order {order.name} (some lines skipped).", 'status': 'info'
                        }))
                    else:
                        line.state = 'failed'
                        line_log_msgs.append((0, 0, {
                            'message': f"Order creation failed due to invalid lines.", 'status': 'error'
                        }))
                except Exception as e:
                    line.state = 'failed'
                    line_log_msgs.append((0, 0, {
                        'message': f"Unexpected error: {str(e)}", 'status': 'error'
                    }))

                line.log_ids = line_log_msgs
                all_states.append(line.state)

            # Set global queue state
            if all(state == 'processed' for state in all_states):
                queue.state = 'processed'
                log_status = 'success'
                notif_msg = f"All Apotheke orders created successfully for queue {queue.name}."
            elif any(state == 'processed' for state in all_states):
                queue.state = 'partially_processed'
                log_status = 'info'
                notif_msg = f"Some Apotheke orders were created successfully for queue {queue.name}."
            else:
                queue.state = 'failed'
                log_status = 'danger'
                notif_msg = f"No Apotheke orders could be created for queue {queue.name}."

            if log_status == 'danger':
                log_state = 'error'
            else:
                log_state = log_status

            queue.log_ids = [(0, 0, {
                'message': notif_msg,
                'status': log_state
            })]

            Bus._sendone(
                self.env.user.partner_id,
                'simple_notification',
                {'title': 'Order Import', 'message': notif_msg, 'type': log_status}
            )

    def action_retry_all_failed_lines(self):
        for queue in self:
            failed_lines = queue.line_ids.filtered(lambda l: l.state == 'failed')
            if not failed_lines:
                raise UserError(_('There are no failed lines to retry.'))
            for line in failed_lines:
                line.action_retry_order_creation()


class ImportOrderQueueLine(models.Model):
    _name = 'import.order.queue.line'
    _description = 'Import Order Queue Line'
    _inherit = ['mail.thread']
    _rec_name = 'apotheke_order_id'

    queue_id = fields.Many2one('import.order.queue', string='Order Queue', ondelete='cascade')
    apotheke_order_id = fields.Char(string='Apotheke Order ID')
    partner_id = fields.Many2one('res.partner', string='Customer')
    order_reference_for_customer = fields.Char(string='Order Reference (For Customer)')
    apotheke_tax_ids = fields.Many2many('apotheke.tax', string='Apotheke Taxes')
    order_lines_ids = fields.One2many('import.order.queue.line.line', 'queue_order_id', string='Order Lines')
    log_ids = fields.One2many('import.order.queue.line.log', 'order_line_queue_id', string='Logs')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('partially_processed', 'Partially Processed'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ], compute='_compute_state', store=True, tracking=True)
    total_amount = fields.Float(string='Total Amount', compute='_compute_total_amount', store=True)
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')

    @api.depends('order_lines_ids.state')
    def _compute_state(self):
        for line in self:
            states = line.order_lines_ids.mapped('state')
            if not states:
                line.state = 'draft'
            elif all(s == 'processed' for s in states):
                line.state = 'processed'
            elif all(s == 'failed' for s in states):
                line.state = 'failed'
            elif any(s in ('processed', 'failed') for s in states):
                line.state = 'partially_processed'
            else:
                line.state = 'draft'

    @api.depends('order_lines_ids.total_amount')
    def _compute_total_amount(self):
        for record in self:
            record.total_amount = sum(line.total_amount for line in record.order_lines_ids)

    def action_retry_order_creation(self):
        self.ensure_one()
        Bus = self.env['bus.bus']
        SaleOrder = self.env['sale.order']
        SaleOrderLine = self.env['sale.order.line']
        line = self

        line_log_msgs = []

        # Check for existing order
        if SaleOrder.search_count([('apotheke_order_id', '=', line.apotheke_order_id)]):
            line.state = 'failed'
            msg = f"Order {line.apotheke_order_id} already exists. Skipping retry."
            line_log_msgs.append((0, 0, {
                'message': msg, 'status': 'error'
            }))
            line.log_ids = line_log_msgs
            line.order_lines_ids.write({'state': 'failed'})
            return

        if not line.partner_id:
            line.state = 'failed'
            msg = f"No customer linked for Apotheke Order {line.apotheke_order_id}."
            line_log_msgs.append((0, 0, {
                'message': msg, 'status': 'error'
            }))
            line.log_ids = line_log_msgs
            line.order_lines_ids.write({'state': 'failed'})
            return

        try:
            order_vals = {
                'partner_id': line.partner_id.id,
                'apotheke_order_id': line.apotheke_order_id,
                'order_reference_for_customer': line.order_reference_for_customer,
                'apotheke_tax_ids': [(6, 0, line.apotheke_tax_ids.ids)],
                'from_apotheke': True,
                'shop_id': line.queue_id.shop_id.id,
                'channel_id': line.queue_id.channel_id.id,
            }
            order = SaleOrder.create(order_vals)

            line_states = []
            for ol in line.order_lines_ids:
                if not ol.product_id:
                    ol.state = 'failed'
                    msg = f"Missing product for line {ol.name or ol.apotheke_line_id}."
                    line_states.append('failed')
                    line_log_msgs.append((0, 0, {
                        'message': msg, 'status': 'error'
                    }))
                    continue

                SaleOrderLine.create({
                    'order_id': order.id,
                    'product_id': ol.product_id.id,
                    'product_uom_qty': ol.product_uom_qty,
                    'price_unit': ol.price_unit,
                    'name': ol.name or ol.product_id.name,
                    'apotheke_line_id': ol.apotheke_line_id,
                    'commission': ol.commission,
                    'apotheke_state': ol.apotheke_state,
                    'tax_id': [(6, 0, ol.tax_id.mapped('tax_id').ids)],
                })
                ol.state = 'processed'
                line_states.append('processed')

            # Confirm the order and accept it in Shop Apotheke.
            order.action_confirm()
            if self.queue_id.change_state_on_apotheke:
                order.accept_on_apotheke()

            # Determine overall line state
            if all(s == 'processed' for s in line_states):
                line.state = 'processed'
                line_log_msgs.append((0, 0, {
                    'message': f"Successfully retried Order {order.name}.", 'status': 'success'
                }))
            elif any(s == 'processed' for s in line_states):
                line.state = 'partially_processed'
                line_log_msgs.append((0, 0, {
                    'message': f"Partially retried Order {order.name}.", 'status': 'info'
                }))
            else:
                line.state = 'failed'
                line_log_msgs.append((0, 0, {
                    'message': "Retry failed due to invalid lines.", 'status': 'error'
                }))
        except Exception as e:
            line.state = 'failed'
            line_log_msgs.append((0, 0, {
                'message': f"Unexpected retry error: {str(e)}", 'status': 'error'
            }))

        line.log_ids = line_log_msgs

        Bus._sendone(
            self.env.user.partner_id,
            'simple_notification',
            {
                'title': 'Retry Order Creation',
                'message': f"Retry result: {line.state.upper()} for {line.apotheke_order_id}",
                'type': 'success' if line.state != 'failed' else 'danger'
            }
        )


class ImportOrderQueueLog(models.Model):
    _name = 'import.order.queue.log'
    _description = 'Import Order Queue Log'

    order_queue_id = fields.Many2one('import.order.queue', string='Queue', ondelete='cascade')
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now)
    message = fields.Text(string='Log Message')
    status = fields.Selection([
        ('info', 'Info'),
        ('success', 'Success'),
        ('error', 'Error')
    ], default='info')


class ImportOrderQueueLineLog(models.Model):
    _name = 'import.order.queue.line.log'
    _description = 'Import Order Queue Line Line Log'

    order_line_queue_id = fields.Many2one('import.order.queue.line', string='Order', ondelete='cascade')
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now)
    message = fields.Text(string='Log Message')
    status = fields.Selection([
        ('info', 'Info'),
        ('success', 'Success'),
        ('error', 'Error')
    ], default='info')


class ImportOrderQueueLineLine(models.Model):
    _name = 'import.order.queue.line.line'
    _description = 'Import Order Queue Order Line'

    queue_order_id = fields.Many2one('import.order.queue.line', string='Order Line Queue', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product')
    product_uom_qty = fields.Float(string='Quantity')
    price_unit = fields.Float(string='Unit Price')
    name = fields.Char(string='Name')
    apotheke_line_id = fields.Char(string='Apotheke Line ID')
    product_sku = fields.Char(string='SKU')
    tax_id = fields.Many2many('apotheke.tax', string='Taxes')
    commission = fields.Float(string='Commission')

    apotheke_state = fields.Selection([
        ('STAGING', 'Staging'),
        ('WAITING_ACCEPTANCE', 'Waiting Acceptance'),
        ('WAITING_DEBIT', 'Waiting Debit'),
        ('WAITING_DEBIT_PAYMENT', 'Waiting Debit Payment'),
        ('SHIPPING', 'Shipping'),
        ('SHIPPED', 'Shipped'),
        ('TO_COLLECT', 'To Collect'),
        ('RECEIVED', 'Received'),
        ('CLOSED', 'Closed'),
        ('REFUSED', 'Refused'),
        ('CANCELED', 'Canceled'),
    ], string='Apotheke State')
    total_tax = fields.Float(string='Total Tax (%)', compute='_compute_totals', store=True)
    total_amount = fields.Float(string='Amount', compute='_compute_totals', store=True)
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ], default='draft', tracking=True)

    @api.depends('tax_id', 'price_unit', 'product_uom_qty')
    def _compute_totals(self):
        for line in self:
            # Compute total tax percentage from related apotheke.tax records
            total_tax = sum(tax.value for tax in line.tax_id)
            line.total_tax = total_tax

            # Calculate total_amount: subtotal + tax
            subtotal = line.price_unit * line.product_uom_qty
            tax_amount = subtotal * (total_tax / 100)
            line.total_amount = subtotal + tax_amount
