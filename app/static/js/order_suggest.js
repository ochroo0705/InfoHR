// «Санал болгох» beside an order number: asks the server for the next number of the year and fills the number
// box. The date box is filled with today only when it is empty (the form needs both together); a typed date
// is never changed, and its year decides which year's numbers are counted. Both stay editable.
(function () {
  "use strict";
  function field(form, suffix) {
    return form.querySelector('input[name="' + suffix + '"], input[name$="-' + suffix + '"]');
  }
  function set(input, value) {
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }
  document.addEventListener("click", function (e) {
    var button = e.target.closest("[data-order-suggest]");
    if (!button) return;
    var form = button.closest("form");
    var number = field(form, "number"), day = field(form, "date");
    var note = button.parentNode.parentNode.querySelector("[data-order-suggest-note]");
    var url = button.getAttribute("data-order-suggest") + (day && day.value ? "?date=" + encodeURIComponent(day.value) : "");
    button.disabled = true;
    fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (data) {
        if (note) note.classList.toggle("hidden", !!data.number);
        if (!data.number) return;
        set(number, data.number);
        if (day && !day.value) set(day, data.date);
      })
      .catch(function () { if (note) note.classList.remove("hidden"); })
      .then(function () { button.disabled = false; });
  });
})();
