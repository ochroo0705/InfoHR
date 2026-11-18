// The clash control under a box whose saved value differs from the one being saved. The markup and texts are Django's
// app/employees/templates/employees/_field.html, except that there is no `form` attribute: React sends the page through JSON,
// not through a form id, so the radios are not tied to a form. The two radios use the name `resolve-<name>` with the values
// "mine" (keep the value typed here) and "theirs" (keep the value already saved, shown as `theirs`).
export function ClashChoice({
  name,
  theirs,
  value,
  onPick,
}: {
  name: string;
  theirs: string;
  value: "mine" | "theirs";
  onPick: (v: "mine" | "theirs") => void;
}) {
  const group = `resolve-${name}`;
  return (
    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-700">
      <label className="inline-flex items-center gap-1">
        <input
          type="radio"
          name={group}
          value="mine"
          checked={value === "mine"}
          onChange={() => onPick("mine")}
          className="accent-violet-600"
        /> Миний утгыг хадгалах
      </label>
      <label className="inline-flex items-center gap-1">
        <input
          type="radio"
          name={group}
          value="theirs"
          checked={value === "theirs"}
          onChange={() => onPick("theirs")}
          className="accent-violet-600"
        /> «{theirs}» хэвээр үлдээх
      </label>
    </div>
  );
}
