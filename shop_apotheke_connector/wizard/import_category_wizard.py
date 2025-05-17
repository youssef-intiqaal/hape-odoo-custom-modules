# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

from odoo import models, fields, _
import requests


class ImportCategoryWizard(models.TransientModel):
    _name = 'import.category.wizard'
    _description = 'Import Category Wizard'

    setting_id = fields.Many2one(
        'shop.apotheke.connector.setting',
        string="Instance",
        required=True
    )

    def action_confirm_import(self):
        queue = self.env['import.category.queue'].create({'setting_id': self.setting_id.id})
        log_model = self.env['import.category.queue.log']
        setting = self.setting_id

        if not setting:
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'danger',
                'sticky': False,
                'message': _("No Instance selected."),
            })
            return

        url = f"{setting.server}/api/hierarchies"
        try:
            response = requests.get(url, headers={"Authorization": setting.api_key})
            response.raise_for_status()
            data = response.json()

            for item in data.get('hierarchies', []):
                queue.line_ids.create({
                    'queue_id': queue.id,
                    'level': item.get('level'),
                    'code': item.get('code'),
                    'name': item.get('label'),
                    'parent_code': item.get('parent_code'),
                    'parent_name': '',
                })

            log_model.create({
                'queue_id': queue.id,
                'message': _('Successfully imported %s categories.') % len(data.get('hierarchies', [])),
                'status': 'success',
            })

            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'success',
                'sticky': False,
                'message': _("Category import completed successfully."),
            })

        except Exception as e:
            log_model.create({
                'queue_id': queue.id,
                'message': f"Failed to fetch data: {str(e)}",
                'status': 'error',
            })
            queue.state = 'failed'
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
                'type': 'danger',
                'sticky': False,
                'message': _("Failed to fetch category data: %s") % str(e),
            })

        # Return action to open the created queue record
        return {
            'type': 'ir.actions.act_window',
            'name': _('Category Queue'),
            'res_model': 'import.category.queue',
            'view_mode': 'form',
            'res_id': queue.id,
            'target': 'current',
        }
