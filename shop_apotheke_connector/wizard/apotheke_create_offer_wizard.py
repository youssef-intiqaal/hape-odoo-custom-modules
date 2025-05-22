# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, api, _
import requests
import time
from odoo.exceptions import ValidationError
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class ApothekeCreateOfferWizard(models.TransientModel):
    _name = 'apotheke.create.offer.wizard'
    _description = 'Create Shop Apotheke Offer Wizard'

    setting_id = fields.Many2one('shop.apotheke.connector.setting', required=True)
    shop_id = fields.Many2one('shop.apotheke.shop', domain="[('setting_id', '=', setting_id)]", required=True)
    channel_id = fields.Many2one('shop.apotheke.shop.channel', domain="[('shop_id', '=', shop_id)]", required=True)
    price = fields.Float(string="Price", required=True)
    qty = fields.Integer(string="Quantity", required=True)
    shop_sku = fields.Char(string="Shop SKU", required=False)
    tax_id = fields.Many2one('apotheke.tax', string="Tax", required=True)
    product_id = fields.Many2one('apotheke.product', required=True)
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    pricelist_id = fields.Many2one('product.pricelist', string="Pricelist")
    computed_pricelist_price = fields.Float(string="Pricelist Price", readonly=True, compute='_compute_pricelist_price')

    @api.depends('pricelist_id', 'product_id')
    def _compute_pricelist_price(self):
        for rec in self:
            rec.computed_pricelist_price = 0.0
            if rec.pricelist_id and rec.product_id and rec.product_id.odoo_product_id:
                try:
                    product = rec.product_id.odoo_product_id.product_variant_id
                    price = rec.pricelist_id._get_product_price(
                        product,
                        quantity=1.0,
                        uom=product.uom_id,
                        currency=rec.pricelist_id.currency_id,
                        date=fields.Date.context_today(self)
                    )
                    rec.computed_pricelist_price = price
                except Exception as e:
                    _logger.warning(f"Could not compute pricelist price in wizard: {e}")

    @api.onchange('pricelist_id', 'product_id')
    def _onchange_pricelist_id_or_product_id(self):
        """Auto-fill price field based on selected pricelist and product."""
        for rec in self:
            if rec.pricelist_id and rec.product_id and rec.product_id.odoo_product_id:
                try:
                    product = rec.product_id.odoo_product_id.product_variant_id
                    price = rec.pricelist_id._get_product_price(
                        product,
                        quantity=1.0,
                        uom=product.uom_id,
                        currency=rec.pricelist_id.currency_id,
                        date=fields.Date.context_today(self)
                    )
                    rec.price = price
                except Exception as e:
                    _logger.warning(f"Error getting pricelist price in wizard onchange: {e}")
                    rec.price = 0.0

    def action_confirm_create_offer(self):
        self.ensure_one()
        if not self.shop_sku:
            raise ValidationError(_("Shop SKU is required. Please generate it or enter manually."))
        api_key = self.setting_id.api_key
        server = self.setting_id.server
        sku = self.product_id.sku

        check_url = f"{server}/api/offers"
        check_params = {"product_id": sku, "shop_id": self.shop_id.shop_number}
        headers = {"Authorization": api_key}

        # 1. Check if product exists in Shop Apotheke using EAN
        try:
            product_check_url = f"{server}/api/products"
            product_check_params = {
                "product_references": f"EAN|{self.product_id.ean}",
                "shop_id": self.shop_id.shop_number,
            }
            headers = {"Authorization": api_key}
            product_response = requests.get(product_check_url, params=product_check_params, headers=headers)
            product_response.raise_for_status()
            product_data = product_response.json()

            if not product_data.get("products"):
                self._notify("This product (EAN) does not exist in Shop Apotheke. Please import it first.",
                             success=False)
                return
        except Exception as e:
            self._notify(f"Failed to verify product existence: {str(e)}", success=False)
            return

        # 2. Check existing offer
        try:
            check_response = requests.get(check_url, params=check_params, headers=headers)
            check_response.raise_for_status()
            offers_data = check_response.json()
        except Exception as e:
            self._notify(f"Failed to check existing offers: {e}", success=False)
            return

        if offers_data.get("total_count", 0) > 0:
            for offer in offers_data.get("offers", []):
                if self.channel_id.code in offer.get("channels", []):
                    self._notify(
                        f"This product already has an offer in the selected channel ({self.channel_id.label}). You can open the offer and update it instead.",
                        success=False)
                    # Attempt to sync the offer locally if it does not already exist in apotheke.product.offer
                    shop_sku = offer.get("shop_sku")
                    if not shop_sku:
                        return

                    existing_offer_local = self.env['apotheke.product.offer'].search([
                        ('offer_sku', '=', shop_sku),
                        ('shop_id', '=', self.shop_id.id),
                        ('channel_ids', 'in', self.channel_id.id),
                    ], limit=1)

                    if not existing_offer_local:
                        # Build local offer record from API data
                        offer_vals = {
                            "shop_id": self.shop_id.id,
                            "offer_sku": offer.get("shop_sku"),
                            "offer_active": offer.get("active", True),
                            "shop_offer_id": str(offer.get("offer_id")),
                            "product_sku": offer.get("product_sku"),
                            "product_ean": self.product_id.ean,
                            "price": offer.get("price", 0.0),
                            "quantity": offer.get("quantity", 0),
                            "state_code": offer.get("state_code"),
                            "product_id": self.product_id.id,
                            "channel_ids": [(6, 0, self.channel_id.ids)],
                            "apotheke_tax_id": self.tax_id.id,
                        }
                        self.env['apotheke.product.offer'].create(offer_vals)

                    return


        # 3. Create new offer
        payload = {
            "offers": [
                {
                    "all_prices": [{"channel_code": self.channel_id.code}],
                    "price": self.price,
                    "product_id": sku,
                    "product_id_type": "SKU",
                    "quantity": self.qty,
                    "state_code": "11",
                    "shop_sku": self.shop_sku,
                    "offer_additional_fields":
                        [{
                            "code": self.tax_id.code,
                            "value": int(self.tax_id.value)
                        }]

                }
            ]
        }
        post_params = {"shop_id": self.shop_id.shop_number}

        try:
            post_response = requests.post(
                check_url, json=payload, headers={**headers, "Content-Type": "application/json"}, params=post_params
            )
            post_response.raise_for_status()
            self._notify("Offer successfully created!", success=True)

            time.sleep(30)
            # 4. Fetch Offer ID from Shop Apotheke of the newly created Offer
            offer_data = {}
            try:
                endpoint = f"{server}/api/offers"
                headers = {
                    "Authorization": f"{api_key}",
                    "Content-Type": "application/json",
                }
                params = {"shop_sku": self.shop_sku}
                response = requests.get(endpoint, headers=headers, params=params)
                response.raise_for_status()
                offer_data = response.json()
            except Exception as e:
                self._notify(f"Offer creation succeeded but could not verify: {str(e)}", success=False)

            if not offer_data.get("offers"):
                self._notify("No offer data found in response after checking.", success=False)

            offers = offer_data.get("offers", [])
            offer = next((o for o in offers if o.get("shop_sku") == self.shop_sku), None)

            if not offer:
                self._notify(f"No offer found with shop_sku = {self.shop_sku}", success=False)

            # Check and remove existing offers for this product/shop/channel
            existing_offer = self.env['apotheke.product.offer'].search([
                ('product_id', '=', self.product_id.id),
                ('shop_id', '=', self.shop_id.id),
                ('channel_ids', 'in', self.channel_id.id),
            ])
            if existing_offer:
                existing_offer.unlink()

            # 5. Create apotheke.product.offer record
            offer_vals = {
                "shop_id": self.shop_id.id,
                "offer_sku": offer.get("shop_sku"),
                "offer_active": True,
                "shop_offer_id": str(offer.get("offer_id")),
                "product_sku": offer.get("product_sku"),
                "product_ean": self.product_id.ean,
                "price": offer.get("price", 0.0),
                "quantity": offer.get("quantity", 0),
                "state_code": offer.get("state_code"),
                "product_id": self.product_id.id,
                "channel_ids": [(6, 0, self.channel_id.ids)],
                "apotheke_tax_id": self.tax_id.id,
            }

            self.env['apotheke.product.offer'].create(offer_vals)
        except Exception as e:
            self._notify(f"Failed to create offer: {e}", success=False)

    def _notify(self, message, success=True):
        partner_id = self.env.user.partner_id
        notification = {
            'title': "Success" if success else "Error",
            'message': message,
            'type': 'success' if success else 'danger',
        }
        self.env['bus.bus']._sendone(partner_id, 'simple_notification', notification)

    def action_generate_shop_sku(self):
        self.ensure_one()
        now = datetime.now()
        sku = f"OFFER_SKU{now.strftime('%y%m%d%H%M')}"
        self.shop_sku = sku

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'view_id': self.env.ref('shop_apotheke_connector.view_apotheke_create_offer_wizard_form').id,
        }
