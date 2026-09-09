(() => {
  "use strict";

  document.querySelector("[data-workspace-alert]")?.focus();
  window.Spendy.localizeDateTimes();

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

  const renameDialog = document.getElementById("workspace-rename-dialog");
  const renameTrigger = document.querySelector("[data-workspace-rename-trigger]");
  if (renameDialog && renameTrigger && typeof renameDialog.showModal === "function") {
    const renameInput = renameDialog.querySelector("#workspace-rename-name");
    let renameReturnFocus = null;
    const openRename = (trigger) => {
      renameReturnFocus = trigger;
      renameDialog.showModal();
      renameInput?.focus();
      renameInput?.select();
    };

    renameTrigger.addEventListener("click", () => openRename(renameTrigger));
    renameDialog.querySelector("[data-workspace-rename-cancel]")?.addEventListener("click", () => renameDialog.close("cancel"));
    renameDialog.addEventListener("click", (event) => {
      if (event.target === renameDialog) renameDialog.close("cancel");
    });
    renameDialog.addEventListener("close", () => {
      if (renameReturnFocus?.isConnected) renameReturnFocus.focus();
      renameReturnFocus = null;
    });
    if (renameDialog.dataset.openOnLoad === "true" && !renameDialog.open) openRename(renameTrigger);
  }
})();
