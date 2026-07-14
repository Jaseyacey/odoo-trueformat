# -*- coding: utf-8 -*-
{
    "name": "TrueFormat CSV Integrity Check",
    "version": "19.0.1.0.0",
    "summary": "Catch silent CSV corruption before it reaches Odoo's import engine.",
    "description": """
TrueFormat CSV Integrity Check
==============================

Excel silently corrupts CSV data before ERP import — scientific notation on
long IDs, stripped leading zeros, flipped dates, hidden characters, and
near-duplicate records. Odoo's import engine validates structure, not values,
so this corruption passes through undetected and surfaces later as
reconciliation and reporting failures.

This module lets you run any CSV through TrueFormat's integrity check directly
from within Odoo, before you import. It flags exactly what changed and returns
a clear report.

The file is processed in-memory. Nothing is written to disk.

Requires an active TrueFormat subscription (£5,000 per year or £800 per month).
Set your API key in Settings > Technical > Parameters > System Parameters.
    """,
    "author": "TrueFormat (Fixturefix Ltd)",
    "website": "https://trueformat.co.uk",
    "category": "Tools",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/check_wizard_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "trueformat/static/src/css/preview.css",
            "trueformat/static/src/xml/preview_templates.xml",
            "trueformat/static/src/js/preview_widget.js",
        ],
    },
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": True,
    "external_dependencies": {"python": ["requests"]},
}
