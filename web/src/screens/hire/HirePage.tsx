import { Fragment, useEffect, useRef, useState, type FormEvent } from "react";
import { flushSync } from "react-dom";
import { useSearchParams } from "react-router";
import { nav } from "../../api/client";
import type { EmployeeFormFieldOut } from "../../api/employeeWrites";
import {
  useHireForm,
  useHireSubmit,
  type HireFormOut,
  type HireResultOut,
  type HireSectionOut,
  type HireTabOut,
} from "../../api/hire";
import { AppLink } from "../../lib/AppLink";
import { isPorted } from "../../lib/ported";
import { setUnsaved, useUnsavedFlag, useUnsavedGuard } from "../../lib/unsaved";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { Forbidden, NotFound } from "../../routes/ErrorPage";
import { initialValue, toPostValues, type FormValues } from "../../widgets/FormFields";
import { HireField } from "./HireField";
import { HireOrderBlock } from "./HireOrderBlock";
import { HireTabs } from "./HireTabs";
import { firstErrorTab, requiredNames, tabBadge, tabNames, tabOfField, type TabBadge } from "./hireTabLogic";
import { RegisterCheck } from "./RegisterCheck";
import { ReviewPanel } from "./ReviewPanel";
import { keepDistrict, useDistricts } from "./useDistricts";

// Port of app/employees/templates/employees/add.html: the add-employee page at /employees/new/. The classes, the
// Mongolian text and the element order are copied from the template. The server sends the layout (tabs, sections and
// the fields of each section); this page draws it, keeps the typed values and sends the hire.
// Not ported: the Django messages banner, and the non-field errors of the address and contact blocks (no field in the
// API response carries them).

const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const PAGE_TITLE = "Ажилтан нэмэх";
// The text shown for a rejected request (no form errors come back with it).
const GENERIC_FAILURE = "Алдаа гарлаа. Дахин оролдоно уу.";
// Order-block fields are counted as the order block's own messages, not as the tab's field errors (add.html parity).
const ORDER_PREFIX = "order-";
const REGISTER_NAME = "register_no";
// The city and district boxes (the names the server sends); the district list follows the city.
const CITY_NAME = "addr-city";
const DISTRICT_NAME = "addr-district";
// The photo box and its hint after a refused post (add.html: "Зургаа дахин сонгоно уу").
const PHOTO_NAME = "photo";
const PHOTO_HINT = "Зургаа дахин сонгоно уу";
// The unsaved-registry key of this page (lib/unsaved.ts).
const UNSAVED_KEY = "hire";

type Errors = Record<string, string[]>;
type Ids = { candidate: string; submission: string };

function idText(id: number | null | undefined): string {
  return id === null || id === undefined ? "" : String(id);
}

// The messages each field starts with (the server's own errors on the description).
function errorsOf(fields: EmployeeFormFieldOut[]): Errors {
  const out: Errors = {};
  for (const field of fields) {
    if (field.errors.length > 0) out[field.name] = field.errors;
  }
  return out;
}

// The errors record without one field's messages (a field error clears when the field is edited).
function withoutField(errors: Errors, name: string): Errors {
  if (!errors[name]) return errors;
  const next = { ...errors };
  delete next[name];
  return next;
}

// The first field, in layout order, that has an error (the one whose box gets the focus after a refusal).
function firstErrorField(tabs: HireTabOut[], errors: Errors): string | null {
  for (const tab of tabs) {
    for (const name of tabNames(tab)) {
      if ((errors[name]?.length ?? 0) > 0) return name;
    }
  }
  return null;
}

// Loads the form. A 403 or 404 is the matching screen; nothing is drawn while loading (the shell's loading bar is the
// only feedback, as on the Django page).
export function HirePage() {
  const [params] = useSearchParams();
  const candidate = params.get("candidate") ?? "";
  const submission = params.get("submission") ?? "";
  const query = useHireForm(candidate, submission);
  const form = query.data;

  if (!form) {
    if (query.error) {
      const status = (query.error as { status?: number }).status;
      if (status === 403) return <Forbidden />;
      if (status === 404) return <NotFound />;
      return <p className="text-sm text-red-600">Мэдээлэл ачаалж чадсангүй.</p>;
    }
    return null;
  }

  // A different candidate or submission in the address is a new page.
  return <HireForm key={candidate + "|" + submission} form={form} />;
}

function HireForm({ form }: { form: HireFormOut }) {
  // The loaded form is held here, so a later render of the query never changes the layout under the typed values.
  const [held] = useState(form);
  const { fields, tabs } = held;

  // The values the page starts with; the page is dirty while any value differs from them (or a photo is chosen).
  const [initial] = useState<FormValues>(() =>
    Object.fromEntries(fields.map((field) => [field.name, initialValue(field)])),
  );
  const [values, setValues] = useState<FormValues>(initial);
  const [errors, setErrors] = useState<Errors>(() => errorsOf(fields));
  const [active, setActive] = useState<string>(
    () => firstErrorTab(tabs, errorsOf(fields)) ?? tabs[0]?.key ?? "",
  );
  const [photo, setPhoto] = useState<File | null>(null);
  // The chosen file as of now (the state above is the value a handler saw when it was created; a refusal reads this).
  const photoRef = useRef<File | null>(null);
  // After a refused post that carried a photo: the file box is remounted (a file input cannot be refilled) and the
  // hint shows until a new file is chosen.
  const [photoHint, setPhotoHint] = useState(false);
  const [photoKey, setPhotoKey] = useState(0);
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [orderErrors, setOrderErrors] = useState<string[]>([]);
  const [ids, setIds] = useState<Ids>(() => ({
    candidate: idText(held.candidate),
    submission: idText(held.submission),
  }));
  const [denied, setDenied] = useState(false);
  const [busy, setBusy] = useState(false);
  // A ref, not the state: two submits in one tick must send one request.
  const busyRef = useRef(false);
  // The native control of each field, for the focus after a refusal.
  const controls = useRef(new Map<string, HTMLElement>());
  const focusName = useRef<string | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  const mutation = useHireSubmit();
  const go = useTransitionNavigate();

  // The district list follows the city (`_district_field.html`). With no city the server's own list stays.
  const city = values[CITY_NAME] ?? "";
  const districts = useDistricts(city);
  const { choices, loading, failed } = districts;
  // A failed request leaves the server's own list in the box (and the saved district alone, see below).
  const shownFields = fields.map((field) =>
    field.name === DISTRICT_NAME && city !== "" && !failed ? { ...field, choices } : field,
  );
  const fieldByName = new Map(shownFields.map((field) => [field.name, field]));

  // The district is cleared only once the city's list has loaded and does not offer it (never while loading, or a stale
  // district could be posted). A failed request is not an answer: the saved district stays. The first render has the
  // server's district in place: it is kept when offered.
  // `city` is in the dependencies so that a change of city re-runs the check even when the list did not change identity.
  useEffect(() => {
    if (city === "" || loading || failed) return;
    setValues((prev) => {
      const current = prev[DISTRICT_NAME] ?? "";
      const kept = keepDistrict(current, choices);
      return kept === current ? prev : { ...prev, [DISTRICT_NAME]: kept };
    });
  }, [city, choices, loading, failed]);

  // Emptying the city clears the district (Django swaps the district select for the empty list of no city). Only a change
  // clears it: the first render keeps the server's own district, whatever the city.
  const previousCity = useRef(city);
  useEffect(() => {
    const changed = previousCity.current !== city;
    previousCity.current = city;
    if (!changed || city !== "") return;
    setValues((prev) => (prev[DISTRICT_NAME] ? { ...prev, [DISTRICT_NAME]: "" } : prev));
  }, [city]);

  const photoChosen = photo !== null;
  const dirty = photoChosen || fields.some((field) => (values[field.name] ?? "") !== (initial[field.name] ?? ""));
  useUnsavedFlag(UNSAVED_KEY, dirty);
  // The tab close and reload prompt while the form is dirty (the shell's guard covers in-app links only).
  useUnsavedGuard();

  useEffect(() => {
    const previous = document.title;
    document.title = PAGE_TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // Runs after the refusal's render, when the tab is open and the box is visible.
  useEffect(() => {
    const name = focusName.current;
    if (name === null) return;
    focusName.current = null;
    // The order block's boxes have no ref hook (HireOrderBlock), so they are found by their name in the form.
    const el = controls.current.get(name) ?? formRef.current?.querySelector<HTMLElement>(`[name="${name}"]`);
    el?.focus();
  });

  // The browser's own check blocks the submit on an empty required box, and a box in a hidden tab cannot be shown. As
  // add.html does, the tab of the first invalid control opens and that control gets the focus; the rest of the same
  // submit attempt are ignored. The tab opens synchronously (flushSync) so the box is visible when it is focused.
  useEffect(() => {
    const form = formRef.current;
    if (!form) return;
    let reporting = false;
    const onInvalid = (event: Event) => {
      if (reporting) return;
      reporting = true;
      setTimeout(() => {
        reporting = false;
      }, 0);
      const control = event.target as HTMLElement;
      const name = control.getAttribute("name") ?? "";
      const section = control.closest<HTMLElement>("section[data-tab]");
      const key = (name ? tabOfField(tabs, name) : null) ?? section?.dataset.tab ?? null;
      if (key !== null) flushSync(() => setActive(key));
      control.focus();
    };
    form.addEventListener("invalid", onInvalid, true);
    return () => form.removeEventListener("invalid", onInvalid, true);
  }, [tabs]);

  // Every value update is functional: the order block can call this twice in a row (number, then date).
  function change(name: string, value: string) {
    setValues((prev) => ({ ...prev, [name]: value }));
    setErrors((prev) => withoutField(prev, name));
  }

  function choosePhoto(file: File | null) {
    photoRef.current = file;
    setPhoto(file);
    if (file) setPhotoHint(false);
  }

  function refuse(result: HireResultOut, sentFile: File | null) {
    setErrors(result.field_errors);
    // A field error whose box the layout does not draw would vanish: it goes to the top messages instead.
    const drawn = new Set(tabs.flatMap((tab) => tabNames(tab)));
    const unplaced = Object.entries(result.field_errors)
      .filter(([name]) => !drawn.has(name))
      .flatMap(([, messages]) => messages);
    setFormErrors([...result.form_errors, ...unplaced]);
    setOrderErrors(result.order_errors);
    // The refused ids stay in the form (the server returns them), so a second save cannot turn into a plain hire.
    setIds({ candidate: idText(result.candidate), submission: idText(result.submission) });
    const tab = firstErrorTab(tabs, result.field_errors);
    if (tab) setActive(tab);
    focusName.current = firstErrorField(tabs, result.field_errors);
    // The file box cannot keep its file: it is cleared and remounted, and the user is asked to choose it again. A file
    // chosen while the request ran is not the sent one, so it stays (and no hint shows).
    const cleared = sentFile !== null && photoRef.current === sentFile;
    if (cleared) {
      photoRef.current = null;
      setPhoto(null);
      setPhotoKey((key) => key + 1);
    }
    setPhotoHint(cleared);
  }

  // The body values: every field but the photo; an unchecked checkbox is omitted, as a browser omits it (the API takes
  // "on" or absent). toPostValues itself keeps "" for it, which other screens rely on.
  function postValues(): FormValues {
    const out = toPostValues(
      fields.filter((field) => field.kind !== "file"),
      values,
    );
    for (const field of fields) {
      if (field.kind === "checkbox" && out[field.name] === "") delete out[field.name];
    }
    return out;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    // The page stays locked after a successful hire: it is leaving.
    let leaving = false;
    // The file this request carries (a file chosen while it runs is a different one).
    const sentFile = photo;
    try {
      const result = await mutation.mutateAsync({
        values: postValues(),
        candidate: ids.candidate,
        submission: ids.submission,
        photo: sentFile,
      });
      if (result.ok) {
        leaving = true;
        // Clean before the page leaves, so the leave guard does not ask about the edits just saved.
        setUnsaved(UNSAVED_KEY, false);
        if (isPorted(result.redirect)) go(result.redirect);
        else nav.assign(result.redirect);
        return;
      }
      refuse(result, sentFile);
    } catch (error) {
      if ((error as { status?: number }).status === 403) {
        setDenied(true);
      } else {
        setFormErrors([GENERIC_FAILURE]);
      }
    } finally {
      if (!leaving) {
        busyRef.current = false;
        setBusy(false);
      }
    }
  }

  if (denied) return <Forbidden />;

  // The tab badges: the error count (order-field errors are not counted, as in Django) and the done mark. The required
  // list includes the order number, which sits in the basic tab's order section.
  const badges: Record<string, TabBadge> = {};
  for (const tab of tabs) {
    const names = tabNames(tab);
    badges[tab.key] = tabBadge(
      { names: names.filter((name) => !name.startsWith(ORDER_PREFIX)), required: requiredNames(fields, names) },
      values,
      errors,
    );
  }

  function registerControl(name: string, el: HTMLElement | null) {
    if (el) controls.current.set(name, el);
    else controls.current.delete(name);
  }

  function renderField(name: string) {
    const field = fieldByName.get(name);
    if (!field) return null;
    const value = values[name] ?? "";
    return (
      <HireField
        // The photo box gets a new key after a refused post, which empties the file input.
        key={name === PHOTO_NAME ? `${name}-${photoKey}` : name}
        field={field}
        value={value}
        onChange={(next) => change(name, next)}
        onFile={choosePhoto}
        errors={errors[name] ?? []}
        afterControl={name === REGISTER_NAME ? <RegisterCheck value={value} /> : undefined}
        controlRef={(el) => registerControl(name, el)}
      />
    );
  }

  function renderSection(section: HireSectionOut, index: number) {
    if (section.kind === "order") {
      return (
        <div key={index} className="mt-8 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          <HireOrderBlock
            section={section}
            fields={shownFields}
            values={values}
            errors={errors}
            onChange={change}
            formErrors={orderErrors}
          />
        </div>
      );
    }
    const heading = index === 0 ? "mb-4 font-medium" : "mb-4 mt-8 font-medium";
    return (
      <div key={index}>
        <h2 className={heading}>{section.heading}</h2>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {section.names.map((name) => (
            <Fragment key={name}>
              {name === DISTRICT_NAME ? (
                // The Django wrapper (`_district_field.html`) is the grid child: it takes the cell, the label fills it.
                <div id="addr-district-wrap">{renderField(name)}</div>
              ) : (
                renderField(name)
              )}
              {name === PHOTO_NAME && photoHint ? (
                <p className="-mt-1 text-xs text-slate-500 md:col-span-2 lg:col-span-3">{PHOTO_HINT}</p>
              ) : null}
            </Fragment>
          ))}
        </div>
      </div>
    );
  }

  // Every panel stays mounted; the inactive ones are hidden, so the typed values and the register check persist.
  function renderTab(tab: HireTabOut) {
    const on = tab.key === active;
    return (
      <section
        key={tab.key}
        role="tabpanel"
        data-tab={tab.key}
        className={`rounded-xl border border-slate-200 bg-surface p-6${on ? "" : " hidden"}`}
      >
        {tab.sections.map(renderSection)}
      </section>
    );
  }

  return (
    <>
      <h1 className="mb-4 text-xl font-semibold">{held.title}</h1>
      {formErrors.map((message, i) => (
        <p key={i} className="mb-4 rounded bg-red-50 p-2 text-sm text-red-700">
          {message}
        </p>
      ))}
      <form ref={formRef} id="add-form" onSubmit={onSubmit} noValidate={false} className="space-y-6 pb-24">
        {ids.candidate ? <input type="hidden" name="candidate" value={ids.candidate} /> : null}
        {ids.submission ? <input type="hidden" name="submission" value={ids.submission} /> : null}
        {held.review ? (
          <ReviewPanel
            review={held.review}
            duplicate={held.duplicate}
            submissionId={held.submission ?? 0}
            onDone={(redirect) => {
              // A full page load: clean first, so the browser does not ask a second time.
              setUnsaved(UNSAVED_KEY, false);
              nav.assign(redirect);
            }}
          />
        ) : null}
        <div className="flex flex-col gap-6 md:flex-row">
          <HireTabs
            tabs={tabs.map((tab) => ({ key: tab.key, label: tab.label }))}
            active={active}
            badges={badges}
            onSelect={setActive}
          />
          <div className="min-w-0 flex-1 space-y-6">{tabs.map(renderTab)}</div>
        </div>

        <div className="fixed inset-x-0 bottom-0 z-40 px-4 pb-4">
          <div className="mx-auto flex max-w-6xl items-center justify-end gap-2 rounded-xl border-2 border-violet-500 bg-violet-50 p-3 shadow-[0_-8px_24px_rgba(15,23,42,0.18)]">
            <AppLink to="/employees/" className="rounded-lg border border-slate-300 bg-surface px-4 py-2 text-sm">
              Болих
            </AppLink>
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white disabled:opacity-60"
            >
              Ажилтан үүсгэх
            </button>
          </div>
        </div>
      </form>
    </>
  );
}
