(() => {
  "use strict";

  function focusErrors(scope) {
    const form = scope.matches?.("[data-auth-form]") ? scope : scope.querySelector?.("[data-auth-form]");
    if (!form?.dataset.hasErrors) return;
    const target = form.querySelector('[aria-invalid="true"]') || form.querySelector(".auth-error-summary");
    target?.focus();
  }

  function updatePasswordMatch(form) {
    const password = form.elements.password;
    const confirmation = form.elements.password_confirm;
    const message = form.querySelector("[data-password-match-error]");
    if (!password || !confirmation || !message) return;
    const mismatch = Boolean(confirmation.value) && password.value !== confirmation.value;
    confirmation.setCustomValidity(mismatch ? "Passwords do not match" : "");
    if (mismatch) {
      confirmation.setAttribute("aria-invalid", "true");
      message.hidden = false;
      message.textContent = "Passwords do not match.";
    } else if (confirmation.dataset.serverError !== "true") {
      confirmation.removeAttribute("aria-invalid");
      message.hidden = true;
      message.textContent = "";
    }
  }

  document.addEventListener("input", (event) => {
    const form = event.target.closest?.("#register-form");
    if (!form) return;
    if (event.target.name === "password" || event.target.name === "password_confirm") {
      delete form.elements.password_confirm.dataset.serverError;
      updatePasswordMatch(form);
    }
  });

  document.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.xhr.status === 422 && event.detail.target?.matches?.("[data-auth-form]")) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });

  document.addEventListener("htmx:afterSwap", (event) => focusErrors(event.detail.target));
  document.addEventListener("DOMContentLoaded", () => focusErrors(document));
})();
