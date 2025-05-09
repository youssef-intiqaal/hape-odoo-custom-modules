# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

{
    'name': 'Invoice Custom CSV Export',
    'version': '1.0',
    'summary': 'Export invoices and customer data to custom CSV formats',
    'website': 'https://mountain.co.at/',
    'depends': ['account'],
    'author': 'Youssef Omri',
    'category': 'Accounting',
    'application': True,
    'data': [
        'security/ir.model.access.csv',
        'wizard/invoice_export_wizard_view.xml',
        'views/custom_invoice_csv_views.xml',
        'views/custom_invoice_csv_menu_views.xml'
    ],
    'license': 'LGPL-3',
    'installable': True,

}
