(() => {
  "use strict";

  // Bank data must never enter HTMX's localStorage history cache. Back/Forward
  // uses a fresh server GET so the controls, permissions, and rows stay current.
  if (window.htmx) {
    window.htmx.config.historyEnabled = false;
    window.htmx.config.historyCacheSize = 0;
  }

  const snapshots = new WeakMap();
  const initialized = new WeakSet();
  const moveDialogs = new WeakSet();
  const pendingRequests = new WeakMap();
  let allowLeave = false;
  let dialogAction = null;
  let dialogTrigger = null;
  let retryRead = null;

  const editor = () => document.querySelector("[data-transaction-editor]");
  const mutationForm = (element) => element instanceof Element
    ? element.closest("form[data-transaction-mutation]") : null;

  function localizeDateTimes(scope = document) {
    const dates = scope.matches?.("[data-local-datetime]") ? [scope] : [];
    dates.push(...scope.querySelectorAll("[data-local-datetime]"));
    dates.forEach((element) => {
      const value = new Date(element.dateTime);
      if (Number.isNaN(value.getTime())) return;
      try {
        const formatter = new Intl.DateTimeFormat("en-US", {
          weekday: "short", day: "2-digit", month: "short", year: "numeric",
          hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
        });
        const parts = Object.fromEntries(formatter.formatToParts(value).map((part) => [part.type, part.value]));
        element.textContent = `${parts.weekday}, ${parts.day} ${parts.month} ${parts.year} ${parts.hour}:${parts.minute}:${parts.second}`;
      } catch (_) {
        // Keep the server-rendered value when the browser cannot format dates.
      }
    });
  }

  function snapshot(form) {
    return JSON.stringify(Array.from(new FormData(form).entries()).filter(([name]) =>
      !["csrf_token", "return_url", "confirmed"].includes(name)));
  }

  function isDirty() {
    const form = editor();
    return !!form && !allowLeave && (form.dataset.hasErrors === "true" ||
      snapshots.get(form) !== snapshot(form));
  }

  function focusInvalid(scope) {
    const invalid = scope.querySelector('[aria-invalid="true"]');
    if (invalid) {
      let parent = invalid.parentElement;
      while (parent) {
        if (parent instanceof HTMLDetailsElement) parent.open = true;
        parent = parent.parentElement;
      }
      invalid.focus();
    } else {
      scope.querySelector("[data-error-summary]")?.focus();
    }
  }

  function announceFilter(form, message) {
    let status = form.querySelector("[data-filter-status]");
    if (!status) {
      status = document.createElement("p");
      status.dataset.filterStatus = "";
      status.className = "sr-only";
      status.setAttribute("role", "status");
      form.append(status);
    }
    status.textContent = message;
  }

  function initializeFilters(form) {
    const period = form.elements.period;
    const customDates = form.querySelector("[data-custom-dates]");
    function showDates() {
      const custom = period.value === "custom";
      customDates.hidden = !custom;
      customDates.querySelectorAll("input").forEach((input) => {
        input.disabled = !custom;
        input.required = custom;
      });
    }
    period.addEventListener("change", showDates);
    showDates();

    const account = form.elements.account_id;
    const card = form.elements.card_id;
    function updateCards(changed) {
      const selected = card.selectedOptions[0];
      if (changed && account.value && selected?.value && selected.dataset.accountId !== account.value) {
        card.value = "";
        announceFilter(form, "Card reset to All cards for the selected account.");
      }
      Array.from(card.options).forEach((option) => {
        const incompatible = !!option.value && !!account.value && option.dataset.accountId !== account.value;
        // Preserve an invalid submitted option until the user changes Account,
        // allowing the server error and the user's selection to stay visible.
        option.hidden = incompatible && !option.selected;
        option.disabled = incompatible && !option.selected;
      });
    }
    account.addEventListener("change", () => updateCards(true));
    updateCards(false);

    const currency = form.elements.currency;
    let previousCurrency = currency.value.trim().toUpperCase();
    currency.addEventListener("input", () => {
      const current = currency.value.trim().toUpperCase();
      if (current !== previousCurrency) {
        const hadBounds = form.elements.min_abs_amount.value || form.elements.max_abs_amount.value;
        form.elements.min_abs_amount.value = "";
        form.elements.max_abs_amount.value = "";
        if (hadBounds) announceFilter(form, "Amount bounds cleared because the currency changed.");
      }
      previousCurrency = current;
    });
  }

  function initializeEditor(form) {
    const currency = form.elements.currency;
    const card = form.elements.card_id;
    const details = form.querySelector("[data-more-details]");
    let currencyTouched = form.dataset.editing === "true" || form.elements.currency_manually_edited.value === "yes";
    currency.addEventListener("input", () => {
      currencyTouched = true;
      form.elements.currency_manually_edited.value = "yes";
    });
    if (card instanceof HTMLSelectElement) {
      card.addEventListener("change", () => {
        if (!currencyTouched) {
          currency.value = card.selectedOptions[0]?.dataset.currency || "";
          updateFxLabels();
        }
      });
    }

    function updateFxLabels() {
      form.querySelector("[data-currency-label]").textContent = currency.value.trim().toUpperCase() || "transaction currency";
      form.querySelector("[data-original-currency-label]").textContent = form.elements.original_currency.value.trim().toUpperCase() || "original currency";
    }
    function revealFx() {
      if (form.elements.original_amount.value || form.elements.original_currency.value || form.elements.fx_rate.value) {
        details.open = true;
      }
      updateFxLabels();
    }
    form.elements.amount.addEventListener("input", revealFx);
    currency.addEventListener("input", revealFx);
    [form.elements.original_amount, form.elements.original_currency].forEach((input) => {
      input.addEventListener("input", () => {
        if (!form.elements.original_amount.value.trim() && !form.elements.original_currency.value.trim()) {
          form.elements.fx_rate.value = "";
        }
        updateFxLabels();
      });
    });
    snapshots.set(form, snapshot(form));
    if (form.dataset.saveBlocked === "true") blockMutation(form, "Refresh this page before trying to save again.");
  }

  function initialize(scope = document) {
    localizeDateTimes(scope);
    const forms = scope.matches?.("form") ? [scope] : [];
    forms.push(...scope.querySelectorAll("[data-transaction-filters], [data-transaction-editor]"));
    forms.forEach((form) => {
      if (initialized.has(form)) return;
      initialized.add(form);
      if (form.matches("[data-transaction-filters]")) initializeFilters(form);
      if (form.matches("[data-transaction-editor]")) initializeEditor(form);
    });
    const dialogs = scope.matches?.("#move-observation-dialog") ? [scope] : [];
    dialogs.push(...scope.querySelectorAll("#move-observation-dialog"));
    dialogs.forEach((dialog) => {
      if (!moveDialogs.has(dialog)) {
        moveDialogs.add(dialog);
        dialog.querySelector("[data-move-observation-cancel]")?.addEventListener("click", () => dialog.close("cancel"));
        dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close("cancel"); });
      }
      if (dialog.dataset.openOnLoad === "true" && !dialog.open) dialog.showModal();
    });
  }

  function askConfirmation({title, message, label, trigger, action}) {
    const dialog = document.getElementById("transaction-confirmation");
    if (!dialog || typeof dialog.showModal !== "function") {
      if (window.confirm(`${title}\n\n${message}`)) action();
      return;
    }
    dialogTrigger = trigger;
    dialogAction = action;
    document.getElementById("confirmation-title").textContent = title;
    document.getElementById("confirmation-message").textContent = message;
    dialog.querySelector("[data-dialog-confirm]").textContent = label;
    dialog.showModal();
    dialog.querySelector("[data-dialog-cancel]").focus();
  }

  function setSaving(form) {
    form.dataset.mutationState = "saving";
    form.setAttribute("aria-busy", "true");
    form.querySelectorAll('button[type="submit"]').forEach((button) => {
      button.dataset.idleText = button.textContent;
      button.disabled = true;
      button.textContent = "Saving…";
    });
    const status = form.querySelector("[data-mutation-status]");
    if (status) status.textContent = "Saving…";
  }

  function clearSaving(form) {
    if (!form || form.dataset.mutationState === "blocked") return;
    delete form.dataset.mutationState;
    form.removeAttribute("aria-busy");
    form.querySelectorAll("button[data-idle-text]").forEach((button) => {
      button.disabled = false;
      button.textContent = button.dataset.idleText;
      delete button.dataset.idleText;
    });
    const status = form.querySelector("[data-mutation-status]");
    if (status) status.textContent = "";
  }

  function blockMutation(form, message) {
    if (!form) return;
    form.dataset.mutationState = "blocked";
    form.removeAttribute("aria-busy");
    form.querySelectorAll('button[type="submit"]').forEach((button) => {
      button.disabled = true;
      if (button.dataset.idleText) button.textContent = button.dataset.idleText;
    });
    const status = form.querySelector("[data-mutation-status]");
    if (status) {
      status.replaceChildren(document.createTextNode(message + " "));
      const refresh = document.createElement("button");
      refresh.type = "button";
      refresh.className = "link font-medium";
      refresh.textContent = "Refresh page";
      refresh.addEventListener("click", () => {
        allowLeave = true;
        window.location.reload();
      });
      status.append(refresh);
      status.setAttribute("role", "alert");
    }
  }

  function showRequestError(message, retry, backUrl) {
    const banner = document.getElementById("transaction-request-error");
    if (!banner) return;
    banner.replaceChildren(document.createTextNode(message + " "));
    if (retry) {
      retryRead = retry;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "link font-semibold";
      button.textContent = "Retry";
      button.addEventListener("click", () => { banner.hidden = true; retryRead?.(); });
      banner.append(button);
    }
    if (backUrl) {
      const back = document.createElement("a");
      back.className = "link font-semibold";
      back.href = backUrl;
      back.textContent = "Back to transactions";
      banner.append(back);
    }
    banner.hidden = false;
  }

  document.addEventListener("submit", (event) => {
    const form = mutationForm(event.target);
    if (!form) return;
    if (form.dataset.mutationState) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    if (form.dataset.confirmTitle && form.elements.confirmed?.value !== "yes") {
      event.preventDefault();
      event.stopImmediatePropagation();
      const submitter = event.submitter;
      askConfirmation({
        title: form.dataset.confirmTitle,
        message: form.dataset.confirmMessage,
        label: form.dataset.confirmLabel,
        trigger: submitter,
        action: () => {
          const confirmed = document.createElement("input");
          confirmed.type = "hidden";
          confirmed.name = "confirmed";
          confirmed.value = "yes";
          form.append(confirmed);
          form.requestSubmit(submitter);
        },
      });
      return;
    }
    setSaving(form);
    // An ordinary navigation should not present an unsaved-changes warning for
    // the very form the user just chose to save. HTMX sets this on HX-Redirect.
    if (!window.htmx || !form.hasAttribute("hx-post")) allowLeave = true;
  }, true);

  document.addEventListener("click", (event) => {
    const moveTrigger = event.target.closest?.("[data-move-observation-trigger]");
    if (moveTrigger) {
      const dialog = document.getElementById("move-observation-dialog");
      const form = dialog?.querySelector("form");
      const observationId = moveTrigger.dataset.observationId;
      if (!dialog || !form || !observationId) return;
      form.elements.observation_id.value = observationId;
      form.elements.transaction_id.value = "";
      form.elements.allow_date_mismatch.checked = false;
      const title = dialog.querySelector("#move-observation-title");
      if (title) title.textContent = `Move observation #${observationId}`;
      dialog.showModal();
      form.elements.transaction_id.focus();
      return;
    }
    const link = event.target.closest?.("a[href]");
    if (!link || !isDirty() || event.defaultPrevented || event.button !== 0 ||
        event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ||
        link.hasAttribute("download") || link.target === "_blank") return;
    const destination = new URL(link.href, window.location.href);
    if (destination.pathname === location.pathname && destination.search === location.search && destination.hash) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    askConfirmation({title: "Discard unsaved changes?", message: "Your changes will not be saved.",
      label: "Discard changes", trigger: link, action: () => {
        allowLeave = true;
        window.location.assign(destination.href);
      }});
  }, true);

  window.addEventListener("beforeunload", (event) => {
    if (isDirty()) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  window.addEventListener("popstate", () => { window.location.reload(); });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });

  document.addEventListener("htmx:beforeRequest", (event) => {
    const element = event.detail.elt;
    const form = mutationForm(element);
    if (form?.dataset.mutationState === "blocked") {
      event.preventDefault();
      return;
    }
    const banner = document.getElementById("transaction-request-error");
    if (banner) banner.hidden = true;
    const active = document.activeElement;
    pendingRequests.set(event.detail.xhr, {form, element, focusId: active?.id,
      sourcePage: !!element.closest("[data-source-page]"),
      resultPage: !!element.closest("[data-result-page]")});
    if (form && !form.dataset.mutationState) setSaving(form);
  });

  document.addEventListener("htmx:beforeSwap", (event) => {
    const status = event.detail.xhr.status;
    const target = document.getElementById(event.detail.target.id) || event.detail.target;
    if (status === 422 || (target.id === "transaction-form" && [403, 503].includes(status))) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
    if (event.detail.xhr.getResponseHeader("HX-Redirect")) allowLeave = true;
  });

  // HX-Redirect is handled before beforeSwap by HTMX 1.9.
  document.addEventListener("htmx:beforeOnLoad", (event) => {
    if (event.detail.xhr.getResponseHeader("HX-Redirect")) allowLeave = true;
  });

  document.addEventListener("htmx:afterSwap", (event) => {
    initialize();
    const request = pendingRequests.get(event.detail.xhr);
    const target = document.getElementById(event.detail.target.id) || event.detail.target;
    const status = event.detail.xhr.status;
    if (status === 200 && target.id === "transaction-browser") {
      // HTMX's historyEnabled flag also disables pushState. Keep only a URL in
      // native session history; never retain a snapshot of the rendered data.
      const canonical = event.detail.xhr.getResponseHeader("HX-Push-Url");
      if (canonical) {
        const url = new URL(canonical, window.location.origin);
        const allowed = new Set(["q", "period", "date_from", "date_to", "account_id", "card_id",
          "kind", "direction", "currency", "min_abs_amount", "max_abs_amount", "page"]);
        if (url.origin === location.origin && url.pathname === "/transactions" &&
            Array.from(url.searchParams.keys()).every((key) => allowed.has(key)) &&
            url.pathname + url.search !== location.pathname + location.search) {
          window.history.pushState({spendyTransactions: true}, "", url.pathname + url.search);
        }
      }
    }
    if (status === 422) {
      focusInvalid(target);
      return;
    }
    if ([403, 503].includes(status) && target.id === "transaction-form") {
      blockMutation(editor(), status === 403 ? "Refresh this page before saving again." :
        "The save could not be confirmed. Refresh and check the transaction before trying again.");
      return;
    }
    if (request?.sourcePage || (request?.form && ["sources", "transaction-detail"].includes(target.id))) {
      document.getElementById("sources-heading")?.focus();
    } else if (request?.resultPage) {
      document.getElementById("transaction-results")?.scrollIntoView({block: "start"});
      document.getElementById("transaction-result-count")?.focus({preventScroll: true});
    } else if (request?.focusId) {
      document.getElementById(request.focusId)?.focus({preventScroll: true});
    }
  });

  function requestFailure(event) {
    const request = pendingRequests.get(event.detail.xhr);
    const form = request?.form || mutationForm(event.detail.elt);
    if (event.type === "htmx:sendAbort" && !form) return;
    const status = event.detail.xhr?.status || 0;
    const backUrl = document.querySelector("[data-transactions-ui]")?.dataset.returnUrl || "/transactions";
    if (form) {
      if (status === 422) return;
      const current = form.matches("[data-transaction-editor]") ? editor() : form;
      const message = status === 403 ? "Your request was rejected. Refresh this page before trying again." :
        status === 404 ? "This transaction is no longer available. Refresh this page before continuing." :
        "The change could not be confirmed. Refresh this page and check the result before trying again.";
      blockMutation(current, message);
      if (status === 404) showRequestError(message, null, backUrl);
      return;
    }
    if (status === 404) {
      showRequestError("This transaction is no longer available.", null, backUrl);
      return;
    }
    const element = request?.element || event.detail.elt;
    const retry = () => {
      if (element instanceof HTMLFormElement && element.isConnected) element.requestSubmit();
      else if (element?.isConnected && element.click) element.click();
      else window.location.reload();
    };
    showRequestError("The page could not be loaded. Your current results are still shown.", retry);
  }

  ["htmx:sendError", "htmx:timeout", "htmx:sendAbort", "htmx:responseError"].forEach((name) => {
    document.addEventListener(name, requestFailure);
  });

  document.addEventListener("htmx:afterRequest", (event) => {
    const request = pendingRequests.get(event.detail.xhr);
    if (event.detail.successful) clearSaving(request?.form);
  });

  initialize();
  focusInvalid(document);
  const dialog = document.getElementById("transaction-confirmation");
  if (dialog) {
    dialog.querySelector("[data-dialog-cancel]").addEventListener("click", () => dialog.close("cancel"));
    dialog.querySelector("[data-dialog-confirm]").addEventListener("click", () => {
      const action = dialogAction;
      dialog.close("confirm");
      dialogAction = null;
      action?.();
    });
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close("cancel"); });
    dialog.addEventListener("close", () => {
      dialogAction = null;
      if (dialogTrigger?.isConnected) dialogTrigger.focus();
      dialogTrigger = null;
    });
  }
})();
