# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api, _
import logging
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ApothekeProduct(models.Model):
    _name = 'apotheke.product'
    _description = 'Shop Apotheke Product'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    setting_id = fields.Many2one('shop.apotheke.connector.setting', string='Instance', readonly=True)
    shop_ids = fields.Many2many(
        'shop.apotheke.shop',
        'apotheke_product_shop_rel',
        'apotheke_product_id',
        'shop_id',
        string='Shops',
        domain="[('setting_id', '=', setting_id)]",
        tracking=True, readonly=True

    )
    main_image = fields.Binary(string='Main Image', readonly=True)
    name = fields.Char(string='Product Name', required=True, tracking=True)
    sku = fields.Char(string='SKU', required=True, tracking=True)
    ean = fields.Char(string='EAN', required=False, tracking=True)
    brand = fields.Char(string='Brand', readonly=True)
    category_id = fields.Many2one('product.category', string='Category')
    odoo_product_id = fields.Many2one('product.template', string='Odoo Product', tracking=True, readonly=False)
    publish_date = fields.Date(string='Publish Date', tracking=True, readonly=True)
    state_sync_odoo = fields.Selection([
        ('not_synchronized', 'Not Linked'),
        ('synchronized', 'Linked'),
    ], default='not_synchronized', string='Odoo Sync. State', tracking=True)

    state_sync_apotheke = fields.Selection([
        ('not_synchronized', 'Not Published'),
        ('synchronized', 'Published'),
    ], default='not_synchronized', string='Apotheke Sync. State', tracking=True)
    offer_ids = fields.One2many('apotheke.product.offer', 'product_id', string='Offers')
    sale_price = fields.Float(string='Sale Price', tracking=True, readonly=True)
    available_qty = fields.Integer(
        string='Total Available Quantity',
        compute='_compute_available_qty',
        store=True,
        tracking=True,
        readonly=True,
    )

    company_currency_id = fields.Many2one('res.currency', compute='_compute_company_currency_id')
    offer_count = fields.Integer(string='Offers Count', compute='_compute_offer_count')
    qty_updated = fields.Boolean(string='Quantity Updated', readonly=True, tracking=True)

    @api.onchange('odoo_product_id')
    def _onchange_odoo_product_id(self):
        for record in self:
            if not record.odoo_product_id:
                record.state_sync_odoo = 'not_synchronized'

    @api.depends('offer_ids.quantity')
    def _compute_available_qty(self):
        for record in self:
            record.available_qty = sum(record.offer_ids.mapped('quantity'))

    @api.depends('offer_ids')
    def _compute_offer_count(self):
        for product in self:
            product.offer_count = len(product.offer_ids)

    @api.depends_context('company')
    def _compute_company_currency_id(self):
        self.company_currency_id = self.env.company.currency_id

    def action_view_offers(self):
        self.ensure_one()
        offers = self.env['apotheke.product.offer'].search([('product_id', '=', self.id)])
        if not offers:
            raise UserError(_("No related offer found."))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Related Offers'),
            'res_model': 'apotheke.product.offer',
            'domain': [('product_id', '=', self.id)],
            'view_mode': 'list,form',
            'target': 'current',
            'context': {
                'default_product_id': self.id,
                'default_shop_id': self.shop_ids[:1].id if self.shop_ids else False,
                'default_product_sku': self.sku,
                'default_product_ean': self.ean,
            }
        }

    @api.onchange('setting_id')
    def _onchange_setting_id(self):
        if self.shop_ids:
            self.shop_ids = self.shop_ids.filtered(lambda shop: shop.setting_id == self.setting_id)

    def action_sync_with_odoo(self):
        ProductTemplate = self.env['product.template']
        updated = 0
        created = 0

        for product in self:

            try:
                with self.env.cr.savepoint():  # Isolate each product sync
                    if product.odoo_product_id and product.state_sync_odoo == 'synchronized':
                        continue

                    # Try to find an existing product by SKU or EAN
                    existing_product = ProductTemplate.search([
                        '|',
                        ('default_code', '=', product.sku),
                        ('ean', '=', product.ean),
                        ('type', '=', 'consu'),
                    ], limit=1)

                    if existing_product:
                        product.odoo_product_id = existing_product.id
                        product.state_sync_odoo = 'synchronized'
                        updated += 1
                    else:
                        new_product = ProductTemplate.create({
                            'name': product.name,
                            'default_code': product.sku,
                            'ean': product.ean,
                            'is_storable': True,
                            'image_1920': product.main_image,
                            'image_128': product.main_image,
                            'image_256': product.main_image,
                            'image_512': product.main_image,
                            'image_1024': product.main_image,
                            'categ_id': product.category_id.id if product.category_id else False,
                        })
                        product.odoo_product_id = new_product.id
                        product.state_sync_odoo = 'synchronized'
                        created += 1

            except Exception as e:
                _logger.exception(f"!!! Error syncing product {product.sku}: {str(e)}")

        notif_type = 'success' if updated or created else 'warning'
        message = _("Synchronization complete: %d linked, %d created.") % (updated, created)

        try:
            partner_id = self.env.user.partner_id
            self.env['bus.bus']._sendone(partner_id, 'simple_notification', {
                'type': notif_type,
                'sticky': False,
                'message': message,
            })
            _logger.info(">>> Notification sent successfully.")
        except Exception as notif_error:
            _logger.exception(f"!!! Notification failed: {notif_error}")

    def action_update_odoo_product_quantities(self):
        StockQuant = self.env['stock.quant']
        Warehouse = self.env['stock.warehouse']
        updated = 0
        skipped = 0
        failed = 0

        warehouse = Warehouse.search([('company_id', '=', self.env.company.id)], limit=1)
        if not warehouse:
            raise UserError(_("No warehouse found for the current company."))

        for product in self:
            try:
                with self.env.cr.savepoint():
                    if not product.odoo_product_id:
                        skipped += 1
                        continue

                    # Assume single variant products
                    product_variant = product.odoo_product_id.product_variant_id
                    if not product_variant:
                        skipped += 1
                        continue

                    quant_vals = {
                        'product_id': product_variant.id,
                        'location_id': warehouse.lot_stock_id.id,
                        'inventory_quantity': product.available_qty,
                    }

                    # Create or update quant and apply inventory
                    StockQuant.with_context(inventory_mode=True).create(quant_vals)._apply_inventory()
                    updated += 1
                    product.qty_updated = True

            except Exception as e:
                failed += 1
                _logger.exception(f"Failed to update quantity for product {product.name}: {str(e)}")

        # Notify user
        notif_type = 'success' if updated else 'warning'
        msg = _("Quantity update finished: %d updated, %d skipped, %d failed.") % (updated, skipped, failed)

        try:
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': notif_type,
                'sticky': False,
                'message': msg,
            })
        except Exception as notif_err:
            _logger.error(f"Failed to send qty update notification: {notif_err}")

        return True

