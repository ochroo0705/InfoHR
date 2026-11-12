// Public employee form (/apply/<token>/): steps, repeating rows, the send tick, the typed-values summary and draft
// autosave. Progressive enhancement: without JavaScript the page is one long form and the server checks everything.
// Plain browser script, no framework, no build step. Under Node (the test file) it exports the pure helpers only.
(function () {
  "use strict";

  var PLACEHOLDER = "__i__";            // index placeholder inside <template data-row-template>
  var AUTOSAVE_DELAY = 1500;            // ms after the last input before a draft is sent
  var LEFT_OUT_OF_DRAFT = ["photo", "agreed_correct", "consent"];
  var MSG_SAVING = "Хадгалж байна…";
  var MSG_SAVED = "Хадгалсан";
  var MSG_FAILED = "Хадгалагдсангүй, дахин оролдоно";
  var MSG_CLOSED = "Энэ холбоос хаагдсан байна. Сүүлийн өөрчлөлт хадгалагдаагүй.";
  var MSG_EMPTY = "Мэдээлэл бөглөөгүй байна.";
  var MSG_NO_FILE = "Файл сонгоогүй";

  // Pure helpers (tested in selfform_apply.test.mjs).
  function nextRowIndex(indices) {
    var max = -1;
    for (var i = 0; i < indices.length; i++) {
      if (indices[i] > max) max = indices[i];
    }
    return max + 1;
  }

  function canAddRow(count, max) {
    return count < max;
  }

  function sendEnabled(agreed, consent) {
    return Boolean(agreed && consent);
  }

  function replacePlaceholder(text, index) {
    return String(text).split(PLACEHOLDER).join(String(index));
  }

  // The draft is the form's text fields: the photo file and the two ticks are never sent with it.
  function draftFields(formData) {
    LEFT_OUT_OF_DRAFT.forEach(function (name) { formData.delete(name); });
    return formData;
  }

  // What Enter does in the form. Enter in a text box or a select must not submit the form early (Send is the only
  // submit button, so implicit submission would skip the summary): on a step before the last it moves to the next
  // step; on the last step, and for any other element (textarea, buttons, links), the browser does its own thing.
  function enterAction(stepIndex, lastIndex, tagName) {
    if (tagName !== "INPUT" && tagName !== "SELECT") return "allow";
    if (stepIndex < 0 || stepIndex >= lastIndex) return "allow";
    return "next";
  }

  var helpers = {
    nextRowIndex: nextRowIndex,
    canAddRow: canAddRow,
    sendEnabled: sendEnabled,
    replacePlaceholder: replacePlaceholder,
    draftFields: draftFields,
    enterAction: enterAction,
    PLACEHOLDER: PLACEHOLDER
  };
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  if (typeof document === "undefined") return;

  function toArray(list) {
    return Array.prototype.slice.call(list);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function fieldValue(field) {
    var type = field.type;
    if (type === "checkbox" || type === "hidden" || type === "button" || type === "submit") return "";
    if (type === "file") return field.files && field.files.length ? field.files[0].name : "";
    if (field.tagName === "SELECT") {
      var option = field.options[field.selectedIndex];
      return option && option.value ? option.text.trim() : "";
    }
    return String(field.value || "").trim();
  }

  function labelOf(field) {
    if (field.name === "photo") return "Зураг";
    var labels = field.labels;
    var text = labels && labels.length ? labels[0].textContent : field.name;
    return text.replace(/\s*\*\s*$/, "").trim();
  }

  // A row or a summary group (the emergency contact) is its own block; other fields belong to their step's title.
  function titleOf(holder, section) {
    if (holder.hasAttribute("data-row")) {
      var rowTitle = holder.querySelector("[data-row-title]");
      return rowTitle ? rowTitle.textContent.trim() : "";
    }
    if (holder.hasAttribute("data-summary-group")) return holder.getAttribute("data-summary-group");
    var heading = section.querySelector("h2");
    return heading ? heading.textContent.trim() : "";
  }

  function attach(form) {
    var steps = toArray(form.querySelectorAll("[data-step]"));
    var nav = form.querySelector("[data-stepper]");
    if (!steps.length || !nav) return;

    var draftUrl = form.getAttribute("data-draft-url") || "";
    var indicator = form.querySelector("[data-step-indicator]");
    var status = form.querySelector("[data-save-status]");
    var backButton = form.querySelector("[data-back]");
    var nextButton = form.querySelector("[data-next]");
    var sendButton = form.querySelector("[data-send]");
    var summaryBox = form.querySelector("[data-summary-box]");
    var summary = form.querySelector("[data-summary]");
    var photo = form.querySelector('input[name="photo"]');
    var fileName = form.querySelector("[data-file-name]");
    var ticks = [form.querySelector('input[name="agreed_correct"]'), form.querySelector('input[name="consent"]')];

    var current = 0;
    var timer = null;
    var inFlight = false;
    var queued = false;
    var closed = false;

    function isSendStep(index) {
      return steps[index].getAttribute("data-step") === "check-send";
    }

    function setStatus(text) {
      if (status) status.textContent = text;
    }

    // Autosave (draft) ----------------------------------------------------------------------------------------------

    function scheduleSave() {
      if (closed || !draftUrl) return;
      clearTimeout(timer);
      timer = setTimeout(saveDraft, AUTOSAVE_DELAY);
    }

    function saveDraft() {
      clearTimeout(timer);
      timer = null;
      if (closed || !draftUrl) return;
      if (inFlight) {
        queued = true;
        return;
      }
      inFlight = true;
      queued = false;
      setStatus(MSG_SAVING);
      // The CSRF token is a hidden input inside the form, so it travels in the FormData.
      fetch(draftUrl, {
        method: "POST",
        body: draftFields(new FormData(form)),
        credentials: "same-origin",
        cache: "no-store"
      })
        .then(function (response) {
          if (response.status === 409) {
            closed = true;
            setStatus(MSG_CLOSED);
            return;
          }
          setStatus(response.ok ? MSG_SAVED : MSG_FAILED);
        }, function () {
          setStatus(MSG_FAILED);
        })
        .then(function () {
          inFlight = false;
          if (queued) saveDraft();
        });
    }

    // Steps ---------------------------------------------------------------------------------------------------------

    function firstErrorStep() {
      for (var i = 0; i < steps.length; i++) {
        if (steps[i].querySelector("[data-has-error]")) return i;
      }
      return 0;
    }

    function fillSummary() {
      if (!summary || !summaryBox) return;
      while (summary.firstChild) summary.removeChild(summary.firstChild);
      var groups = [];
      steps.forEach(function (section, index) {
        if (isSendStep(index)) return;
        toArray(section.querySelectorAll("input, select, textarea")).forEach(function (field) {
          var value = fieldValue(field);
          if (!value) return;
          var holder = field.closest("[data-row], [data-summary-group]") || section;
          var group = null;
          for (var g = 0; g < groups.length; g++) {
            if (groups[g].holder === holder) group = groups[g];
          }
          if (!group) {
            group = { holder: holder, title: titleOf(holder, section), items: [] };
            groups.push(group);
          }
          group.items.push({ label: labelOf(field), value: value });
        });
      });
      if (!groups.length) summary.appendChild(el("p", "text-base text-slate-600", MSG_EMPTY));
      groups.forEach(function (group) {
        var card = el("div", "grid gap-2 rounded-lg border border-slate-200 bg-white p-4");
        card.appendChild(el("h4", "text-base font-semibold", group.title));
        var list = el("dl", "grid gap-2 text-base");
        group.items.forEach(function (item) {
          list.appendChild(el("dt", "text-sm text-slate-600", item.label));
          list.appendChild(el("dd", "break-words font-medium", item.value));
        });
        card.appendChild(list);
        summary.appendChild(card);
      });
      summaryBox.hidden = false;
    }

    function show(index, moved) {
      if (index < 0 || index >= steps.length) return;
      current = index;
      steps.forEach(function (section, k) { section.hidden = k !== index; });
      indicator.textContent = (index + 1) + " / " + steps.length;
      backButton.hidden = index === 0;
      nextButton.hidden = index === steps.length - 1;
      if (isSendStep(index)) fillSummary();
      if (moved) {
        var heading = steps[index].querySelector("h2");
        if (heading) {
          heading.setAttribute("tabindex", "-1");
          heading.focus();
        }
        saveDraft();
      }
    }

    // Repeating rows -----------------------------------------------------------------------------------------------

    function rowsOf(box) {
      return toArray(box.children).filter(function (node) { return node.hasAttribute("data-row"); });
    }

    function reindex(root, index) {
      var nodes = [root].concat(toArray(root.querySelectorAll("*")));
      nodes.forEach(function (node) {
        if (node.nodeType !== 1) return;
        toArray(node.attributes).forEach(function (attr) {
          if (attr.value.indexOf(PLACEHOLDER) !== -1) node.setAttribute(attr.name, replacePlaceholder(attr.value, index));
        });
      });
    }

    // Renumbers the titles, shows the remove buttons, and hides «add» at the cap.
    function updateRows(box) {
      var name = box.getAttribute("data-rows");
      var max = parseInt(box.getAttribute("data-max"), 10);
      var rows = rowsOf(box);
      rows.forEach(function (row, i) {
        var title = row.querySelector("[data-row-title]");
        if (title) title.textContent = (row.getAttribute("data-row-label") || "") + " " + (i + 1);
        var remove = row.querySelector("[data-row-remove]");
        if (remove) remove.hidden = false;
      });
      var add = form.querySelector('[data-row-add="' + name + '"]');
      if (add) add.hidden = !canAddRow(rows.length, max);
    }

    function addRow(name) {
      var box = form.querySelector('[data-rows="' + name + '"]');
      var template = form.querySelector('template[data-row-template="' + name + '"]');
      if (!box || !template) return;
      var rows = rowsOf(box);
      if (!canAddRow(rows.length, parseInt(box.getAttribute("data-max"), 10))) return;
      var index = nextRowIndex(rows.map(function (row) { return parseInt(row.getAttribute("data-index"), 10); }));
      var copy = template.content.cloneNode(true);
      reindex(copy, index);
      var row = copy.querySelector("[data-row]");
      box.appendChild(copy);
      // The date picker upgrades date boxes on this event (datepicker.js listens for htmx:load); a new row has none yet.
      if (row) document.dispatchEvent(new CustomEvent("htmx:load", { detail: { elt: row } }));
      updateRows(box);
      var first = row && row.querySelector("input, select, textarea");
      if (first) first.focus();
      scheduleSave();
    }

    function removeRow(row) {
      if (!row || !row.parentNode) return;
      var box = row.parentNode;
      box.removeChild(row);
      updateRows(box);
      scheduleSave();
    }

    // Send gating --------------------------------------------------------------------------------------------------

    function syncSend() {
      if (!sendButton) return;
      sendButton.disabled = !sendEnabled(ticks[0] && ticks[0].checked, ticks[1] && ticks[1].checked);
    }

    // Events ---------------------------------------------------------------------------------------------------------

    form.addEventListener("click", function (event) {
      var target = event.target;
      if (!(target instanceof Element)) return;
      var add = target.closest("[data-row-add]");
      if (add) {
        event.preventDefault();
        addRow(add.getAttribute("data-row-add"));
        return;
      }
      var remove = target.closest("[data-row-remove]");
      if (remove) {
        event.preventDefault();
        removeRow(remove.closest("[data-row]"));
        return;
      }
      if (target.closest("[data-back]")) {
        event.preventDefault();
        show(current - 1, true);
        return;
      }
      if (target.closest("[data-next]")) {
        event.preventDefault();
        show(current + 1, true);
      }
    });

    function onEdit(event) {
      var target = event.target;
      if (target === photo) {
        if (fileName) fileName.textContent = target.files && target.files.length ? target.files[0].name : MSG_NO_FILE;
        return;
      }
      if (target === ticks[0] || target === ticks[1]) {
        syncSend();
        return;
      }
      scheduleSave();
    }
    form.addEventListener("input", onEdit);
    form.addEventListener("change", onEdit);
    // A double tap on Send must not post twice: the button is off from the first submit until the page comes back.
    // The server answers a repeat with the done page, so a second post is harmless; this only keeps it to one.
    form.addEventListener("submit", function () {
      if (sendButton) sendButton.disabled = true;
    });
    // Coming back to this page (back button, bfcache) restores the button by the same rule as before.
    window.addEventListener("pageshow", syncSend);
    form.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" || event.isComposing || !event.target) return;
      if (enterAction(current, steps.length - 1, event.target.tagName) === "next") {
        event.preventDefault();
        show(current + 1, true);
      }
    });

    // Start ----------------------------------------------------------------------------------------------------------

    nav.hidden = false;
    toArray(form.querySelectorAll("[data-rows]")).forEach(updateRows);
    syncSend();
    show(firstErrorStep(), false);
  }

  function start() {
    toArray(document.querySelectorAll("form[data-draft-url]")).forEach(attach);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
