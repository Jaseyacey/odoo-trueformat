/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { status } from "@odoo/owl";

const WIZARD_MODEL = "trueformat.check.wizard";

const BUSY_ACTIONS = new Set([
    "action_check",
    "action_check_all",
    "action_fix",
    "action_fix_selected",
]);

function loadingMessage(actionName) {
    if (actionName === "action_fix" || actionName === "action_fix_selected") {
        return _t("Fixing CSV…");
    }
    return _t("Checking CSV…");
}

patch(FormController.prototype, {
    async beforeExecuteActionButton(clickParams) {
        const saved = await super.beforeExecuteActionButton(clickParams);
        if (saved === false) {
            return false;
        }
        if (
            this.props.resModel === WIZARD_MODEL &&
            BUSY_ACTIONS.has(clickParams.name)
        ) {
            this._trueformatShowLoading(loadingMessage(clickParams.name));
        }
        return saved;
    },

    async afterExecuteActionButton(clickParams) {
        if (
            this.props.resModel === WIZARD_MODEL &&
            status(this) !== "destroyed"
        ) {
            this._trueformatHideLoading();
        }
        return super.afterExecuteActionButton(clickParams);
    },

    _trueformatShowLoading(message) {
        this._trueformatHideLoading();
        const root = this.rootRef?.el;
        if (!root) {
            return;
        }
        root.classList.add("o_trueformat_busy_host");
        const overlay = document.createElement("div");
        overlay.className = "o_trueformat_loading_overlay";
        overlay.setAttribute("role", "status");
        overlay.setAttribute("aria-live", "polite");
        overlay.innerHTML = `
            <div class="o_trueformat_loading_overlay__panel">
                <div class="o_trueformat_loading_overlay__spinner"></div>
                <div class="o_trueformat_loading_overlay__message"></div>
            </div>
        `;
        overlay.querySelector(".o_trueformat_loading_overlay__message").textContent =
            message;
        root.appendChild(overlay);
        this._trueformatOverlayEl = overlay;
    },

    _trueformatHideLoading() {
        this._trueformatOverlayEl?.remove();
        this._trueformatOverlayEl = null;
        this.rootRef?.el?.classList.remove("o_trueformat_busy_host");
    },
});
