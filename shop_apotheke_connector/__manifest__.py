# -*- coding: utf-8 -*-
# Developed by Youssef Omri AKA DZEUF

{
    'name': 'Shop Apotheke Connector',
    'version': '1.0',
    'summary': 'Shop Apotheke Connector',
    'website': 'https://mountain.co.at/',
    'depends': ['base', 'mail', 'sale', 'account', 'austria_dpd_shipping_integration'],
    'author': 'Youssef Omri',
    'category': 'Tools',
    'data': [
        'data/sequences.xml',
        'data/cron.xml',
        'security/ir.model.access.csv',

        'wizard/import_category_wizard_view.xml',
        'wizard/import_product_wizard_view.xml',
        'wizard/import_offer_wizard_view.xml',
        'wizard/update_apotheke_qty_wizard_view.xml',
        'wizard/import_apotheke_order_wizard_view.xml',
        'wizard/transfer_to_apotheke_wizard.xml',
        'wizard/apotheke_create_offer_wizard.xml',

        'views/product_category_form_view_inherit.xml',
        'views/product_template_form_view_inherit.xml',
        'views/delivery_carrier_view_inherit.xml',
        'views/res_partner_view_inherit.xml',

        'views/shop.xml',
        'views/setting.xml',
        'views/product.xml',
        'views/import_category_queue.xml',
        'views/import_product_queue.xml',
        'views/import_offer_queue.xml',
        'views/offer.xml',
        'views/tax.xml',
        'views/sale_view_inherit.xml',
        'views/category.xml',
        'views/apotheke_import_operation_log.xml',
        'views/menus.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
}
