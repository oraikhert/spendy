(() => {
  "use strict";

  document.querySelector("[data-workspace-page-alert]")?.focus();

  const dialog = document.getElementById("create-workspace-dialog");
  const trigger = document.querySelector("[data-create-workspace-trigger]");
  if (!dialog || !trigger || typeof dialog.showModal !== "function") return;

  const input = dialog.querySelector("#workspace-name");
  let returnFocus = null;
  const open = (opener) => {
    returnFocus = opener;
    dialog.showModal();
    input?.focus();
  };

  trigger.addEventListener("click", () => open(trigger));
  dialog.querySelector("[data-create-workspace-cancel]")?.addEventListener("click", () => dialog.close("cancel"));
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close("cancel");
  });
  dialog.addEventListener("close", () => {
    if (returnFocus?.isConnected) returnFocus.focus();
    returnFocus = null;
  });

  if (dialog.dataset.openOnLoad === "true" && !dialog.open) open(null);
})();
