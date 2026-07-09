# odoo-trueformat

Odoo 18 connector for [TrueFormat](https://trueformat.co.uk) — a CSV integrity
checker that catches Excel-induced corruption (scientific notation on long IDs,
stripped leading zeros, flipped/ambiguous dates, hidden characters,
near-duplicate rows) **before** the data reaches Odoo's import engine.

This module is a thin connector only. All detection logic runs on the
TrueFormat API; the module uploads a CSV, receives a report, and displays it.
Files are processed in-memory — nothing is written to disk.

## Installation

The module lives in the `trueformat/` folder of this repository. Clone the
repo and add it to your Odoo addons path (or copy `trueformat/` into an
existing addons directory):

```bash
git clone https://github.com/Jaseyacey/odoo-trueformat.git
# then start Odoo with:  --addons-path=...,/path/to/odoo-trueformat
```

Then update the apps list and install **TrueFormat CSV Integrity Check**.
The `requests` Python library must be available on the Odoo server
(it ships with standard Odoo installs).

## Configuration

Set your API key in **Settings → Technical → Parameters → System Parameters**:

| Key | Value |
|---|---|
| `trueformat.api_key` | Your TrueFormat integration API key (required) |
| `trueformat.api_endpoint` | Override only if not using the default `https://trueformat-api.onrender.com/check` |
| `trueformat.api_fix_endpoint` | Override only if not using the default `https://trueformat-api.onrender.com/fix` |

## Usage

Open **TrueFormat → CSV Integrity Check**, attach a `.csv` file and click
**Check File**. The report lists every flagged cell or column with its issue
type, location, original value, and an explanation.

From the report screen, **Get Corrected File** downloads a copy with safe
mechanical corrections applied (trimming, empty row/column removal,
duplicate header renaming). Issues that need human judgment — ambiguous
dates, near-duplicate values — or where Excel already destroyed data
(scientific-notation IDs, stripped leading zeros) are never auto-fixed;
they stay in the report so you can correct them at the source.

Limits enforced by the API: `.csv` files up to **20 MB** / **250,000 rows**.

## License

LGPL-3
