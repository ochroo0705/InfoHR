// Mongolian browser validation messages (docs/UI_RULES.md §2). When a form field is invalid the browser shows its own
// bubble; this script replaces its English text with a Mongolian one by setting a custom validity message. One
// document-level listener set covers every form, including pop-ups that htmx inserts later.
(function () {
  "use strict";

  var MARK = "data-mn-validity";  // set only on fields this script gave a message, so other custom messages stay
  var DATE_TYPES = { date: 1, "datetime-local": 1, month: 1, time: 1, week: 1 };

  function isCombo(el) {
    return el.tagName === "SELECT" || el.getAttribute("role") === "combobox";
  }

  function message(el) {
    var v = el.validity;
    if (v.valueMissing) {
      if (isCombo(el)) return "Жагсаалтаас сонгоно уу.";
      if (el.type === "file") return "Файл сонгоно уу.";
      return "Энэ талбарыг бөглөнө үү.";
    }
    if (el.type === "number" && (v.badInput || v.typeMismatch)) return "Тоо оруулна уу.";
    if (v.badInput) return DATE_TYPES[el.type] ? "Огноог зөв оруулна уу." : "Утгыг зөв оруулна уу.";
    if (v.stepMismatch) return "Утгыг зөв оруулна уу.";
    if (v.tooLong) return "Хэт урт байна.";
    if (v.tooShort) return "Хэт богино байна.";
    if (v.rangeUnderflow || v.rangeOverflow) return "Утга хязгаараас гадуур байна.";
    if (v.typeMismatch) return "Буруу формат байна.";
    return "";
  }

  function unmark(el) {
    if (!el || !el.hasAttribute || !el.hasAttribute(MARK)) return;
    el.setCustomValidity("");
    el.removeAttribute(MARK);
  }

  document.addEventListener(
    "invalid",
    function (e) {
      var el = e.target;
      if (!el || !el.setCustomValidity || !el.validity) return;
      // Our own old message (set when the field was last checked, then changed by script): drop it and judge the
      // field as it is now, so a field that became valid is not refused with a stale text.
      if (el.hasAttribute && el.hasAttribute(MARK)) unmark(el);
      if (el.validity.customError) return;
      var text = message(el);
      if (!text) return;
      el.setCustomValidity(text);
      el.setAttribute(MARK, "1");
    },
    true
  );

  // Typing or picking again clears our message, so the next check decides afresh. A pick in a typing box (select.js)
  // fires its events on the hidden select, so the box that shows the text is cleared too.
  function clear(e) {
    var el = e.target;
    if (!el || !el.hasAttribute) return;
    unmark(el);
    if (el.tagName === "SELECT" && el._selCombo) unmark(el._selCombo.input);
  }
  document.addEventListener("input", clear, true);
  document.addEventListener("change", clear, true);

  // A new submit attempt starts from scratch: every message of the form is dropped, and the browser's check that
  // follows sets again only the fields that are still invalid. This clears a message left on a field that is hidden
  // or no longer required (contract end date) and one left on a typing box after a pick.
  function clearForm(form) {
    var all = document.querySelectorAll("[" + MARK + "]");
    for (var i = 0; i < all.length; i++) if (all[i].form === form) unmark(all[i]);
  }

  document.addEventListener(
    "click",
    function (e) {
      var btn = e.target && e.target.closest && e.target.closest("button, input[type=submit], input[type=image]");
      if (!btn || !btn.form || btn.type !== "submit" || btn.formNoValidate) return;
      clearForm(btn.form);
    },
    true
  );

  // Enter in a field submits the form without a click on the button in some cases, so it starts the same way.
  document.addEventListener(
    "keydown",
    function (e) {
      if (e.key !== "Enter" || !e.target || e.target.tagName !== "INPUT" || !e.target.form) return;
      clearForm(e.target.form);
    },
    true
  );

  // A form that is submitted by script (requestSubmit) or by htmx does not always pass a click or Enter: these two
  // paths start it the same way. A submit event only comes when the form was valid, so no error is hidden by it.
  document.addEventListener(
    "submit",
    function (e) {
      if (e.target && e.target.tagName === "FORM") clearForm(e.target);
    },
    true
  );
  document.addEventListener("htmx:beforeRequest", function (e) {
    var el = e.detail && e.detail.elt;
    var form = el && (el.tagName === "FORM" ? el : el.form || (el.closest && el.closest("form")));
    if (form) clearForm(form);
  });
})();
