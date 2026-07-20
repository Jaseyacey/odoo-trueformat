# TrueFormat CSV Integrity Check

An Odoo 19 connector that checks CSV files for silent spreadsheet corruption
before they reach Odoo's import engine.

Excel rewrites data when it opens a CSV: long identifiers collapse into
scientific notation (`1.02E+11`), leading zeros disappear from SKUs and account
codes (`000456` → `456`), product codes that resemble dates get converted into
dates (`SEP-26`), and date formats flip between DD/MM and MM/DD depending on
locale.

None of this produces an import error. Odoo's import validates *structure* —
column names, field types, required fields — not *values*. A
scientific-notation string is still a valid string, so it imports cleanly and
surfaces weeks later as reconciliation and reporting failures.

This module runs a CSV through the TrueFormat integrity check from inside Odoo,
reports exactly which cells are affected, and can return a corrected copy of the
file.

## What it detects

| Category | Examples |
| --- | --- |
| Format flips | Scientific notation on long identifiers, stripped leading zeros, cells breaking their column's dominant format |
| Date corruption | Ambiguous day/month values, mixed formats within one column, spreadsheet date serials, date-coerced identifiers |
| Hidden characters | Zero-width and non-breaking spaces, control characters, stray CSV metacharacters — reported with position |
| Near-duplicates | Values differing only in case, whitespace or trailing punctuation, grouped with every raw variant |

Detection is rule-based, not probabilistic. The same file always produces the
same result, and every transformation is logged. Where a spreadsheet has
genuinely destroyed information and no correct value can be derived, the module
reports it rather than substituting a guess.

## Multi-file sessions

Real migrations are never a single CSV. Attach several files in one session —
products, customers, suppliers, pricelists, opening inventory — check each one,
review its own preview, and download each corrected copy independently. `Check
All` processes the batch sequentially; a failure on one file never aborts the
rest.

## Requirements

- Odoo 19.0
- Python `requests` (included in standard Odoo installs)
- An active TrueFormat subscription and API key — https://trueformat.co.uk

This module is a thin connector. All detection and correction logic runs on the
TrueFormat API; files are processed in memory and are not stored.

**Hosting note:** Odoo Online (SaaS) does not permit third-party modules. This
module can be installed on Odoo.sh and self-hosted instances. For Odoo Online,
use the web application at https://trueformat.co.uk instead.

## Installation

The module's technical name is `trueformat`, so the directory **must** be named
`trueformat`. Clone it accordingly:

```bash
cd /path/to/your/addons
git clone https://github.com/Jaseyacey/odoo-trueformat.git trueformat
```

Then restart Odoo, go to **Apps → Update Apps List**, search for
`trueformat`, and install.

It is also available on the Odoo App Store:
https://apps.odoo.com/apps/modules/19.0/trueformat

## Configuration

Two system parameters, under **Settings → Technical → Parameters → System
Parameters**:

| Key | Value |
| --- | --- |
| `trueformat.api_key` | Your API key, generated at https://trueformat.co.uk (Settings → API Keys) |
| `trueformat.api_endpoint` | *(optional)* Defaults to `https://trueformat.onrender.com/api/check` |
| `trueformat.api_fix_endpoint` | *(optional)* Defaults to `https://trueformat.onrender.com/api/fix` |

Only `trueformat.api_key` is required. The endpoint parameters exist so the
module can be pointed at a different environment if needed.

## Usage

1. Open **TrueFormat → CSV Integrity Check**.
2. Attach one or more `.csv` files (up to 20 MB / 250,000 rows each).
3. Click **Check** on a line, or **Check All** to process the batch.
4. Review the report and interactive preview: every flagged cell is shown with
   its column, row, original value and issue type.
5. Click **Fix** to download a corrected copy of that file.

## Data handling

Files are transmitted over an encrypted connection to the TrueFormat API,
processed in memory, and are not written to disk or stored in a database. File
contents are not retained once results are returned and are not used for any
other purpose.

## Licence

LGPL-3. See [LICENSE](LICENSE).

## Support

Issues and questions: open a GitHub issue, or email jason@trueformat.app
