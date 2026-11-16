// The in-page order template editor (plan 2026-11-13-order-template-editor, task 7). A classic browser script:
// window.OrderTemplateEditor = { mount, toEditorJson, fromEditorJson }. The editor is Tiptap, loaded from the vendored
// bundle app/static/vendor/tiptap-editor.js (window.TiptapEditor, licence in app/static/vendor/TIPTAP-NOTICE.txt).
// toEditorJson / fromEditorJson convert between the EditorDoc of app/employees/services/order_template_editor.py
// ({"paragraphs": [{"align", "bold", "italic", "size", "show_if", "numbered", "parts": [{"text"} | {"field"}]}]}) and ProseMirror JSON.
// Under node (typeof module !== "undefined") only the two converters are exported; the Tiptap part never runs there.
(function () {
  "use strict";

  var ALIGNS = ["left", "center", "right", "justify"];
  var ALIGN_LABELS = { left: "Зүүн", center: "Төвд", right: "Баруун", justify: "Тэгшлэх" };
  var SIZES = [10, 11, 12, 13, 14, 15, 16, 17, 18];
  var WARN_TITLE = "Энэ төрөлд хоосон гарна";

  // EditorDoc -> ProseMirror JSON. A null size writes no size attribute; an empty paragraph has no content.
  function toEditorJson(doc) {
    var paragraphs = (doc && doc.paragraphs) || [];
    return {
      type: "doc",
      content: paragraphs.map(function (p) {
        var attrs = {
          align: ALIGNS.indexOf(p.align) >= 0 ? p.align : "left",
          bold: !!p.bold,
          italic: !!p.italic,
          numbered: !!p.numbered,
          showIf: typeof p.show_if === "string" && p.show_if ? p.show_if : null,
        };
        if (p.size !== null && p.size !== undefined) attrs.size = p.size;
        var node = { type: "paragraph", attrs: attrs };
        var content = (p.parts || []).map(partToNode).filter(Boolean);
        if (content.length) node.content = content;
        return node;
      }),
    };
  }

  // ProseMirror JSON -> EditorDoc. An unknown align becomes "left"; a missing size becomes null.
  function fromEditorJson(json) {
    var content = json && Array.isArray(json.content) ? json.content : [];
    var paragraphs = [];
    content.forEach(function (node) {
      if (!node || node.type !== "paragraph") return;
      var a = node.attrs || {};
      paragraphs.push({
        align: ALIGNS.indexOf(a.align) >= 0 ? a.align : "left",
        bold: a.bold === true,
        italic: a.italic === true,
        size: typeof a.size === "number" ? a.size : null,
        show_if: typeof a.showIf === "string" && a.showIf ? a.showIf : null,
        numbered: a.numbered === true,
        parts: (node.content || []).map(nodeToPart).filter(Boolean),
      });
    });
    return { paragraphs: paragraphs };
  }

  function partToNode(part) {
    if (part && "field" in part) return { type: "field", attrs: { name: part.field } };
    if (part && "text" in part && part.text !== "") return { type: "text", text: part.text };
    return null;
  }

  function nodeToPart(node) {
    if (node && node.type === "text") return { text: node.text };
    if (node && node.type === "field" && node.attrs && typeof node.attrs.name === "string") {
      return { field: node.attrs.name };
    }
    return null;
  }

  // Field list -> lookup by name. A null-prototype object, so a name such as "constructor" finds nothing unless the
  // list holds it.
  function fieldIndex(list) {
    var map = Object.create(null);
    (list || []).forEach(function (f) {
      if (f && f.name) map[f.name] = f;
    });
    return map;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { toEditorJson: toEditorJson, fromEditorJson: fromEditorJson, fieldIndex: fieldIndex };
    return;
  }
  if (typeof window === "undefined" || typeof document === "undefined") return;

  // ---- browser part: Tiptap ----

  function el(tag, className) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    return node;
  }

  // The CSS a paragraph needs to look like the PDF: one alignment, bold, italic, size in pt.
  function paragraphStyle(a) {
    var style = "text-align:" + (ALIGNS.indexOf(a.align) >= 0 ? a.align : "left") + ";";
    if (a.bold) style += "font-weight:700;";
    if (a.italic) style += "font-style:italic;";
    if (a.size) style += "font-size:" + a.size + "pt;";
    return style;
  }

  // The paragraph and chip nodes. Built per mount, because a chip's label and warning depend on the field list.
  function buildExtensions(TE, fieldMap) {
    var Paragraph = TE.Paragraph.extend({
      addAttributes: function () {
        return {
          align: { default: "left", rendered: false },
          bold: { default: false, rendered: false },
          italic: { default: false, rendered: false },
          size: { default: null, rendered: false },
          numbered: { default: false, rendered: false },
          showIf: { default: null, rendered: false },
        };
      },
      renderHTML: function (args) {
        var node = args.node.attrs;
        var shown = {
          "data-align": node.align,
          style: paragraphStyle(node),
        };
        if (node.numbered) shown["data-numbered"] = "true";
        if (node.showIf) {
          var info = fieldMap[node.showIf];
          shown["data-show-if"] = node.showIf;
          shown["data-show-if-label"] = info && info.label ? info.label : node.showIf;
        }
        return ["p", TE.mergeAttributes(args.HTMLAttributes || {}, shown), 0];
      },
    });

    var Field = TE.Node.create({
      name: "field",
      group: "inline",
      inline: true,
      atom: true,
      selectable: true,
      addAttributes: function () {
        return { name: { default: null } };
      },
      parseHTML: function () {
        return [
          {
            tag: "span[data-field]",
            getAttrs: function (node) {
              return { name: node.getAttribute("data-field") };
            },
          },
        ];
      },
      renderHTML: function (args) {
        var name = args.node.attrs.name || "";
        var info = fieldMap[name];
        var warn = !info || !info.for_this_type;
        var attrs = { "data-field": name, class: warn ? "ote-chip ote-chip--warn" : "ote-chip" };
        // The chip shows its short label; the long meaning and the warning go in the tooltip.
        var hint = [warn ? WARN_TITLE : "", info && info.meaning ? info.meaning : ""].filter(Boolean).join(". ");
        if (hint) attrs.title = hint;
        return ["span", attrs, info && info.label ? info.label : name];
      },
    });

    return [TE.Document, Paragraph, TE.Text, Field, TE.History];
  }

  // The attributes of the paragraph the cursor is in (the defaults when there is none).
  function currentParagraphAttrs(editor) {
    var parent = editor.state.selection.$from.parent;
    if (parent && parent.type.name === "paragraph") return parent.attrs;
    return { align: "left", bold: false, italic: false, size: null, numbered: false, showIf: null };
  }

  // Sets attributes on every paragraph that the selection touches, in one transaction.
  function setParagraphAttrs(editor, attrs) {
    var state = editor.state;
    var tr = state.tr;
    var sel = state.selection;
    state.doc.nodesBetween(sel.from, sel.to, function (node, pos) {
      if (node.type.name === "paragraph") {
        tr.setNodeMarkup(pos, undefined, Object.assign({}, node.attrs, attrs));
      }
    });
    editor.view.dispatch(tr);
  }

  function setPressed(button, on) {
    button.setAttribute("aria-pressed", on ? "true" : "false");
    button.classList.toggle("ote-btn--on", !!on);
  }

  // mount(root, options) -> { getDoc(), insertField(name) }. options: {doc, fields, canChange}. Without doc, or with
  // canChange false, the page is shown read-only and the toolbar is hidden.
  function mount(root, options) {
    options = options || {};
    var TE = window.TiptapEditor;
    if (!TE) throw new Error("Редактор (tiptap-editor.js) ачаалагдаагүй байна.");

    var readOnly = options.canChange === false || !options.doc;
    var fieldMap = fieldIndex(options.fields);
    var json = options.doc ? toEditorJson(options.doc) : { type: "doc", content: [] };
    if (!json.content.length) json.content = [{ type: "paragraph", attrs: { align: "left", bold: false, italic: false, numbered: false, showIf: null } }];

    var toolbar = el("div", "ote-toolbar");
    toolbar.setAttribute("role", "toolbar");
    toolbar.setAttribute("aria-label", "Формат");
    toolbar.hidden = readOnly;
    var page = el("div", "ote-page");
    root.appendChild(toolbar);
    root.appendChild(page);

    var editor = new TE.Editor({
      element: page,
      extensions: buildExtensions(TE, fieldMap),
      content: json,
      editable: !readOnly,
    });

    var buttons = {};
    // mousedown is cancelled so a click on the toolbar keeps the text selection in the page.
    function button(key, text, title, onClick) {
      var b = el("button", "ote-btn");
      b.type = "button";
      b.textContent = text;
      b.title = title;
      b.setAttribute("aria-label", title);
      b.addEventListener("mousedown", function (e) { e.preventDefault(); });
      b.addEventListener("click", onClick);
      b.disabled = readOnly;  // a read-only page: the buttons are not interactive (the toolbar is hidden too)
      toolbar.appendChild(b);
      buttons[key] = b;
      return b;
    }

    button("bold", "B", "Тод", function () {
      setParagraphAttrs(editor, { bold: !currentParagraphAttrs(editor).bold });
    });
    button("italic", "I", "Налуу", function () {
      setParagraphAttrs(editor, { italic: !currentParagraphAttrs(editor).italic });
    });

    var sizeSelect = el("select", "ote-size");
    sizeSelect.setAttribute("aria-label", "Фонтын хэмжээ");
    sizeSelect.title = "Фонтын хэмжээ";
    sizeSelect.disabled = readOnly;
    var defaultOption = el("option");
    defaultOption.value = "";
    defaultOption.textContent = "Үндсэн";
    sizeSelect.appendChild(defaultOption);
    SIZES.forEach(function (size) {
      var option = el("option");
      option.value = String(size);
      option.textContent = String(size);
      sizeSelect.appendChild(option);
    });
    sizeSelect.addEventListener("change", function () {
      setParagraphAttrs(editor, { size: sizeSelect.value === "" ? null : Number(sizeSelect.value) });
    });
    toolbar.appendChild(sizeSelect);

    ALIGNS.forEach(function (align) {
      button("align-" + align, ALIGN_LABELS[align], ALIGN_LABELS[align], function () {
        setParagraphAttrs(editor, { align: align });
      });
    });

    button("numbered", "1.", "Дугаарласан зүйл (өмнөх зүйлсээс үргэлжилнэ)", function () {
      setParagraphAttrs(editor, { numbered: !currentParagraphAttrs(editor).numbered });
    });

    var showIfSelect = el("select", "ote-showif");
    showIfSelect.setAttribute("aria-label", "Харуулах нөхцөл");
    showIfSelect.title = "Энэ мөрийг хэзээ харуулах";
    showIfSelect.disabled = readOnly;
    var alwaysOption = el("option");
    alwaysOption.value = "";
    alwaysOption.textContent = "Үргэлж харуулах";
    showIfSelect.appendChild(alwaysOption);
    (options.fields || []).forEach(function (f) {
      var option = el("option");
      option.value = f.name;
      option.textContent = "Зөвхөн «" + (f.label || f.name) + "» утгатай үед";
      showIfSelect.appendChild(option);
    });
    showIfSelect.addEventListener("change", function () {
      setParagraphAttrs(editor, { showIf: showIfSelect.value === "" ? null : showIfSelect.value });
    });
    toolbar.appendChild(showIfSelect);

    button("undo", "↶", "Буцаах", function () { editor.commands.undo(); });
    button("redo", "↷", "Сэргээх", function () { editor.commands.redo(); });

    // Keeps the toolbar in step with the paragraph under the cursor.
    // A size outside the 10-18 list (set in the stored file) is added as an extra option, in numeric order, so the
    // select shows the real size instead of silently falling back to «Үндсэн».
    function ensureSizeOption(size) {
      var value = String(size);
      var options = sizeSelect.options;
      for (var i = 0; i < options.length; i++) {
        if (options[i].value === value) return;
      }
      var option = el("option");
      option.value = value;
      option.textContent = value;
      for (var j = 0; j < options.length; j++) {
        if (options[j].value !== "" && Number(options[j].value) > size) {
          sizeSelect.insertBefore(option, options[j]);
          return;
        }
      }
      sizeSelect.appendChild(option);
    }

    function refresh() {
      var a = currentParagraphAttrs(editor);
      setPressed(buttons.bold, a.bold);
      setPressed(buttons.italic, a.italic);
      setPressed(buttons.numbered, a.numbered);
      showIfSelect.value = a.showIf && fieldMap[a.showIf] ? a.showIf : "";
      ALIGNS.forEach(function (align) { setPressed(buttons["align-" + align], a.align === align); });
      if (a.size) ensureSizeOption(a.size);
      sizeSelect.value = a.size ? String(a.size) : "";
    }
    editor.on("transaction", refresh);
    refresh();

    var destroyed = false;
    return {
      getDoc: function () {
        return fromEditorJson(editor.getJSON());
      },
      insertField: function (name) {
        if (readOnly) return;
        editor.chain().focus().insertContent({ type: "field", attrs: { name: name } }).run();
      },
      // Destroys the Tiptap editor and removes the toolbar and page this mount added to root. Safe to call twice.
      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        editor.destroy();
        toolbar.remove();
        page.remove();
      },
    };
  }

  window.OrderTemplateEditor = {
    mount: mount,
    toEditorJson: toEditorJson,
    fromEditorJson: fromEditorJson,
  };
})();
