import { useEffect, useRef, type RefObject } from "react";

// Port of app/static/js/validation_mn.js (docs/UI_RULES.md §2). When a form field is invalid the browser shows its own
// English bubble; this replaces it with a Mongolian text by setting a custom validity message. The texts and the order
// of the checks are the same as in the JS.

type Field = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

const MARK = "data-mn-validity"; // set only on fields this module gave a message, so other custom messages stay
const DATE_TYPES: Record<string, true> = { date: true, "datetime-local": true, month: true, time: true, week: true };

function isCombo(el: Field): boolean {
  return el.tagName === "SELECT" || el.getAttribute("role") === "combobox";
}

// The Mongolian text for the first failing ValidityState flag, or "" when nothing fails.
export function messageFor(el: Field): string {
  const v = el.validity;
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

function unmark(el: Field): void {
  if (!el.hasAttribute(MARK)) return;
  el.setCustomValidity("");
  el.removeAttribute(MARK);
}

// Drops every message this module gave to a field of the form. form.elements also lists controls that belong to the
// form through a form="..." attribute, the same fields the JS reaches through each field's .form.
function clearForm(form: HTMLFormElement): void {
  for (const el of Array.from(form.elements)) {
    if (el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement) {
      unmark(el);
    }
  }
}

// Attaches the listeners to one form and returns the function that removes them. They sit on the document, not on the
// form, because a control that belongs to the form through form="..." can be outside the form's DOM subtree (the JS
// listens on the document too). Each event is kept only when its field, or its button, belongs to this form.
function attach(form: HTMLFormElement): () => void {
  const ownedBy = (el: unknown): boolean => (el as Field | null)?.form === form;

  const onInvalid = (e: Event) => {
    const el = e.target as Field | null;
    if (!el || !ownedBy(el) || typeof el.setCustomValidity !== "function" || !el.validity) return;
    // Our own old message: drop it and judge the field as it is now, so a field that became valid is not refused.
    unmark(el);
    if (el.validity.customError) return;
    const text = messageFor(el);
    if (!text) return;
    el.setCustomValidity(text);
    el.setAttribute(MARK, "1");
  };

  const onClear = (e: Event) => {
    const el = e.target as Field | null;
    if (el && ownedBy(el)) unmark(el);
    // Not ported: the JS's `_selCombo` clearing (select.js hides a required <select> behind a typing box and puts the
    // text on the box). The React Select does not do that. Its visible typing box is the one with `required`, so the
    // invalid event and this clear both land on that box; its hidden value field is type="hidden" and never required.
    // In the list mode the real <select> is visible and carries `required` itself, so the path above covers it too.
  };

  const onClick = (e: Event) => {
    const target = e.target as Element | null;
    const btn = target?.closest("button, input[type=submit], input[type=image]") as HTMLButtonElement | null;
    if (!btn || btn.form !== form || btn.type !== "submit" || btn.formNoValidate) return;
    clearForm(form);
  };

  const onKeyDown = (e: Event) => {
    const target = e.target as HTMLElement | null;
    if ((e as KeyboardEvent).key !== "Enter" || !target || target.tagName !== "INPUT") return;
    if (!ownedBy(target)) return;
    clearForm(form);
  };

  const onSubmit = (e: Event) => {
    if (e.target === form) clearForm(form);
  };

  const listeners: Array<[string, EventListener]> = [
    ["invalid", onInvalid],
    ["input", onClear],
    ["change", onClear],
    ["click", onClick],
    ["keydown", onKeyDown],
    ["submit", onSubmit],
  ];
  for (const [type, fn] of listeners) document.addEventListener(type, fn, true);
  return () => {
    for (const [type, fn] of listeners) document.removeEventListener(type, fn, true);
  };
}

// Sets the Mongolian messages on one form (the JS does it document-wide; a React form passes its own ref). Invalid sets
// the text, typing or picking again clears it, and a new submit attempt starts from scratch.
// The form element is read again after every render, so a form that mounts later or is replaced is attached to.
export function useMnValidation(formRef: RefObject<HTMLFormElement | null>): void {
  const attached = useRef<HTMLFormElement | null>(null);
  const detach = useRef<(() => void) | null>(null);

  useEffect(() => {
    const form = formRef.current;
    if (form === attached.current) return;
    detach.current?.();
    detach.current = form ? attach(form) : null;
    attached.current = form;
  });

  useEffect(
    () => () => {
      detach.current?.();
      detach.current = null;
      attached.current = null;
    },
    [],
  );
}
