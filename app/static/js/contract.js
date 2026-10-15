/* Contract end date follows the contract type (models.contract_errors):
   Хугацаагүй (open-ended) → "Гэрээ дуусах" is hidden and cleared; Хугацаатай (fixed-term) → shown and required.
   Works in any form with a <select name="…contract_type"> and an <input name="…contract_end"> (hire form,
   job-change and correction pop-ups); the server enforces the same rule. */
(function () {
  "use strict";

  function endFor(select) {
    var scope = select.form || select.closest("form") || document;
    var prefix = select.name.slice(0, -"contract_type".length);
    return scope.querySelector('input[name="' + prefix + 'contract_end"]');
  }

  function apply(select) {
    var end = endFor(select);
    if (!end) return;
    var box = end.closest("label") || end.parentElement;
    var open = select.value === "open_ended";
    box.hidden = open;
    end.required = select.value === "fixed_term";
    if (open && end.value) {
      end.value = "";
      end.dispatchEvent(new Event("input", { bubbles: true }));
    }
    var star = box.querySelector("[data-contract-star]");
    if (end.required && !star && !/\*\s*$/.test(box.firstChild ? box.firstChild.textContent : "")) {
      star = document.createElement("span");
      star.dataset.contractStar = "1";
      star.textContent = " *";
      box.insertBefore(star, box.firstChild ? box.firstChild.nextSibling : null);
    } else if (!end.required && star) {
      star.remove();
    }
  }

  function init(root) {
    (root.querySelectorAll ? root : document).querySelectorAll('select[name$="contract_type"]').forEach(apply);
  }

  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches('select[name$="contract_type"]')) apply(e.target);
  });
  document.addEventListener("DOMContentLoaded", function () { init(document); });
  document.addEventListener("htmx:load", function (e) { init(e.detail.elt); });
})();
