/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState } from "@odoo/owl";

/** Amber/warning severity — reconstruction & soft detection modules. */
const WARNING_ISSUE_TYPES = new Set([
    "reconstructed",
    "hidden_character",
    "hidden_characters",
    "ambiguous_date",
    "normalized_duplicate",
    "normalized_duplicates",
    "mixed_date_formats",
    "mixed_formats",
]);

/** Red/error severity — classic SKU / format corruption. */
const ERROR_ISSUE_TYPES = new Set([
    "scientific_notation",
    "missing_leading_zero",
    "sku_corruption",
    "format_flip",
    "format_flips",
]);

export class TrueformatPreviewField extends Component {
    static template = "trueformat.PreviewField";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.state = useState({
            errorsOnly: false,
        });
    }

    get preview() {
        const raw = this.props.record.data.preview_data;
        if (!raw) {
            return {};
        }
        try {
            return JSON.parse(raw);
        } catch {
            return {};
        }
    }

    get hasPreview() {
        return Boolean(this.preview.headers && this.preview.headers.length);
    }

    get displayRows() {
        const rows = this.preview.rows || [];
        if (!this.state.errorsOnly) {
            return rows;
        }
        return rows.filter((row) => row.has_error);
    }

    get visibleRowCount() {
        return this.displayRows.length;
    }

    setErrorsOnly(errorsOnly) {
        this.state.errorsOnly = errorsOnly;
    }

    cellTitle(cell) {
        if (!cell.has_error || !cell.issues || !cell.issues.length) {
            return "";
        }
        return cell.issues
            .map((issue) => `[${issue.issue_type}] ${issue.detail}`)
            .join("\n");
    }

    cellIssueTypes(cell) {
        if (!cell.issues || !cell.issues.length) {
            return [];
        }
        const seen = new Set();
        const types = [];
        for (const issue of cell.issues) {
            const type = issue.issue_type || "issue";
            if (seen.has(type)) {
                continue;
            }
            seen.add(type);
            types.push(type);
        }
        return types;
    }

    cellSeverity(cell) {
        if (!cell.has_error) {
            return null;
        }
        const types = this.cellIssueTypes(cell);
        if (types.some((t) => ERROR_ISSUE_TYPES.has(t))) {
            return "error";
        }
        if (types.some((t) => WARNING_ISSUE_TYPES.has(t))) {
            return "warning";
        }
        // Default: treat unknown detection types as warnings (reconstructed-like).
        if (types.length) {
            return "warning";
        }
        return "error";
    }

    cellClass(cell) {
        const severity = this.cellSeverity(cell);
        if (severity === "warning") {
            return "o_trueformat_preview__cell--warning";
        }
        if (severity === "error") {
            return "o_trueformat_preview__cell--error";
        }
        return "";
    }

    badgeClass(issueType) {
        if (ERROR_ISSUE_TYPES.has(issueType)) {
            return "o_trueformat_preview__badge o_trueformat_preview__badge--error";
        }
        return "o_trueformat_preview__badge o_trueformat_preview__badge--warning";
    }

    formatIssueType(issueType) {
        return String(issueType || "issue").replace(/_/g, " ");
    }
}

registry.category("fields").add("trueformat_preview", {
    component: TrueformatPreviewField,
});
