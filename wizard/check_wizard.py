# -*- coding: utf-8 -*-
import base64
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
DEFAULT_ENDPOINT = "https://trueformat-api.onrender.com/check"
DEFAULT_FIX_ENDPOINT = "https://trueformat-api.onrender.com/fix"

# Server-side limits (MAX_UPLOAD_BYTES / CSV_SANDBOX_ROW_LIMIT on the API).
# Checked client-side too so oversized files fail fast with a clear message.
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 250000


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
                    "Add it in Settings > Technical > Parameters > "
                    "System Parameters using the key '%s'."
                )
                % PARAM_API_KEY
            )
        return endpoint, api_key

    @staticmethod
    def _format_flag(flag):
        """One report line per flag, matching the API flag shape:
        {column, row_index (0-based or null), issue_type, original_value, detail}
        """
        issue_type = flag.get("issue_type", "issue")
        column = flag.get("column", "?")
        detail = flag.get("detail", "")
        row_index = flag.get("row_index")
        original = flag.get("original_value")

        if row_index is None:
            location = _("column '%s' (whole column)") % column
        else:
            # API row_index is 0-based over data rows; show 1-based.
            location = _("column '%s', data row %s") % (column, row_index + 1)

        line = "- [%s] %s: %s" % (issue_type, location, detail)
        if original:
            line += _(" (value: %s)") % json.dumps(original)
        return line

    def _api_error_message(self, response):
        """Turn a FastAPI error response into a readable message.

        Errors come back as {"detail": "..."} with 400 (bad file / over
        limit), 401 (bad key), 429 (rate limited) or 503 (key not
        configured server-side).
        """
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
        """Validate the attached CSV and POST it to a TrueFormat endpoint.

        Returns the successful (HTTP 200) requests.Response; raises
        UserError for anything else.
        """
        if requests is None:
            raise UserError(_("The Python `requests` library is not installed on the server."))
        if not self.csv_file:
            raise UserError(_("Please attach a CSV file first."))

        filename = self.csv_filename or "upload.csv"
        if not filename.lower().endswith(".csv"):
            raise UserError(_("TrueFormat only checks .csv files."))

        _, api_key = self._get_config()
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
        icp = self.env["ir.config_parameter"].sudo()
        response = self._post_csv(icp.get_param(PARAM_ENDPOINT, DEFAULT_ENDPOINT))

        try:
            data = response.json()
        except ValueError:
            raise UserError(_("TrueFormat returned an unexpected response."))
        if data.get("status") != "success":
            raise UserError(_("TrueFormat returned an unexpected response."))

        # Success shape:
        # { "status": "success", "filename": str, "row_count": int,
        #   "column_count": int, "issues_found": int, "summary": str,
        #   "flags": [ {column, row_index, issue_type, original_value, detail} ] }
        flags = data.get("flags") or []
        detail_lines = [self._format_flag(f) for f in flags]

        self.write(
            {
                "state": "done",
                "issues_found": data.get("issues_found", len(flags)),
                "row_count": data.get("row_count", 0),
                "result_summary": data.get("summary")
                or _("No issues found — file is clean."),
                "result_detail": "\n".join(detail_lines) or _("Nothing flagged."),
            }
        )
        return self._reopen()

    def action_fix(self):
        """Fetch a corrected copy of the CSV from the TrueFormat API.

        Only safe mechanical corrections are applied server-side; issues
        needing human judgment (ambiguous dates, near-duplicates) or where
        data was destroyed (scientific-notation IDs) stay in the report
        and are not auto-fixed.
        """
        self.ensure_one()
        icp = self.env["ir.config_parameter"].sudo()
        response = self._post_csv(icp.get_param(PARAM_FIX_ENDPOINT, DEFAULT_FIX_ENDPOINT))

        if not response.content or "text/csv" not in response.headers.get("Content-Type", ""):
            raise UserError(_("TrueFormat returned an unexpected response."))

        filename = self.csv_filename or "upload.csv"
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
                "issues_found": 0,
                "row_count": 0,
                "fixed_file": False,
                "fixed_filename": False,
            }
        )
        return self._reopen()
