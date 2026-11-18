import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { useEmployeePersonal } from "../../api/employee";
import type { components } from "../../api/schema";
import { ClashChoice } from "./ClashChoice";
import { PersonalGroup } from "./PersonalGroup";
import { PersonalList } from "./PersonalList";
import { Soft, type SoftKind } from "./Soft";
import { isUnsaved, useUnsavedRevision } from "../../lib/unsaved";
import { useSectionEdit, type PersonalSectionOut } from "./sectionEdit";

// Port of `employees/_tab_personal.html`: five topic groups, each a collapsible <details> with its chips, and inside
// them the four field sections and the personal lists, placed as the template places them. The placement uses the
// API's `group` and `parent` keys: a list whose `parent` is a section sits inside that section; a list with no parent
// follows the group's sections, in the API's (template) order. Classes, Mongolian text, ids and wrappers are copied
// from the templates. React renders only the strings and flags the API sends. Field sections are soft boxes for a
// manager (`editable`) and read rows otherwise. A manager's field sections save on the spot (step 3b, task 14a): each
// has its own save strip and posts only its changed names. An inline list is edited in its own rows (15b); a pop-up list's
// add, edit and delete open its own pop-up (RowModal, 15c). Nothing here opens the Django employee page for a list write.

type PersonalOut = components["schemas"]["EmployeePersonalOut"];
type Section = PersonalOut["sections"][number];
type Row = Section["rows"][number];
type List = PersonalOut["lists"][number];

const PERSONAL_HASH = "#personal-";
const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";

// The wrapper of a list that sits inside a field section (`_section_contact.html`, `_section_education.html`).
const NESTED_WRAPPER: Record<string, { tag: "section" | "div"; className: string }> = {
  address: { tag: "section", className: "mt-6" },
  contact: { tag: "div", className: "mt-6" },
  education: { tag: "div", className: "mt-5" },
};

// A field section's read rows (`_section_identity.html` and its siblings, managers excepted): «—» muted when empty.
function ReadRows({ rows }: { rows: Row[] }) {
  return (
    <dl className="mt-4 grid grid-cols-1 gap-x-8 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
      {rows.map((row, index) => (
        <div key={index}>
          <dt className="text-xs text-slate-500">{row.label}</dt>
          <dd>{row.empty ? <span className="text-slate-300">{row.display}</span> : row.display}</dd>
        </div>
      ))}
    </dl>
  );
}

// Opens a group by its key (never closes it). PersonalBody provides it, so a section can open its own group when a save is
// refused, even when the section was already dirty and the registry does not change.
const OpenGroupContext = createContext<(key: string) => void>(() => undefined);

// The soft boxes of a field section for a manager (`_on_spot_fields.html`). Each box is bound to the section's edit state
// (sectionEdit.ts): a typed change shows the save strip and the violet edge; «Болих» drops the edits; «Хадгалах» posts the
// changed names with the section's snapshot. A refused save keeps the edits, shows the errors and keeps the strip.
function OnSpotFields({ section, pk }: { section: PersonalSectionOut; pk: number }) {
  const edit = useSectionEdit(pk, section);
  const formRef = useRef<HTMLFormElement>(null);
  const formId = `sec-${section.name}-form`;

  const openGroup = useContext(OpenGroupContext);

  // After a refused save, its group opens (sections.js openMarked) and the first box with an error comes into view
  // (sections.js and PageForm do the same).
  useEffect(() => {
    if (edit.errorTick === 0) return;
    openGroup(section.group);
    const invalid = formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
    if (invalid && typeof invalid.scrollIntoView === "function") invalid.scrollIntoView({ block: "center" });
  }, [edit.errorTick, openGroup, section.group]);

  return (
    <div id={`fields-${section.name}`}>
      <form
        ref={formRef}
        id={formId}
        data-on-spot=""
        data-dirty={edit.dirty ? "" : undefined}
        className="mt-4"
        onSubmit={(e) => {
          e.preventDefault();
          void edit.save();
        }}
      >
        {edit.formErrors.length > 0 ? (
          <div className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700">
            {edit.formErrors.map((message, i) => (
              <p key={i}>{message}</p>
            ))}
          </div>
        ) : null}
        <dl className="grid grid-cols-1 gap-x-8 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {section.fields.map((field) => {
            const error = edit.errors[field.name];
            const edited = field.name in edit.edits;
            return (
              <div key={field.name}>
                <dt className="text-xs text-slate-500">
                  {field.label}
                  {field.required ? " *" : null}
                </dt>
                <dd>
                  <Soft
                    label={field.label}
                    kind={field.kind as SoftKind}
                    value={edited ? edit.edits[field.name] : field.value}
                    choice={field.choice}
                    combo={field.combo}
                    checked={edited ? edit.edits[field.name] === "on" : field.checked}
                    placeholder={field.placeholder}
                    name={field.name}
                    form={formId}
                    onChange={(name, value) => edit.setValue(name, value)}
                    error={error && error.errors.length > 0 ? error.errors : undefined}
                    changed={edited}
                    choices={field.choices}
                  />
                  {error?.conflict ? (
                    <ClashChoice
                      name={field.name}
                      theirs={error.conflict}
                      value={edit.resolves[field.name] ?? "mine"}
                      onPick={(choice) => edit.setResolve(field.name, choice)}
                    />
                  ) : null}
                </dd>
              </div>
            );
          })}
        </dl>
        <div
          data-strip=""
          hidden={!edit.dirty}
          className="mt-4 flex items-center justify-end gap-2 rounded-lg border border-violet-300 bg-violet-50 p-2"
        >
          <span className="mr-auto flex items-center gap-2 text-sm font-medium text-violet-900">
            <span className="h-2 w-2 rounded-full bg-violet-600"></span>Хадгалаагүй өөрчлөлт байна
          </span>
          <button
            type="button"
            onClick={edit.cancel}
            className="rounded-lg border border-slate-300 bg-surface px-4 py-2 text-sm hover:bg-slate-50"
          >
            Болих
          </button>
          <button
            type="submit"
            disabled={edit.pending}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:opacity-60"
          >
            Хадгалах
          </button>
        </div>
      </form>
    </div>
  );
}

// A field section (`_section_<name>.html`): its wrapper, its title, its soft boxes or read rows, then the lists that
// sit inside it.
function FieldSection({ section, nested, pk }: { section: Section; nested: List[]; pk: number }) {
  return (
    <section id={`sec-${section.name}`} className="scroll-mt-20 pt-7">
      <h3 className="sec-title">{section.title}</h3>
      {section.editable ? <OnSpotFields section={section} pk={pk} /> : <ReadRows rows={section.rows} />}
      {nested.map((list) => {
        const wrapper = NESTED_WRAPPER[list.kind];
        const body = <PersonalList list={list} pk={pk} editable={list.editable} />;
        return wrapper.tag === "section" ? (
          <section key={list.kind} className={wrapper.className}>
            {body}
          </section>
        ) : (
          <div key={list.kind} className={wrapper.className}>
            {body}
          </div>
        );
      })}
    </section>
  );
}

// A list that stands on its own in its group (`_section_<kind>.html` with its `sec-<kind>` wrapper).
function ListSection({ list, pk }: { list: List; pk: number }) {
  return (
    <section id={`sec-${list.kind}`} className="scroll-mt-20 pt-7">
      <PersonalList list={list} pk={pk} editable={list.editable} />
    </section>
  );
}

// The body of one group: its field sections (each with the lists nested in it), then its stand-alone lists.
function GroupBody({
  groupKey,
  sections,
  lists,
  pk,
}: {
  groupKey: string;
  sections: Section[];
  lists: List[];
  pk: number;
}): ReactNode {
  return (
    <>
      {sections
        .filter((section) => section.group === groupKey)
        .map((section) => (
          <FieldSection
            key={section.name}
            section={section}
            nested={lists.filter((list) => list.parent === section.name)}
            pk={pk}
          />
        ))}
      {lists
        .filter((list) => list.group === groupKey && list.parent === null)
        .map((list) => (
          <ListSection key={list.kind} list={list} pk={pk} />
        ))}
    </>
  );
}

// The personal group key the address names (#personal-<key>), or "" when it names none.
function hashGroup(): string {
  const hash = window.location.hash;
  return hash.startsWith(PERSONAL_HASH) ? hash.slice(PERSONAL_HASH.length) : "";
}

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(REDUCED_QUERY).matches;
}

// The personal tab once its data is here. A group opens from its server default, or when the address names it; a click
// flips it. The open state lives in this component (not in the query), so a refetch does not close a group. Like
// sections.js, a named group opens and scrolls into view on load and on a hash change.
function PersonalBody({ pk, data, openGroup }: { pk: number; data: PersonalOut; openGroup?: string }) {
  const groupRefs = useRef<Record<string, HTMLDetailsElement | null>>({});
  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(data.groups.map((group) => [group.key, group.open_by_default || group.key === openGroup])),
  );

  const openGroupKey = useCallback((key: string) => {
    setOpen((current) => (current[key] ? current : { ...current, [key]: true }));
  }, []);

  const reveal = (key: string) => {
    const el = groupRefs.current[key];
    if (!el) return;
    setOpen((current) => ({ ...current, [key]: true }));
    el.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
  };

  // On load: the group the address names opens and scrolls into view (sections.js showHashGroup).
  useEffect(() => {
    if (openGroup) reveal(openGroup);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Django's openMarked (sections.js): a group that holds a section with unsaved edits or a failed save opens itself. It
  // only opens, never closes, and runs when a section's state changes (the registry revision) or the data refetches. A
  // group the user closed by hand, with no dirty section in it, is not touched.
  const unsavedRevision = useUnsavedRevision();
  useEffect(() => {
    const dirtyGroups = new Set(data.sections.filter((s) => isUnsaved("section:" + s.name)).map((s) => s.group));
    if (dirtyGroups.size === 0) return;
    setOpen((current) => {
      const missing = [...dirtyGroups].filter((key) => !current[key]);
      if (missing.length === 0) return current;
      const next = { ...current };
      missing.forEach((key) => (next[key] = true));
      return next;
    });
  }, [unsavedRevision, data.sections]);

  // Printing shows every group: a closed one opens for the print and closes again after it (sections.js beforeprint and
  // afterprint). flushSync makes the open state reach the DOM before the browser takes the print snapshot.
  const openRef = useRef(open);
  openRef.current = open;
  const printOpened = useRef<string[]>([]);
  useEffect(() => {
    const before = () => {
      const closed = Object.keys(groupRefs.current).filter((key) => groupRefs.current[key] && !openRef.current[key]);
      printOpened.current = closed;
      flushSync(() =>
        setOpen((current) => {
          const next = { ...current };
          closed.forEach((key) => (next[key] = true));
          return next;
        }),
      );
    };
    const after = () => {
      const opened = printOpened.current;
      printOpened.current = [];
      if (opened.length === 0) return;
      setOpen((current) => {
        const next = { ...current };
        opened.forEach((key) => (next[key] = false));
        return next;
      });
    };
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
    };
  }, []);

  // A hash change to another group opens and scrolls to it (sections.js: hashchange).
  useEffect(() => {
    const onHash = () => {
      const key = hashGroup();
      if (key) reveal(key);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <div className="min-w-0">
        {data.groups.map((group, index) => (
          <PersonalGroup
            key={group.key}
            group={group}
            open={!!open[group.key]}
            first={index === 0}
            groupRef={(el) => {
              groupRefs.current[group.key] = el;
            }}
            onToggle={() => setOpen((current) => ({ ...current, [group.key]: !current[group.key] }))}
          >
            <OpenGroupContext.Provider value={openGroupKey}>
              <GroupBody groupKey={group.key} sections={data.sections} lists={data.lists} pk={pk} />
            </OpenGroupContext.Provider>
          </PersonalGroup>
        ))}
      </div>
    </div>
  );
}

// Loads the personal tab. Nothing draws before the data arrives. A failed request shows the section's error line, as the
// other step-2 screens do. The section is mounted only when the header says the user may view personal data.
export function PersonalSection({ pk, openGroup }: { pk: number; openGroup?: string }) {
  const query = useEmployeePersonal(pk, true);
  const data = query.data;
  return (
    <>
      {query.error ? <p className="mb-3 text-sm text-red-600">Мэдээлэл ачаалж чадсангүй.</p> : null}
      {data ? <PersonalBody pk={pk} data={data} openGroup={openGroup} /> : null}
    </>
  );
}
