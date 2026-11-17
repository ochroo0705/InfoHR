import type { ItemOut, ToggleIn } from "../../api/today";
import { AppLink } from "../../lib/AppLink";

// The action sent with a «Мэдлээ» / «Дахин харуулах» click (ToggleIn.action on the server).
export type ToggleAction = ToggleIn["action"];
// Called by the parent with the item keys and the action; Task 12 wires it to the toggle mutation.
export type ToggleHandler = (keys: string[], action: ToggleAction) => void;

// A link that goes to the person's page; an item without an employee links to its list (`url`).
export const ATTENTION_LINK_CLASS = "font-medium text-slate-800 hover:text-violet-700 hover:underline";

// One Анхаарах line (`_attention_item.html`): the person (or «Жагсаалт») — the text, and a «Мэдлээ» or
// «Дахин харуулах» button at the end. «Мэдлээ» shows on hover or focus only; it is left out for an item without an
// employee in the dismiss list, because such an item has no person to hide.
export function AttentionItem({
  item,
  action,
  onToggle,
}: {
  item: ItemOut;
  action: "dismiss" | "restore";
  onToggle: ToggleHandler;
}) {
  const dismiss = action === "dismiss";
  const showButton = item.employee !== null || !dismiss;
  const buttonClass =
    "ml-auto shrink-0 min-h-7 rounded px-2 py-0.5 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-700" +
    (dismiss ? " opacity-0 group-hover/item:opacity-100 focus:opacity-100" : "");

  return (
    <li className="group/item flex items-baseline gap-2">
      <span>
        {item.employee ? (
          <AppLink to={item.url} className={ATTENTION_LINK_CLASS}>
            {item.employee.full_name}
          </AppLink>
        ) : (
          <AppLink to={item.url} className={ATTENTION_LINK_CLASS}>
            Жагсаалт
          </AppLink>
        )}{" "}
        <span className="text-slate-500">—</span>{" "}
        <span className={item.urgency === 0 ? "text-red-700" : undefined}>{item.text}</span>
      </span>
      {showButton ? (
        <button
          type="button"
          onClick={() => onToggle([item.key], action)}
          className={buttonClass}
          title={
            dismiss
              ? "Надад дахин харуулахгүй — өөрчлөгдвөл дахин гарна"
              : "Дахин жагсаалтад гаргах"
          }
        >
          {dismiss ? "Мэдлээ" : "Дахин харуулах"}
        </button>
      ) : null}
    </li>
  );
}
