/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState } from "@odoo/owl";

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
}

registry.category("fields").add("trueformat_preview", {
    component: TrueformatPreviewField,
});
