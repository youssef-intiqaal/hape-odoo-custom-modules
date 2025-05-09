# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields
from odoo.exceptions import ValidationError
import base64
import logging
from io import StringIO
import csv

_logger = logging.getLogger(__name__)


class InvoiceExportWizard(models.TransientModel):
    _name = 'invoice.export.wizard'
    _description = 'Wizard to export invoice and customer data'

    # Date filters for invoice selection
    date_from = fields.Date(string='Start Date', required=False)
    date_to = fields.Date(string='End Date', required=False)

    invoice_ids = fields.Many2many('account.move', string='Invoices',
                                   domain="[('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]")

    export_file_belastungen = fields.Binary("Export Belastungen File")
    export_file_kunden = fields.Binary("Export Kunden File")
    export_filename_belastungen = fields.Char("Filename Belastungen")
    export_filename_kunden = fields.Char("Filename Kunden")

    def load_all_invoices(self):
        """
        Load all posted customer invoices regardless of date.
        Automatically sets the date range and populates `invoice_ids`.
        """

        self.ensure_one()

        # Search all posted customer invoices ordered by date
        invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
        ], order='invoice_date asc')

        if not invoices:
            raise ValidationError("No posted customer invoices found.")

        # Assign all found invoices to the wizard
        self.invoice_ids = [(6, 0, invoices.ids)]

        # Set date range based on invoice dates
        self.date_from = invoices[0].invoice_date
        self.date_to = invoices[-1].invoice_date

        # Reopen the wizard with updated data
        return {
            'type': 'ir.actions.act_window',
            'name': 'Export All Invoices',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_load_invoices(self):
        """
        Load posted customer invoices within the specified date range.
        Validates that start date is before end date.
        """

        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError("Start Date must be before End Date.")

        self.ensure_one()

        # Load invoices in date range if both dates are provided
        if self.date_from and self.date_to:
            invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', self.date_from),
                ('invoice_date', '<=', self.date_to),
            ])
            self.invoice_ids = [(6, 0, invoices.ids)]

        # Name the action dynamically based on provided dates
        action_name = f"Export invoice from {self.date_from} to {self.date_to}" if self.date_from and self.date_to else "Export Invoices"

        return {
            'type': 'ir.actions.act_window',
            'name': action_name,
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def clear_invoices(self):
        """
        Reset the wizard fields: clears the date range and selected invoices.
        """

        self.ensure_one()

        self.date_from = False
        self.date_to = False
        self.invoice_ids = [(5, 0, 0)]

        return {
            'type': 'ir.actions.act_window',
            'name': 'Export Invoices',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def export_belastungen(self):
        """
        Export selected invoice data to a semicolon-separated text (CSV) file.
        The output includes customer number, description, amount, account code, and invoice number.
        """

        if not self.invoice_ids:
            raise ValidationError("No invoices selected for export.")

        buffer = StringIO()
        writer = csv.writer(buffer, delimiter=';', lineterminator='\n')

        # Write CSV header
        writer.writerow(['Kd.Nr.', 'Titel und Zeitraum', 'Betrag', 'Kostenstelle', 'Rg.Nr.'])

        # Format the date range for period column
        date_start = self.date_from.strftime('%d.%m.%Y') if self.date_from else ''
        date_end = self.date_to.strftime('%d.%m.%Y') if self.date_to else ''
        period = f"{date_start} bis {date_end}"

        for inv in self.invoice_ids:
            try:
                title = inv.invoice_origin or inv.name or 'Rechnung'
                titel_und_zeitraum = f"{title} {period}"

                # Extract data fields for the line
                line = [
                    inv.partner_id.ref or '',
                    titel_und_zeitraum,
                    f"{inv.amount_total:.2f}".replace('.', ','),
                    inv.invoice_line_ids[:1].account_id.code if inv.invoice_line_ids else '',
                    inv.name
                ]
                writer.writerow(line)
            except Exception as e:
                _logger.error("Error exporting invoice %s: %s", inv.name, str(e))

        # Encode and store the file for download
        self.export_file_belastungen = base64.b64encode(buffer.getvalue().encode('utf-8'))
        self.export_filename_belastungen = 'Export_Belastungen.txt'

        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content?model={self._name}&id={self.id}&field=export_file_belastungen"
                   f"&filename_field=export_filename_belastungen&download=true",
            'target': 'self',
        }

    def export_kunden(self):
        """
        Export customer (partner) data associated with selected invoices to a semicolon-separated text (CSV) file.
        The output includes customer number, name, address, payment method, IBAN, and BIC.
        """

        if not self.invoice_ids:
            raise ValidationError("No invoices selected for export.")

        buffer = StringIO()
        writer = csv.writer(buffer, delimiter=';', lineterminator='\n')

        writer.writerow(['Kd.Nr.', 'Name', 'Vorname', 'PLZ', 'Ort', 'Anschrift', 'Zahlungsart', 'IBAN', 'BIC'])

        for partner in self.invoice_ids.mapped('partner_id'):
            try:
                # Split full name into last and first name
                name_split = (partner.name or '').split(' ', 1)
                last_name = name_split[0]
                first_name = name_split[1] if len(name_split) > 1 else ''

                writer.writerow([
                    partner.ref or '',
                    last_name,
                    first_name,
                    partner.zip or '',
                    partner.city or '',
                    partner.street or '',
                    partner.property_inbound_payment_method_line_id.name or '',
                    partner.bank_ids[:1].acc_number if partner.bank_ids else '',
                    partner.bank_ids[:1].bank_bic if partner.bank_ids else '',
                ])
            except Exception as e:
                _logger.error("Error exporting partner %s: %s", partner.name, str(e))

        self.export_file_kunden = base64.b64encode(buffer.getvalue().encode('utf-8'))
        self.export_filename_kunden = 'Export_Kunden.txt'

        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content?model={self._name}&id={self.id}&field=export_file_kunden"
                   f"&filename_field=export_filename_kunden&download=true",
            'target': 'self',
        }
