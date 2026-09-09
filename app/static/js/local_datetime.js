(() => {
  "use strict";

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

  window.Spendy = window.Spendy || {};
  window.Spendy.localizeDateTimes = localizeDateTimes;
})();
