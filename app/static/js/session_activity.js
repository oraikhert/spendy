(() => {
  "use strict";

  const minimumRefreshIntervalMs = 60_000;
  let activityPending = false;
  let refreshInProgress = false;
  let refreshTimer = null;
  let lastRefreshAt = Date.now();

  function scheduleRefresh() {
    if (document.visibilityState === "hidden") return;
    activityPending = true;
    if (refreshTimer !== null || refreshInProgress) return;

    const elapsed = Date.now() - lastRefreshAt;
    refreshTimer = window.setTimeout(refreshSession, Math.max(0, minimumRefreshIntervalMs - elapsed));
  }

  async function refreshSession() {
    refreshTimer = null;
    if (!activityPending || document.visibilityState === "hidden" || refreshInProgress) return;

    activityPending = false;
    refreshInProgress = true;
    try {
      const response = await fetch("/auth/session/refresh", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "HX-Request": "true",
          "X-Spendy-Session-Activity": "true",
        },
      });
      if (response.status === 401) {
        window.location.assign(response.headers.get("HX-Redirect") || "/auth/login");
        return;
      }
      if (!response.ok) throw new Error(`Session refresh failed with ${response.status}`);
      lastRefreshAt = Date.now();
    } catch (_error) {
      // A failed request is not activity. A later user event will try again.
    } finally {
      refreshInProgress = false;
      if (activityPending) scheduleRefresh();
    }
  }

  for (const eventName of ["pointerdown", "pointermove", "keydown", "touchstart", "scroll"]) {
    window.addEventListener(eventName, scheduleRefresh, { passive: true });
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") scheduleRefresh();
  });
})();
