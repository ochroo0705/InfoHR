import { useGSAP } from "@gsap/react";
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { submitDemoRequest } from "../../../api/welcome";
import type { ApiFailure } from "../../../api/mutate";
import { copy } from "../copy";
import { EASE, canAnimate, gsap, registerGsap } from "../motion";
import "./demo.css";

type Field = "email" | "name" | "organisation" | "phone" | "size_band" | "note";
type Values = Record<Field, string>;
type Problems = Partial<Record<Field, string>>;
type FieldElement = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

// Visual order. The first invalid field in this order gets the focus after a failed submit.
const FIELD_ORDER: Field[] = ["email", "name", "organisation", "phone", "size_band", "note"];
const REQUIRED: Field[] = ["email", "name", "organisation"];
// Same limits as the server (api/welcome). Counted after trimming.
const MAX_LENGTH: Partial<Record<Field, number>> = { email: 254, name: 120, organisation: 200, phone: 40, note: 2000 };
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const EMPTY: Values = { email: "", name: "", organisation: "", phone: "", size_band: "", note: "" };
const REQUIRED_MESSAGE: Record<"email" | "name" | "organisation", string> = {
  email: copy.form.errors.emailRequired,
  name: copy.form.errors.nameRequired,
  organisation: copy.form.errors.organisationRequired,
};

function isField(key: string): key is Field {
  return (FIELD_ORDER as string[]).includes(key);
}

// The client checks mirror the server's: required fields, email shape, length limits.
function validate(values: Values): Problems {
  const found: Problems = {};
  for (const field of REQUIRED) {
    if (values[field] === "") {
      found[field] = REQUIRED_MESSAGE[field as keyof typeof REQUIRED_MESSAGE];
    }
  }
  if (values.email !== "" && !found.email && !EMAIL_SHAPE.test(values.email)) {
    found.email = copy.form.errors.emailInvalid;
  }
  for (const field of FIELD_ORDER) {
    const max = MAX_LENGTH[field];
    if (max !== undefined && values[field].length > max && found[field] === undefined) {
      found[field] = copy.form.errors.tooLong;
    }
  }
  return found;
}

function trimmed(values: Values): Values {
  return {
    email: values.email.trim(),
    name: values.name.trim(),
    organisation: values.organisation.trim(),
    phone: values.phone.trim(),
    size_band: values.size_band,
    note: values.note.trim(),
  };
}

// Label with the required mark outside the <label> element, so the label's text is the plain field name.
function FieldLabel({ field, required }: { field: Field; required: boolean }) {
  return (
    <span className="w-demo-label-row">
      <label className="w-demo-label" htmlFor={`demo-${field}`}>
        {copy.form.labels[labelKey(field)]}
      </label>
      {required ? (
        <span className="w-demo-required" aria-hidden="true">
          {copy.form.requiredMark}
        </span>
      ) : null}
    </span>
  );
}

function labelKey(field: Field): keyof typeof copy.form.labels {
  if (field === "size_band") return "size";
  return field;
}

// The demo request form. Light tone, the page's last call to action. Static by default; the only motion is the
// thank-you fade, and only when canAnimate().
export function DemoSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const thanksRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const contactRef = useRef<HTMLInputElement>(null);
  const fieldRefs = useRef<Partial<Record<Field, FieldElement | null>>>({});
  // Synchronous guard: a second click or Enter before the disabled state renders sends nothing.
  const sendingRef = useRef(false);

  const [values, setValues] = useState<Values>(EMPTY);
  const [problems, setProblems] = useState<Problems>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [submitFailed, setSubmitFailed] = useState(false);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  // The card's height at the moment of success, pinned as min-height so the swap does not shrink the card.
  const [cardHeight, setCardHeight] = useState<number | undefined>(undefined);

  useGSAP(
    () => {
      const el = thanksRef.current;
      if (!done || !el || !canAnimate()) {
        return;
      }
      try {
        registerGsap();
        // fromTo applies the hidden start state when it is created; the thank-you is visible in the markup otherwise.
        gsap.fromTo(el, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.4, ease: EASE });
      } catch {
        // If GSAP fails, drop any inline start state so the thank-you stays visible.
        try {
          gsap.killTweensOf(el);
        } catch {
          // Ignored: the inline reset below is what matters.
        }
        el.style.removeProperty("opacity");
        el.style.removeProperty("transform");
      }
    },
    { scope: sectionRef, dependencies: [done] },
  );

  // The submit button leaves the page with the form; move focus to the confirmation so keyboard and screen-reader
  // users land on it.
  useEffect(() => {
    if (done) {
      thanksRef.current?.focus();
    }
  }, [done]);

  function focusFirst(found: Problems) {
    const first = FIELD_ORDER.find((field) => found[field] !== undefined);
    if (first) {
      fieldRefs.current[first]?.focus();
    }
  }

  // Typing in a field clears its own message; the other values stay as they are.
  function update(field: Field, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    // A message about the last submit is stale once the user is typing: clear it.
    setFormErrors([]);
    setSubmitFailed(false);
    setProblems((current) => {
      if (current[field] === undefined) {
        return current;
      }
      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  function change(field: Field) {
    return (event: ChangeEvent<FieldElement>) => update(field, event.target.value);
  }

  function setRef(field: Field) {
    return (el: FieldElement | null) => {
      fieldRefs.current[field] = el;
    };
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sendingRef.current) {
      return;
    }
    const clean = trimmed(values);
    const found = validate(clean);
    setFormErrors([]);
    setSubmitFailed(false);
    setProblems(found);
    if (Object.keys(found).length > 0) {
      focusFirst(found);
      return;
    }

    sendingRef.current = true;
    setSending(true);
    try {
      await submitDemoRequest({ ...clean, contact_ref: contactRef.current?.value ?? "" });
      // The sending guard stays set: the form is replaced, so nothing can be sent again from this page.
      // Measure the card before the form is swapped out, so the thank-you keeps the same height (no layout jump).
      const card = cardRef.current;
      if (card) {
        setCardHeight(card.offsetHeight);
      }
      setDone(true);
    } catch (error) {
      sendingRef.current = false;
      setSending(false);
      const failure = error as Partial<ApiFailure>;
      const fromServer: Problems = {};
      const generic: string[] = Array.isArray(failure.formErrors) ? [...failure.formErrors] : [];
      for (const [key, messages] of Object.entries(failure.fieldErrors ?? {})) {
        if (!Array.isArray(messages) || messages.length === 0) {
          continue;
        }
        if (isField(key)) {
          fromServer[key] = messages.join(" ");
        } else {
          generic.push(...messages);
        }
      }
      setProblems(fromServer);
      setFormErrors(generic);
      setSubmitFailed(true);
      focusFirst(fromServer);
    }
  }

  function describedBy(field: Field): string | undefined {
    const ids: string[] = [];
    if (field === "phone") {
      ids.push("demo-phone-hint");
    }
    if (problems[field] !== undefined) {
      ids.push(`demo-${field}-error`);
    }
    return ids.length > 0 ? ids.join(" ") : undefined;
  }

  function errorFor(field: Field) {
    const message = problems[field];
    if (message === undefined) {
      return null;
    }
    return (
      <p className="w-demo-error" id={`demo-${field}-error`}>
        {message}
      </p>
    );
  }

  function invalid(field: Field): "true" | undefined {
    return problems[field] !== undefined ? "true" : undefined;
  }

  return (
    <section id="demo" data-tone="light" className="w-demo" ref={sectionRef}>
      <div className="w-container">
        <h2 className="w-demo-title" id="demo-title">
          {copy.form.title}
        </h2>
        <div
          className="w-demo-card"
          ref={cardRef}
          style={cardHeight !== undefined ? { minHeight: `${cardHeight}px` } : undefined}
        >
          {done ? (
            <div role="status" className="w-demo-thanks" tabIndex={-1} ref={thanksRef}>
              <h3 className="w-demo-thanks-title">{copy.form.thanksTitle}</h3>
              <p className="w-demo-thanks-text">{copy.form.thanksText}</p>
            </div>
          ) : (
            <form className="w-demo-form" noValidate onSubmit={onSubmit} aria-labelledby="demo-title">
              <p className="w-demo-note-required">{copy.form.requiredNote}</p>
              <div className="w-demo-grid">
                <div className="w-demo-field">
                  <FieldLabel field="email" required />
                  <input
                    id="demo-email"
                    className="w-demo-input"
                    name="email"
                    type="email"
                    autoComplete="email"
                    maxLength={MAX_LENGTH.email}
                    required
                    aria-required="true"
                    aria-invalid={invalid("email")}
                    aria-describedby={describedBy("email")}
                    value={values.email}
                    onChange={change("email")}
                    ref={setRef("email")}
                  />
                  {errorFor("email")}
                </div>
                <div className="w-demo-field">
                  <FieldLabel field="name" required />
                  <input
                    id="demo-name"
                    className="w-demo-input"
                    name="name"
                    type="text"
                    autoComplete="name"
                    maxLength={MAX_LENGTH.name}
                    required
                    aria-required="true"
                    aria-invalid={invalid("name")}
                    aria-describedby={describedBy("name")}
                    value={values.name}
                    onChange={change("name")}
                    ref={setRef("name")}
                  />
                  {errorFor("name")}
                </div>
                <div className="w-demo-field">
                  <FieldLabel field="organisation" required />
                  <input
                    id="demo-organisation"
                    className="w-demo-input"
                    name="organisation"
                    type="text"
                    autoComplete="organization"
                    maxLength={MAX_LENGTH.organisation}
                    required
                    aria-required="true"
                    aria-invalid={invalid("organisation")}
                    aria-describedby={describedBy("organisation")}
                    value={values.organisation}
                    onChange={change("organisation")}
                    ref={setRef("organisation")}
                  />
                  {errorFor("organisation")}
                </div>
                <div className="w-demo-field">
                  <FieldLabel field="phone" required={false} />
                  <input
                    id="demo-phone"
                    className="w-demo-input"
                    name="phone"
                    type="tel"
                    autoComplete="tel"
                    maxLength={MAX_LENGTH.phone}
                    aria-invalid={invalid("phone")}
                    aria-describedby={describedBy("phone")}
                    value={values.phone}
                    onChange={change("phone")}
                    ref={setRef("phone")}
                  />
                  <p className="w-demo-hint" id="demo-phone-hint">
                    {copy.form.optionalPhone}
                  </p>
                  {errorFor("phone")}
                </div>
                <div className="w-demo-field">
                  <FieldLabel field="size_band" required={false} />
                  <select
                    id="demo-size_band"
                    className="w-demo-input"
                    name="size_band"
                    aria-invalid={invalid("size_band")}
                    aria-describedby={describedBy("size_band")}
                    value={values.size_band}
                    onChange={change("size_band")}
                    ref={setRef("size_band")}
                  >
                    <option value="">{copy.form.sizeNone}</option>
                    {copy.form.sizeBands.map((band) => (
                      <option key={band} value={band}>
                        {band}
                      </option>
                    ))}
                  </select>
                  {errorFor("size_band")}
                </div>
                <div className="w-demo-field w-demo-wide">
                  <FieldLabel field="note" required={false} />
                  <textarea
                    id="demo-note"
                    className="w-demo-input w-demo-textarea"
                    name="note"
                    rows={4}
                    maxLength={MAX_LENGTH.note}
                    aria-invalid={invalid("note")}
                    aria-describedby={describedBy("note")}
                    value={values.note}
                    onChange={change("note")}
                    ref={setRef("note")}
                  />
                  {errorFor("note")}
                </div>
              </div>

              {/* Honeypot: off-screen, out of the tab order, hidden from assistive tech. Bots fill it; people never see it. */}
              <input
                ref={contactRef}
                className="w-demo-hp"
                type="text"
                name="contact_ref"
                tabIndex={-1}
                autoComplete="off"
                aria-hidden="true"
                defaultValue=""
              />

              <div className="w-demo-alert" role="alert">
                {submitFailed ? <p className="w-demo-alert-text">{copy.form.errors.submitFailed}</p> : null}
                {formErrors.map((text, index) => (
                  <p className="w-demo-alert-text" key={`${index}-${text}`}>
                    {text}
                  </p>
                ))}
              </div>

              <div className="w-demo-actions">
                <button type="submit" className="w-button w-demo-submit" disabled={sending} aria-busy={sending}>
                  {copy.form.submit}
                </button>
                <p className="w-demo-privacy">{copy.form.privacy}</p>
              </div>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
