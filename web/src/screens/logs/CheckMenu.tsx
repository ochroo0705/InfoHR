import { useEffect, useRef, useState } from "react";

// Port of the «Төрөл» / «Ангилал» panel in app/logs/templates/logs/employee.html and system.html: a <details> with one
// checkbox per option. The panel closes on any click outside it (the Django script does the same).
export type CheckOption = { value: string; label: string };

export type CheckMenuProps = {
  label: string;
  options: CheckOption[];
  selected: string[];
  onChange: (next: string[]) => void;
};

export function CheckMenu({ label, options, selected, onChange }: CheckMenuProps) {
  // The panel is controlled, so the outside-click close and the summary click share one state.
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    function closeOnOutsideClick(e: MouseEvent) {
      const details = ref.current;
      if (details && !details.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("click", closeOnOutsideClick);
    return () => document.removeEventListener("click", closeOnOutsideClick);
  }, []);

  const count = selected.length > 0 ? ` · ${selected.length}` : "";

  function toggle(value: string) {
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value]);
  }

  return (
    <details ref={ref} open={open} className="relative shrink-0">
      <summary
        className="flex cursor-pointer list-none items-center rounded-lg border border-slate-300 bg-surface py-2 pl-3 pr-8 text-sm hover:bg-slate-50"
        onClick={(e) => {
          e.preventDefault();
          setOpen((prev) => !prev);
        }}
      >
        {`${label}${count} ▾`}
      </summary>
      <div className="absolute left-0 z-20 mt-1 w-52 rounded-lg border border-slate-200 bg-surface py-1 shadow-lg">
        {options.map((option) => (
          <label key={option.value} className="flex cursor-pointer items-center gap-2 px-3 py-1.5 hover:bg-slate-50">
            <input type="checkbox" value={option.value} checked={selected.includes(option.value)} onChange={() => toggle(option.value)} />{" "}
            {option.label}
          </label>
        ))}
      </div>
    </details>
  );
}
