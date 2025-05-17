from odoo import models, fields, api


class ProductCategory(models.Model):
    _inherit = 'product.template'

    ean = fields.Char(string='EAN')
    apotheke_qty_updated = fields.Boolean(string="Apotheke Qty Updated", default=False)
    last_update_datetime = fields.Datetime(string="Last Apotheke Update Time")

    def write(self, vals):
        # If sales price is being changed, reset apotheke_qty_updated
        if 'list_price' in vals:
            vals['apotheke_qty_updated'] = False
        return super().write(vals)

    def unlink(self):
        # Get related apotheke.product records before deleting product.template
        apotheke_products = self.env['apotheke.product'].search([
            ('odoo_product_id', 'in', self.ids),
            ('state_sync_odoo', '=', 'synchronized')
        ])

        # Proceed with deletion
        result = super().unlink()

        # After deletion, reset sync state and unlink odoo_product_id
        if apotheke_products:
            apotheke_products.write({
                'state_sync_odoo': 'not_synchronized',
                'odoo_product_id': False,
            })

        return result

    def action_update_quantity_apotheke(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Update Apotheke Quantity',
            'res_model': 'update.apotheke.qty.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_id': self.id,
                'default_product_ean': self.ean,
            }
        }


class StockChangeProductQty(models.TransientModel):
    _inherit = 'stock.change.product.qty'

    def change_product_qty(self):
        res = super().change_product_qty()

        # Set apotheke_qty_updated = False after qty change
        for wizard in self:
            if wizard.product_tmpl_id:
                wizard.product_tmpl_id.apotheke_qty_updated = False

        return res
