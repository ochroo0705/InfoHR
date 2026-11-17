import { useEffect, useRef, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { useEmployeePersonal } from "../../api/employee";
import type { components } from "../../api/schema";
import { openLegacyEmployee } from "../../lib/AppLink";
import { PersonalGroup } from "./PersonalGroup";
import { PersonalList } from "./PersonalList";
import { Soft } from "./Soft";

// Port of `employees/_tab_personal.html`: five topic groups, each a collapsible <details> with its chips, and inside
// them the four field sections and the personal lists, placed as the template places them. The placement uses the
// API's `group` and `parent` keys: a list whose `parent` is a section sits inside that section; a list with no parent
// follows the group's sections, in the API's (template) order. Classes, Mongolian text, ids and wrappers are copied
// from the templates. React renders only the strings and flags the API sends. Field sections are soft boxes for a
// manager (`editable`) and read rows otherwise. Every write (the boxes' save, add, edit) opens the Django employee page
// (openLegacyEmployee, ruling D2): no fetch.

type PersonalOut = components["schemas"]["EmployeePersonalOut"];
type Section = PersonalOut["sections"][number];
type Field = Section["fields"][number];
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

// The soft boxes of a field section for a manager (`_on_spot_fields.html`). The save strip is hidden until a change
// (step 3b wires it); its buttons open the Django page for now.
function OnSpotFields({ section, pk }: { section: Section; pk: number }) {
  return (
    <div id={`fields-${section.name}`}>
      <form id={`sec-${section.name}-form`} data-on-spot="" className="mt-4" onSubmit={(e) => e.preventDefault()}>
        <dl className="grid grid-cols-1 gap-x-8 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {section.fields.map((field: Field) => (
            <div key={field.name}>
              <dt className="text-xs text-slate-500">
                {field.label}
                {field.required ? " *" : null}
              </dt>
              <dd>
                <Soft
                  label={field.label}
                  kind={field.kind}
                  value={field.value}
                  choice={field.choice}
                  combo={field.combo}
                  checked={field.checked}
                  placeholder={field.placeholder}
                />
              </dd>
            </div>
          ))}
        </dl>
        <div
          data-strip=""
          hidden
          className="mt-4 flex items-center justify-end gap-2 rounded-lg border border-violet-300 bg-violet-50 p-2"
        >
          <span className="mr-auto flex items-center gap-2 text-sm font-medium text-violet-900">
            <span className="h-2 w-2 rounded-full bg-violet-600"></span>Хадгалаагүй өөрчлөлт байна
          </span>
          <button
            type="button"
            onClick={() => openLegacyEmployee(pk)}
            className="rounded-lg border border-slate-300 bg-surface px-4 py-2 text-sm hover:bg-slate-50"
          >
            Болих
          </button>
          <button
            type="button"
            onClick={() => openLegacyEmployee(pk)}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
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
            <GroupBody groupKey={group.key} sections={data.sections} lists={data.lists} pk={pk} />
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
