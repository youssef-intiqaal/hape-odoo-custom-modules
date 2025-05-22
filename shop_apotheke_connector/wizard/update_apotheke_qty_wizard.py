from odoo import models, fields, api, _
import requests
import logging
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UpdateApothekeQtyWizard(models.TransientModel):
    _name = 'update.apotheke.qty.wizard'
    _description = 'Update Apotheke Quantity & Price Wizard'

    product_id = fields.Many2one('product.template', string="Product", required=True)
    product_ean = fields.Char(string="EAN", readonly=True)
    shop_id = fields.Many2one('shop.apotheke.shop', string="Shop", domain="[('id', 'in', domain_shop_ids)]", required=True)
    offer_id = fields.Many2one('apotheke.product.offer', string="Offer", readonly=True)
    domain_shop_ids = fields.Many2many('shop.apotheke.shop', compute='_compute_domain_shop_ids')
    product_qty_available = fields.Float(string="On-hand Quantity", related='product_id.qty_available', readonly=True)
    product_sales_price = fields.Float(string="Sales Price", related='product_id.list_price', readonly=True)
    company_currency_id = fields.Many2one('res.currency', compute='_compute_company_currency_id', readonly=True)

    @api.depends_context('company')
    def _compute_company_currency_id(self):
        self.company_currency_id = self.env.company.currency_id

    @api.depends('product_ean')
    def _compute_domain_shop_ids(self):
        for wizard in self:
            wizard.domain_shop_ids = False
            apotheke_product = self.env['apotheke.product'].search([('ean', '=', wizard.product_ean)], limit=1)
            if apotheke_product:
                wizard.domain_shop_ids = apotheke_product.offer_ids.mapped('shop_id').ids

    @api.onchange('shop_id')
    def _onchange_shop_id(self):
        self.offer_id = False
        if self.shop_id and self.product_ean:
            offer = self.env['apotheke.product.offer'].search([
                ('product_ean', '=', self.product_ean),
                ('shop_id', '=', self.shop_id.id)
            ], limit=1)
            self.offer_id = offer

    def action_submit_update(self):
        self.ensure_one()

        if not self.offer_id:
            raise UserError(_("No matching offer found."))

        qty_available = self.product_id.qty_available
        payload = {
            "offers": [{
                "product_id": self.product_ean,
                "product_id_type": "EAN",
                "quantity": qty_available,
                "shop_sku": self.offer_id.offer_sku,
                "state_code": self.offer_id.state_code,
                "update_delete": "update",
                "price": self.product_id.list_price,
            }]
        }
        query = {
            "shop_id": self.shop_id.shop_number
        }

        server_url = self.shop_id.setting_id.server.rstrip("/") + "/api/offers"
        api_key = self.shop_id.setting_id.api_key

        if not api_key:
            raise UserError(_("API Key is missing in the connector setting."))

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"{api_key}"
        }

        try:
            response = requests.post(server_url, json=payload, params=query, headers=headers)
            response.raise_for_status()
            self._send_notification('success', _("Quantity update sent successfully."))
            self.product_id.apotheke_qty_updated = True
            self.product_id.last_update_datetime = fields.Datetime.now()
            self.offer_id.quantity = self.product_qty_available
            self.offer_id.price = self.product_id.list_price

        except Exception as e:
            _logger.exception("Error updating Apotheke quantity")
            self._send_notification('danger', _("Failed to update quantity: %s") % str(e))

    def _send_notification(self, notif_type, message):
        self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
            'type': notif_type,
            'sticky': False,
            'message': message,
        })
