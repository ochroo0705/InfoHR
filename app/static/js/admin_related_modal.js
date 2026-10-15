/* Admin "+" (add related object) opens in a modal instead of a new browser window.
   The add form loads in an iframe; when Django answers with its popup-response page,
   the new object is added (and selected) in the field that opened it, and the modal closes. */
(function () {
  "use strict";

  var dialog, frame, title, current;

  function build() {
    dialog = document.createElement("dialog");
    dialog.style.cssText =
      "position:fixed;inset:0;margin:auto;" +  // the admin's CSS reset removes the default centering
      "width:min(760px,94vw);height:min(640px,88vh);padding:0;border:0;border-radius:8px;" +
      "box-shadow:0 20px 50px rgba(0,0,0,.35);overflow:hidden;background:#fff";
    var bar = document.createElement("div");
    bar.style.cssText =
      "display:flex;align-items:center;justify-content:space-between;padding:8px 12px;" +
      "border-bottom:1px solid #e5e7eb;font:500 14px system-ui,sans-serif;color:#111827";
    title = document.createElement("span");
    var close = document.createElement("button");
    close.type = "button";
    close.textContent = "✕";
    close.setAttribute("aria-label", "Хаах");
    close.style.cssText = "border:0;background:none;font-size:18px;cursor:pointer;color:#6b7280";
    close.addEventListener("click", function () { dialog.close(); });
    bar.append(title, close);
    frame = document.createElement("iframe");
    frame.style.cssText = "width:100%;height:calc(100% - 41px);border:0";
    frame.addEventListener("load", onLoad);
    dialog.append(bar, frame);
    dialog.addEventListener("close", function () { frame.src = "about:blank"; current = null; });
    document.body.appendChild(dialog);
  }

  function onLoad() {
    var doc;
    try { doc = frame.contentDocument; } catch (e) { return; }
    var answer = doc && doc.getElementById("django-admin-popup-response-constants");
    if (!answer || !current) return;
    var data = JSON.parse(answer.dataset.popupResponse);
    if (data.value !== undefined && (!data.action || data.action === "add")) addChoice(current, String(data.value), data.obj);
    dialog.close();
  }

  function addChoice(fieldName, value, label) {
    var select = document.getElementById("id_" + fieldName);
    if (select && select.tagName === "SELECT") {
      var option = new Option(label, value, true, true);
      select.appendChild(option);
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }
    var boxes = document.querySelectorAll('input[type="checkbox"][name="' + fieldName + '"]');
    if (!boxes.length) return;
    var last = boxes[boxes.length - 1];
    var row = last;  // climb to the element that holds one checkbox with its label
    while (row.parentElement && row.parentElement.querySelectorAll('input[name="' + fieldName + '"]').length === 1) {
      row = row.parentElement;
    }
    var copy = row.cloneNode(true);
    var box = copy.querySelector('input[type="checkbox"]');
    var id = "id_" + fieldName + "_new_" + value;
    box.value = value;
    box.checked = true;
    box.id = id;
    var text = copy.querySelector("label") || copy;
    if (text.htmlFor !== undefined) text.htmlFor = id;
    var walker = document.createTreeWalker(text, NodeFilter.SHOW_TEXT), node, lastText = null;
    while ((node = walker.nextNode())) if (node.textContent.trim()) lastText = node;  // the label may sit in a <span>
    if (lastText) lastText.textContent = label;
    else text.appendChild(document.createTextNode(" " + label));
    row.after(copy);
  }

  document.addEventListener(
    "click",
    function (event) {
      var link = event.target.closest && event.target.closest("a.add-related[data-popup]");
      if (!link || !window.HTMLDialogElement) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!dialog) build();
      current = link.id.replace(/^add_id_/, "");
      var url = new URL(link.href, location.href);
      url.searchParams.set("_popup", "1");
      title.textContent = link.title || "";
      frame.src = url.toString();
      dialog.showModal();
    },
    true
  );
})();
