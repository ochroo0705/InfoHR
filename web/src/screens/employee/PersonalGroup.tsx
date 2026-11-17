import type { ReactNode, Ref } from "react";
import type { components } from "../../api/schema";

type PersonalGroupOut = components["schemas"]["EmployeePersonalGroupOut"];

// Port of `_tab_personal.html`'s group `<details data-pgroup>` and `_personal_group_summary.html`: the summary row (the
// chevron that turns on open, the group title, one count chip per section that has rows). Classes, element order and ids
// are copied from the templates. The chips' classes come from the API (`tone`); a chip whose `visible` is false keeps
// its number in the DOM with `invisible`, so the wrapper hides it (`has-[.invisible]:hidden`), as the template does.
// Open state is held by the caller (PersonalSection); the native <details> follows it through its `open` attribute,
// so `group-open:rotate-90` on the chevron works as in the template (M-23: a 150 ms turn, no other animation).
// `aria-expanded` is added to the summary for assistive tech; the template has none.

export function PersonalGroup({
  group,
  open,
  first = false,
  onToggle,
  groupRef,
  children,
}: {
  group: PersonalGroupOut;
  open: boolean;
  first?: boolean; // the «Үндсэн мэдээлэл» group is the first child, so it takes first:mt-0 (as in the template)
  onToggle: () => void;
  groupRef: Ref<HTMLDetailsElement>;
  children: ReactNode;
}) {
  return (
    <details
      ref={groupRef}
      data-pgroup={group.key}
      id={`personal-${group.key}`}
      className={`group mt-3 scroll-mt-28 lg:scroll-mt-20${first ? " first:mt-0" : ""}`}
      open={open}
    >
      <summary
        aria-expanded={open}
        onClick={(e) => {
          // The open state is React's: the click's default toggle is stopped, and the group opens or closes from state.
          e.preventDefault();
          onToggle();
        }}
        className="flex min-h-11 cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 hover:bg-slate-100 [&::-webkit-details-marker]:hidden"
      >
        <svg
          viewBox="0 0 20 20"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          className="shrink-0 text-slate-500 transition-transform group-open:rotate-90"
        >
          <path d="M7.5 4.5 13 10l-5.5 5.5" />
        </svg>
        <span className="font-semibold text-slate-900">{group.title}</span>
        <span className="ml-auto flex flex-wrap justify-end gap-1.5">
          {group.chips.map((chip) => (
            <span key={chip.key} className={chip.tone}>
              {chip.label}
              {" "}
              <span id={`menu-count-${chip.key}`} className={chip.visible ? undefined : "invisible"}>
                {chip.count_text}
              </span>
            </span>
          ))}
        </span>
      </summary>
      <div className="pt-2">{children}</div>
    </details>
  );
}
