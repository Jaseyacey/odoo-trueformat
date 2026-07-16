# -*- coding: utf-8 -*-
import base64
import csv
import io
import json
import logging
import re

from odoo import _, api, fields, models
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
# Cap local scan work so a 250k-row file does not freeze the dialog.
PREVIEW_FLAG_SCAN_LIMIT = 5000
PREVIEW_FLAG_MAX = 2000

# Mirrors trueformat_backend/routes/health.py detection so cells can be marked
# red even though /api/check does not return per-cell flags.
_SCI_PATTERN = re.compile(r"^[+-]?\d+(\.\d+)?[Ee][+-]?\d+$")
_DATE_TOKEN_PATTERNS = (
    re.compile(r"^\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?$"),
    re.compile(r"^\d{1,2}-[A-Za-z]{3}$"),
    re.compile(r"^[A-Za-z]{3}-\d{1,2}$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
)
_MONTH_TOKEN_PATTERN = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.IGNORECASE
)


class TrueFormatApiMixin(models.AbstractModel):
    """Shared TrueFormat API helpers used by the wizard and its file lines."""

    _name = "trueformat.api.mixin"
    _description = "TrueFormat API Helpers"

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
        if response.status_code == 402:
            return _(
                "Your TrueFormat subscription is inactive. Renew your plan to "
                "continue using the API."
            )
        if response.status_code == 404:
            return _(
                "The TrueFormat server does not provide this endpoint (HTTP 404).\n\n"
                "Check that '%(endpoint_param)s' / '%(fix_param)s' point at "
                "https://trueformat.onrender.com (not trueformat-api.onrender.com)."
            ) % {"endpoint_param": PARAM_ENDPOINT, "fix_param": PARAM_FIX_ENDPOINT}
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

    def _post_file_bytes(self, endpoint, filename, file_bytes):
        """POST CSV bytes to a TrueFormat endpoint."""
        if requests is None:
            raise UserError(_("The Python `requests` library is not installed on the server."))

        _unused_endpoint, api_key = self._get_config()

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

    @staticmethod
    def _extract_fixed_csv(response):
        """Normalize fix endpoint responses into raw CSV bytes."""
        content_type = (response.headers.get("Content-Type") or "").lower()

        # Primary path: endpoint returns the CSV file directly.
        if "text/csv" in content_type or "application/octet-stream" in content_type:
            if response.content:
                return response.content
            raise UserError(_("TrueFormat returned an empty corrected file."))

        # Fallback path: endpoint returns JSON with corrected CSV payload.
        try:
            payload = response.json()
        except ValueError:
            raise UserError(_("TrueFormat returned an unexpected response."))

        b64_value = (
            payload.get("fixed_csv_base64")
            or payload.get("fixed_file_base64")
            or payload.get("file_base64")
        )
        if b64_value:
            try:
                return base64.b64decode(b64_value)
            except Exception:
                raise UserError(_("TrueFormat returned an invalid corrected file."))

        text_value = payload.get("fixed_csv") or payload.get("csv")
        if text_value is not None:
            return text_value.encode("utf-8")

        raise UserError(_("TrueFormat returned an unexpected response."))

    @staticmethod
    def _b64_store(raw_bytes):
        """Encode raw file bytes for an Odoo Binary field (ASCII str, not bytes)."""
        return base64.b64encode(raw_bytes).decode("ascii")

    @staticmethod
    def _user_error_text(exc):
        if exc.args:
            return str(exc.args[0])
        return str(exc)


class TrueFormatCheckWizardLine(models.TransientModel):
    _name = "trueformat.check.wizard.line"
    _description = "TrueFormat CSV Check File"
    _inherit = "trueformat.api.mixin"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "trueformat.check.wizard",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    # attachment=False keeps bytes on the transient record so the dialog download
    # still has the corrected payload after _reopen().
    csv_file = fields.Binary(string="CSV File", required=True, attachment=False)
    csv_filename = fields.Char(string="Filename")
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("checked", "Checked"),
            ("fixed", "Fixed"),
            ("error", "Error"),
        ],
        string="Status",
        default="pending",
        readonly=True,
    )
    issues_found = fields.Integer(string="Issues Found", readonly=True)
    row_count = fields.Integer(string="Rows Checked", readonly=True)
    result_summary = fields.Char(string="Summary", readonly=True)
    result_detail = fields.Text(string="Report", readonly=True)
    preview_data = fields.Text(string="Preview Data", readonly=True)
    fixed_file = fields.Binary(string="Corrected File", readonly=True, attachment=False)
    fixed_filename = fields.Char(readonly=True)
    error_message = fields.Char(string="Error", readonly=True)

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

    @staticmethod
    def _is_probable_date_token(value):
        token = (value or "").strip()
        if not token:
            return False
        if any(pattern.match(token) for pattern in _DATE_TOKEN_PATTERNS):
            return True
        if _MONTH_TOKEN_PATTERN.search(token) and any(ch.isdigit() for ch in token):
            return True
        return False

    def _scan_preview_flags(self, file_bytes, check_data):
        """Build per-cell flags for the preview ( /api/check has no flags array )."""
        text = file_bytes.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return []

        header = rows[0]
        data_rows = rows[1 : 1 + PREVIEW_FLAG_SCAN_LIMIT]
        cols = (check_data or {}).get("columns") or {}
        transaction_col = cols.get("transaction_id")
        batch_col = cols.get("batch")

        header_index = {name: idx for idx, name in enumerate(header)}
        batch_idx = header_index.get(batch_col) if batch_col else None
        max_batch_len = 0
        if batch_idx is not None:
            for row in data_rows:
                if batch_idx >= len(row):
                    continue
                value = (row[batch_idx] or "").strip()
                if value.isdigit():
                    max_batch_len = max(max_batch_len, len(value))

        flags = []
        for row_index, row in enumerate(data_rows):
            if len(flags) >= PREVIEW_FLAG_MAX:
                break
            for col_index, column_name in enumerate(header):
                value = (row[col_index] if col_index < len(row) else "").strip()
                if not value:
                    continue

                if _SCI_PATTERN.match(value):
                    flags.append(
                        {
                            "column": column_name,
                            "row_index": row_index,
                            "issue_type": "scientific_notation",
                            "detail": "Scientific notation: %s" % value,
                        }
                    )
                elif column_name == transaction_col and self._is_probable_date_token(value):
                    flags.append(
                        {
                            "column": column_name,
                            "row_index": row_index,
                            "issue_type": "sku_corruption",
                            "detail": "Date-like token in identifier column: %s" % value,
                        }
                    )
                elif (
                    column_name == batch_col
                    and max_batch_len >= 3
                    and value.isdigit()
                    and len(value) < max_batch_len
                ):
                    flags.append(
                        {
                            "column": column_name,
                            "row_index": row_index,
                            "issue_type": "missing_leading_zero",
                            "detail": "Possible stripped leading zero: %s" % value,
                        }
                    )

                if len(flags) >= PREVIEW_FLAG_MAX:
                    break
        return flags

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
        if self.fixed_file and issues:
            detail_lines += [
                "",
                _(
                    "A corrected file is attached below. Re-download it if you "
                    "need the latest Fix All Columns output."
                ),
            ]
        flags = data.get("flags") or self._scan_preview_flags(file_bytes, data)
        preview = self._build_preview_data(file_bytes, flags, rows)

        state = "fixed" if self.fixed_file else "checked"
        self.write(
            {
                "state": state,
                "issues_found": issues,
                "row_count": rows,
                "result_summary": summary,
                "result_detail": "\n".join(detail_lines),
                "preview_data": json.dumps(preview),
                "error_message": False,
            }
        )

    def _run_check(self):
        """POST this line's CSV to /api/check and store results on the line."""
        self.ensure_one()
        filename, file_bytes = self._validate_csv_upload()
        icp = self.env["ir.config_parameter"].sudo()
        endpoint = icp.get_param(PARAM_ENDPOINT, DEFAULT_ENDPOINT)
        response = self.wizard_id._post_file_bytes(endpoint, filename, file_bytes)

        try:
            data = response.json()
        except ValueError:
            raise UserError(_("TrueFormat returned an unexpected response."))
        if data.get("status") != "ok":
            raise UserError(_("TrueFormat returned an unexpected response."))

        self._apply_check_result(data, file_bytes)

    def _mark_error(self, exc):
        self.write(
            {
                "state": "error",
                "error_message": self._user_error_text(exc),
                "issues_found": 0,
                "row_count": 0,
                "result_summary": False,
                "result_detail": False,
                "preview_data": False,
            }
        )

    def action_check(self):
        """Check this file only."""
        self.ensure_one()
        try:
            self._run_check()
        except UserError as exc:
            self._mark_error(exc)
        self.wizard_id.selected_line_id = self
        return self.wizard_id._reopen()

    def action_fix(self):
        """Fetch a corrected copy of this line's CSV from the TrueFormat API."""
        self.ensure_one()
        try:
            filename, file_bytes = self._validate_csv_upload()
            icp = self.env["ir.config_parameter"].sudo()
            fix_endpoint = icp.get_param(PARAM_FIX_ENDPOINT, DEFAULT_FIX_ENDPOINT)
            response = self.wizard_id._post_file_bytes(fix_endpoint, filename, file_bytes)
            fixed_bytes = self._extract_fixed_csv(response)

            fixed_b64 = self._b64_store(fixed_bytes)
            fixed_name = "fixed_%s" % filename

            self.write(
                {
                    "fixed_file": fixed_b64,
                    "fixed_filename": fixed_name,
                    "csv_file": fixed_b64,
                    "csv_filename": fixed_name,
                }
            )

            check_response = self.wizard_id._post_file_bytes(
                icp.get_param(PARAM_ENDPOINT, DEFAULT_ENDPOINT),
                fixed_name,
                fixed_bytes,
            )
            try:
                check_data = check_response.json()
            except ValueError:
                raise UserError(_("TrueFormat returned an unexpected response."))
            if check_data.get("status") != "ok":
                raise UserError(_("TrueFormat returned an unexpected response."))

            self._apply_check_result(check_data, fixed_bytes)
        except UserError as exc:
            self._mark_error(exc)
        self.wizard_id.selected_line_id = self
        return self.wizard_id._reopen()

    def action_show_detail(self):
        """Open this line's preview and results in the wizard detail panel."""
        self.ensure_one()
        self.wizard_id.selected_line_id = self
        return self.wizard_id._reopen()


class TrueFormatCheckWizard(models.TransientModel):
    _name = "trueformat.check.wizard"
    _description = "TrueFormat CSV Integrity Check"
    _inherit = "trueformat.api.mixin"

    line_ids = fields.One2many(
        "trueformat.check.wizard.line",
        "wizard_id",
        string="CSV Files",
    )
    selected_line_id = fields.Many2one(
        "trueformat.check.wizard.line",
        string="Selected File",
        domain="[('wizard_id', '=', id)]",
        ondelete="set null",
    )
    batch_summary = fields.Char(string="Batch Summary", readonly=True)

    # Computed mirrors of the selected line — used by the detail panel and preview
    # widget so each file's preview stays isolated to its own line record.
    result_summary = fields.Char(compute="_compute_selected_line_display", readonly=True)
    result_detail = fields.Text(compute="_compute_selected_line_display", readonly=True)
    issues_found = fields.Integer(compute="_compute_selected_line_display", readonly=True)
    row_count = fields.Integer(compute="_compute_selected_line_display", readonly=True)
    preview_data = fields.Text(compute="_compute_selected_line_display", readonly=True)
    fixed_file = fields.Binary(compute="_compute_selected_line_display", readonly=True)
    fixed_filename = fields.Char(compute="_compute_selected_line_display", readonly=True)
    selected_state = fields.Selection(
        related="selected_line_id.state",
        readonly=True,
    )
    selected_error_message = fields.Char(
        related="selected_line_id.error_message",
        readonly=True,
    )
    selected_csv_filename = fields.Char(
        related="selected_line_id.csv_filename",
        readonly=True,
    )

    @api.depends(
        "selected_line_id",
        "selected_line_id.result_summary",
        "selected_line_id.result_detail",
        "selected_line_id.issues_found",
        "selected_line_id.row_count",
        "selected_line_id.preview_data",
        "selected_line_id.fixed_file",
        "selected_line_id.fixed_filename",
    )
    def _compute_selected_line_display(self):
        for wizard in self:
            line = wizard.selected_line_id
            if line:
                wizard.result_summary = line.result_summary
                wizard.result_detail = line.result_detail
                wizard.issues_found = line.issues_found
                wizard.row_count = line.row_count
                wizard.preview_data = line.preview_data
                wizard.fixed_file = line.fixed_file
                wizard.fixed_filename = line.fixed_filename
            else:
                wizard.result_summary = False
                wizard.result_detail = False
                wizard.issues_found = 0
                wizard.row_count = 0
                wizard.preview_data = False
                wizard.fixed_file = False
                wizard.fixed_filename = False

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_check_all(self):
        """Check every pending line sequentially; failures do not abort the batch."""
        self.ensure_one()
        pending_lines = self.line_ids.filtered(lambda line: line.state == "pending")
        if not pending_lines:
            raise UserError(_("Add at least one CSV file with Pending status to check."))

        checked = 0
        failed = 0
        total_issues = 0
        last_line = False

        for line in pending_lines:
            try:
                line._run_check()
                checked += 1
                total_issues += line.issues_found
                last_line = line
            except UserError as exc:
                failed += 1
                line._mark_error(exc)
                last_line = line

        summary = _(
            "%(checked)s checked, %(failed)s failed, %(issues)s total issues"
        ) % {
            "checked": checked,
            "failed": failed,
            "issues": total_issues,
        }
        self.write(
            {
                "batch_summary": summary,
                "selected_line_id": last_line.id if last_line else False,
            }
        )

        notification_type = "warning" if failed else "success"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Check All complete"),
                "message": summary,
                "type": notification_type,
                "sticky": False,
                "next": self._reopen(),
            },
        }

    def action_fix_selected(self):
        """Fix the file currently shown in the detail panel."""
        self.ensure_one()
        if not self.selected_line_id:
            raise UserError(_("Select a checked file first."))
        return self.selected_line_id.action_fix()

    def action_reset(self):
        """Clear all files and start a new session."""
        self.ensure_one()
        self.write(
            {
                "line_ids": [(5, 0, 0)],
                "selected_line_id": False,
                "batch_summary": False,
            }
        )
        return self._reopen()
