// Signature pad in the order-signing pop-up (employees/_order_sign.html). Classic browser script with event delegation
// on document: the pop-up is inserted by HTMX, so nothing is set up on page load. Strokes use Pointer Events (mouse,
// touch and pen) with pointer capture; the canvas stays transparent (the white comes from the box around it) and each
// finished stroke writes a PNG data URL into the hidden `signature` input. The sign button stays disabled until a
// stroke exists. Saved-signature / draw switching sets the hidden `mode` input (saved | drawn).
// The pure helpers and install(doc) are exported for signature_pad.test.mjs (Node); the browser calls install(document).
(function () {
  "use strict";

  var INK = "#1a3a8a";
  var LINE_WIDTH = 2.5;
  var ARIA_LABEL = "Гарын үсэг зурах талбар";
  var CANVAS = "canvas[data-signature-pad]";

  // Client (CSS pixel) point to canvas pixel. The canvas may be scaled by CSS, so the ratio of its pixel size to its
  // on-screen box is applied.
  function canvasPoint(rect, canvasSize, clientX, clientY) {
    var sx = rect.width ? canvasSize.width / rect.width : 1;
    var sy = rect.height ? canvasSize.height / rect.height : 1;
    return { x: (clientX - rect.left) * sx, y: (clientY - rect.top) * sy };
  }

  // The mode a switch button asks for: "draw" -> drawn, "saved" -> saved; anything else -> null.
  function modeFor(show) {
    if (show === "draw") return "drawn";
    if (show === "saved") return "saved";
    return null;
  }

  // The new value of the hidden mode input: the wanted mode when it is a known one, otherwise the current value.
  function nextMode(current, wanted) {
    return wanted === "saved" || wanted === "drawn" ? wanted : current;
  }

  // Stroke bookkeeping per canvas (a WeakMap, so a removed pop-up leaves nothing behind).
  function install(doc) {
    var states = new WeakMap();
    var active = null;  // the canvas whose stroke is in progress

    function stateOf(canvas) {
      var s = states.get(canvas);
      if (!s) {
        s = { strokes: 0, pointerId: null };
        states.set(canvas, s);
      }
      return s;
    }

    function styleContext(ctx) {
      ctx.strokeStyle = INK;
      ctx.fillStyle = INK;
      ctx.lineWidth = LINE_WIDTH;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      return ctx;
    }

    function pointOf(canvas, e) {
      return canvasPoint(
        canvas.getBoundingClientRect(),
        { width: canvas.width, height: canvas.height },
        e.clientX,
        e.clientY
      );
    }

    function formOf(canvas) {
      return canvas.closest("[data-signature-form]");
    }

    function submitOf(form) {
      return form ? form.querySelector("[data-signature-submit]") : null;
    }

    // Sets the hidden signature value. A real change dispatches a bubbling `input` event, so modal.js marks the pop-up
    // as holding typed input (Escape, ✕ and an outside click then ask first). No change, no event.
    function setSignature(form, value) {
      var input = form.querySelector('input[name="signature"]');
      if (!input || input.value === value) return;
      input.value = value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }

    // Writes the drawing into the hidden input and enables the sign button.
    function writeSignature(canvas) {
      var form = formOf(canvas);
      if (!form) return;
      setSignature(form, canvas.toDataURL("image/png"));
      var submit = submitOf(form);
      if (submit) submit.disabled = false;
    }

    function clearCanvas(canvas) {
      var ctx = canvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
      stateOf(canvas).strokes = 0;
      var form = formOf(canvas);
      if (!form) return;
      setSignature(form, "");
      var submit = submitOf(form);
      if (submit) submit.disabled = true;
    }

    // Accessibility and touch hooks for a canvas that was just inserted (htmx:load). Existing values are kept.
    function prepare(canvas) {
      if (!canvas.hasAttribute("role")) canvas.setAttribute("role", "img");
      if (!canvas.hasAttribute("aria-label")) canvas.setAttribute("aria-label", ARIA_LABEL);
      if (canvas.style) canvas.style.touchAction = "none";
    }

    function onPointerDown(e) {
      var canvas = e.target && e.target.closest ? e.target.closest(CANVAS) : null;
      if (!canvas || (e.button !== undefined && e.button > 0)) return;
      // A second pointer must not take over the stroke in progress. A stroke whose pad was removed mid-drag (no up
      // reaches the document) is stale: it is dropped here, so later strokes still work.
      if (active && active.isConnected !== false) return;
      active = null;
      e.preventDefault();
      var s = stateOf(canvas);
      s.pointerId = e.pointerId;
      active = canvas;
      if (canvas.setPointerCapture) {
        try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* capture refused: the stroke still works */ }
      }
      var p = pointOf(canvas, e);
      s.last = p;
      var ctx = canvas.getContext("2d");
      if (!ctx) return;
      styleContext(ctx);
      // A tap with no movement leaves a dot.
      ctx.beginPath();
      ctx.arc(p.x, p.y, LINE_WIDTH / 2, 0, Math.PI * 2);
      ctx.fill();
    }

    function onPointerMove(e) {
      if (!active) return;
      var s = stateOf(active);
      if (e.pointerId !== s.pointerId) return;
      var p = pointOf(active, e);
      var ctx = active.getContext("2d");
      if (!ctx) return;
      styleContext(ctx);
      ctx.beginPath();
      ctx.moveTo(s.last.x, s.last.y);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      s.last = p;
    }

    function onPointerEnd(e) {
      if (!active) return;
      var canvas = active;
      var s = stateOf(canvas);
      if (e.pointerId !== s.pointerId) return;
      active = null;
      s.pointerId = null;
      s.strokes += 1;
      if (canvas.releasePointerCapture) {
        try { canvas.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
      }
      writeSignature(canvas);
    }

    // Mode switch: «Өөр гарын үсэг зурах» (draw) and «Буцах» / «Болих» back to the saved one (saved). Going back clears
    // the drawing, so the sign button follows the saved signature again.
    function onShowClick(show, form) {
      var toDraw = show === "draw";
      var saved = form.querySelector('[data-sign-section="saved"]');
      var draw = form.querySelector('[data-sign-section="draw"]');
      if (saved) {
        if (toDraw) saved.setAttribute("hidden", "");
        else saved.removeAttribute("hidden");
      }
      if (draw) {
        if (toDraw) draw.removeAttribute("hidden");
        else draw.setAttribute("hidden", "");
      }
      var mode = form.querySelector('input[name="mode"]');
      if (mode) mode.value = nextMode(mode.value, modeFor(show));
      if (!toDraw) {
        var canvas = form.querySelector(CANVAS);
        if (canvas) clearCanvas(canvas);
      }
    }

    doc.addEventListener("pointerdown", onPointerDown);
    doc.addEventListener("pointermove", onPointerMove);
    doc.addEventListener("pointerup", onPointerEnd);
    doc.addEventListener("pointercancel", onPointerEnd);
    doc.addEventListener("lostpointercapture", onPointerEnd);  // capture lost without an up: the stroke ends

    doc.addEventListener("click", function (e) {
      var target = e.target;
      if (!target || !target.closest) return;
      var clear = target.closest("[data-signature-clear]");
      if (clear) {
        var form = clear.closest("[data-signature-form]");
        var canvas = form ? form.querySelector(CANVAS) : null;
        if (canvas) clearCanvas(canvas);
        return;
      }
      var show = target.closest("[data-sign-show]");
      if (show) {
        var owner = show.closest("[data-signature-form]");
        if (owner) onShowClick(show.getAttribute("data-sign-show"), owner);
      }
    });

    // Guard against Enter in the form while the drawn signature is empty (the button is disabled anyway). The
    // propagation stop keeps HTMX from sending the form.
    doc.addEventListener(
      "submit",
      function (e) {
        var form = e.target;
        if (!form || !form.hasAttribute || !form.hasAttribute("data-signature-form")) return;
        var mode = form.querySelector('input[name="mode"]');
        var sig = form.querySelector('input[name="signature"]');
        if (mode && mode.value === "drawn" && sig && sig.value === "") {
          e.preventDefault();
          e.stopPropagation();
        }
      },
      true
    );

    doc.addEventListener("htmx:load", function (e) {
      var elt = e.detail && e.detail.elt;
      if (!elt || !elt.querySelectorAll) return;
      if (elt.matches && elt.matches(CANVAS)) prepare(elt);
      elt.querySelectorAll(CANVAS).forEach(prepare);
    });
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { canvasPoint: canvasPoint, modeFor: modeFor, nextMode: nextMode, install: install };
  } else {
    install(document);
  }
})();
