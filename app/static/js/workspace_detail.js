(() => {
  "use strict";

  document.querySelector("[data-workspace-alert]")?.focus();

  document.querySelectorAll("[data-workspace-confirm-form]").forEach((form) => {
    const dialog = document.getElementById(form.dataset.workspaceConfirmForm);
    if (!dialog || typeof dialog.showModal !== "function") return;

    let trigger = null;
    let confirmed = false;
    const cancel = dialog.querySelector("[data-workspace-confirm-cancel]");
    const confirm = dialog.querySelector("[data-workspace-confirm-submit]");

    form.addEventListener("submit", (event) => {
      if (confirmed) {
        confirmed = false;
        return;
      }
      event.preventDefault();
      trigger = event.submitter || form.querySelector('button[type="submit"]');
      dialog.showModal();
      cancel?.focus();
    });
    cancel?.addEventListener("click", () => dialog.close("cancel"));
    confirm?.addEventListener("click", () => {
      confirmed = true;
      dialog.close("confirm");
      form.requestSubmit();
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close("cancel");
    });
    dialog.addEventListener("close", () => {
      if (trigger?.isConnected) trigger.focus();
      trigger = null;
    });
  });
})();
