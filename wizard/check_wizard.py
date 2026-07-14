# -*- coding: utf-8 -*-
import base64
import csv
import io
import json
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    requests = None
    _logger.warning("The `requests` library is required for the TrueFormat module.")

# Config keys stored in System Parameters (Settings > Technical > Parameters).
PARAM_ENDPOINT = "trueformat.api_endpoint"
PARAM_FIX_ENDPOINT = "trueformat.api_fix_endpoint"
PARAM_API_KEY = "trueformat.api_key"
DEFAULT_ENDPOINT = "https://trueformat.onrender.com/api/check"
DEFAULT_FIX_ENDPOINT = "https://trueformat.onrender.com/api/fix" 


# Server-side limits (MAX_UPLOAD_BYTES / CSV_SANDBOX_ROW_LIMIT on the API).
MAX_FILE_BYTES = 20 * 1024 * 1024
PREVIEW_ROW_LIMIT = 1000


class TrueFormatCheckWizard(models.TransientModel):
    _name = "trueformat.check.wizard"
    _description = "TrueFormat CSV Integrity Check"

    csv_file = fields.Binary(string="CSV File", required=True)
    csv_filename = fields.Char(string="Filename")

    state = fields.Selection(
        [("draft", "Upload"), ("done", "Result")],
        default="draft",
    )
    result_summary = fields.Char(string="Summary", readonly=True)
    result_detail = fields.Text(string="Report", readonly=True)
    issues_found = fields.Integer(string="Issues Found", readonly=True)
    row_count = fields.Integer(string="Rows Checked", readonly=True)
    preview_data = fields.Text(string="Preview Data", readonly=True)
    fixed_file = fields.Binary(string="Corrected File", readonly=True)
    fixed_filename = fields.Char(readonly=True)

    def _get_config(self):
        """Read endpoint + API key from system parameters."""
        icp = self.env["ir.config_parameter"].sudo()
        endpoint = icp.get_param(PARAM_ENDPOINT, DEFAULT_ENDPOINT)
        api_key = icp.get_param(PARAM_API_KEY, "")
        if not api_key:
            raise UserError(
                _(
                    "No TrueFormat API key set.\n\n"
                    "Add your API key in Settings > Technical > Parameters > "
                    "System Parameters using the key '%s'."
                )
                % PARAM_API_KEY
            )
        return endpoint, api_key

    def _api_error_message(self, response):
        """Turn a FastAPI error response into a readable message."""
        try:
            detail = response.json().get("detail", "")
        except ValueError:
            detail = ""

        if response.status_code == 401:
            return _(
                "TrueFormat rejected the API key. Check the '%s' system parameter."
            ) % PARAM_API_KEY
        if response.status_code == 503:
            return _(
                "The TrueFormat server has no integration API key configured. %s"
            ) % detail
        if response.status_code == 429:
            return _("Too many requests to TrueFormat. Please wait a moment and retry.")
        if response.status_code == 400 and detail:
            return _("TrueFormat could not check the file: %s") % detail
        return _("TrueFormat returned an error (HTTP %s). %s") % (
            response.status_code,
            detail,
        )

    def _post_csv(self, endpoint):
        """Validate the attached CSV and POST it to a TrueFormat endpoint."""
        if requests is None:
            raise UserError(_("The Python `requests` library is not installed on the server."))
        if not self.csv_file:
            raise UserError(_("Please attach a CSV file first."))

        filename = self.csv_filename or "upload.csv"
        if not filename.lower().endswith(".csv"):
            raise UserError(_("TrueFormat only checks .csv files."))

        _endpoint, api_key = self._get_config()
        file_bytes = base64.b64decode(self.csv_file)
        if len(file_bytes) > MAX_FILE_BYTES:
            raise UserError(
                _("The file is larger than the 20 MB limit of the TrueFormat API.")
            )

        try:
            response = requests.post(
                endpoint,
                headers={"Authorization": "Bearer %s" % api_key},
                files={"file": (filename, file_bytes, "text/csv")},
                timeout=120,
            )
        except requests.exceptions.Timeout:
            raise UserError(_("TrueFormat did not respond in time. Please try again."))
        except requests.exceptions.RequestException as exc:
            _logger.exception("TrueFormat API call failed")
            raise UserError(_("Could not reach TrueFormat: %s") % exc)

        if response.status_code != 200:
            raise UserError(self._api_error_message(response))
        return response

    def _validate_csv_upload(self):
        if not self.csv_file:
            raise UserError(_("Please attach a CSV file first."))

        filename = self.csv_filename or "upload.csv"
        if not filename.lower().endswith(".csv"):
            raise UserError(_("TrueFormat only checks .csv files."))

        file_bytes = base64.b64decode(self.csv_file)
        if len(file_bytes) > MAX_FILE_BYTES:
            raise UserError(
                _("The file is larger than the 20 MB limit of the TrueFormat API.")
            )
        return filename, file_bytes

    def _build_preview_data(self, file_bytes, flags, total_rows):
        """Build JSON payload for the interactive preview widget."""
        text = file_bytes.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        header = rows[0] if rows else []
        data_rows = rows[1:] if len(rows) > 1 else []

        error_cells = {}
        column_counts = {}
        error_row_indices = set()

        for flag in flags:
            column = flag.get("column")
            row_index = flag.get("row_index")
            if column:
                column_counts[column] = column_counts.get(column, 0) + 1
            if row_index is not None and column:
                error_cells.setdefault((row_index, column), []).append(flag)
                error_row_indices.add(row_index)

        preview_indices = []
        for row_index in sorted(error_row_indices):
            if len(preview_indices) >= PREVIEW_ROW_LIMIT:
                break
            preview_indices.append(row_index)
        for row_index in range(len(data_rows)):
            if len(preview_indices) >= PREVIEW_ROW_LIMIT:
                break
            if row_index not in error_row_indices:
                preview_indices.append(row_index)

        preview_rows = []
        for row_index in preview_indices:
            row = data_rows[row_index] if row_index < len(data_rows) else []
            cells = []
            for col_index, column_name in enumerate(header):
                value = row[col_index] if col_index < len(row) else ""
                cell_flags = error_cells.get((row_index, column_name), [])
                cells.append(
                    {
                        "value": value,
                        "has_error": bool(cell_flags),
                        "issues": [
                            {
                                "issue_type": f.get("issue_type", "issue"),
                                "detail": f.get("detail", ""),
                            }
                            for f in cell_flags
                        ],
                    }
                )
            preview_rows.append(
                {
                    "row_index": row_index,
                    "has_error": row_index in error_row_indices,
                    "cells": cells,
                }
            )

        return {
            "headers": [
                {
                    "name": column_name,
                    "issue_count": column_counts.get(column_name, 0),
                    "has_issues": column_counts.get(column_name, 0) > 0,
                }
                for column_name in header
            ],
            "rows": preview_rows,
            "preview_row_count": len(preview_rows),
            "total_row_count": total_rows,
            "total_issues": sum(column_counts.values()) or len(flags),
        }

    def _apply_check_result(self, data, file_bytes):
        # Parse TrueFormat's actual response shape
        summary_data = data.get("summary", {}) or {}
        if not isinstance(summary_data, dict):
            summary_data = {}
        issues = summary_data.get("issue_count", 0)
        rows = summary_data.get("rows_checked", 0)

        sci = summary_data.get("scientific_notation_count", 0)
        zeros = summary_data.get("missing_leading_zero_count", 0)
        sku = summary_data.get("sku_corruption_count", 0)

        cols = data.get("columns", {}) or {}
        sci_cols = ", ".join(cols.get("scientific_notation_columns") or []) or "-"

        examples = data.get("examples", {}) or {}
        sku_examples = ", ".join(str(e) for e in (examples.get("sku") or [])[:5])

        summary = (
            _("No issues found - file is clean. %s rows checked.") % rows
            if not issues
            else _("%(issues)s issue(s) found across %(rows)s rows.") % {"issues": issues, "rows": rows}
        )

        detail_lines = [
            _("Rows checked: %s") % rows,
            _("Total issues: %s") % issues,
            "",
            _("Scientific notation: %s") % sci,
            _("Stripped leading zeros: %s") % zeros,
            _("SKU corruption: %s") % sku,
            "",
            _("Affected columns: %s") % sci_cols,
        ]
        if sku_examples:
            detail_lines += ["", _("Examples of corrupted values: %s") % sku_examples]

        flags = data.get("flags") or []
        preview = self._build_preview_data(file_bytes, flags, rows)

        self.write(
            {
                "state": "done",
                "issues_found": issues,
                "row_count": rows,
                "result_summary": summary,
                "result_detail": "\n".join(detail_lines),
                "preview_data": json.dumps(preview),
            }
        )

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_check(self):
        """Send the uploaded CSV to the TrueFormat API and show the result."""
        self.ensure_one()
        filename, file_bytes = self._validate_csv_upload()
        icp = self.env["ir.config_parameter"].sudo()
        response = self._post_csv(icp.get_param(PARAM_ENDPOINT, DEFAULT_ENDPOINT))

        try:
            data = response.json()
        except ValueError:
            raise UserError(_("TrueFormat returned an unexpected response."))
        if data.get("status") != "ok":
            raise UserError(_("TrueFormat returned an unexpected response."))

        self._apply_check_result(data, file_bytes)
        return self._reopen()

    def action_fix(self):
        """Fetch a corrected copy of the CSV from the TrueFormat API."""
        self.ensure_one()
        filename, file_bytes = self._validate_csv_upload()
        icp = self.env["ir.config_parameter"].sudo()
        response = self._post_csv(icp.get_param(PARAM_FIX_ENDPOINT, DEFAULT_FIX_ENDPOINT))

        if not response.content or "text/csv" not in response.headers.get(
            "Content-Type", ""
        ):
            raise UserError(_("TrueFormat returned an unexpected response."))

        self.write(
            {
                "fixed_file": base64.b64encode(response.content),
                "fixed_filename": "fixed_%s" % filename,
            }
        )
        return self._reopen()

    def action_reset(self):
        self.ensure_one()
        self.write(
            {
                "state": "draft",
                "result_summary": False,
                "result_detail": False,
                "preview_data": False,
                "issues_found": 0,
                "row_count": 0,
                "fixed_file": False,
                "fixed_filename": False,
            }
        )
        return self._reopen()
