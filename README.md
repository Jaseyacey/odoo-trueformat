# odoo-trueformat

Odoo 18 connector for [TrueFormat](https://trueformat.co.uk) — a CSV integrity
checker that catches Excel-induced corruption (scientific notation on long IDs,
stripped leading zeros, flipped/ambiguous dates, hidden characters,
near-duplicate rows) **before** the data reaches Odoo's import engine.

This module is a thin connector only. All detection logic runs on the
TrueFormat API; the module uploads a CSV, receives a report, and displays it.
Files are processed in-memory — nothing is written to disk.

## Installation

The repository root is the Odoo module itself. Clone it into your addons
path as a directory named `trueformat` (the module's technical name):

```bash
cd /path/to/odoo/addons
git clone https://github.com/Jaseyacey/odoo-trueformat.git trueformat
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

## Usage

Open **TrueFormat → CSV Integrity Check**, attach a `.csv` file and click
**Check File**. The report lists every flagged cell or column with its issue
type, location, original value, and an explanation.

Limits enforced by the API: `.csv` files up to **20 MB** / **250,000 rows**.

## License

LGPL-3
