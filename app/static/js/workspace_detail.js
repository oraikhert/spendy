(() => {
  "use strict";

  const form = document.querySelector("[data-leave-workspace-form]");
  const dialog = document.getElementById("leave-workspace-confirmation");
  if (!form || !dialog || typeof dialog.showModal !== "function") return;

  let trigger = null;
  let confirmed = false;
  const cancel = dialog.querySelector("[data-leave-workspace-cancel]");
  const confirm = dialog.querySelector("[data-leave-workspace-confirm]");

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
})();
