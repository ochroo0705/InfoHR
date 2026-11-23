import { useState } from "react";

// The «Холбоос хуулах» button beside a read-only link box (port of the inline script in
// app/employees/templates/employees/selfform/show.html, data-copy-target). The box is found by id. The clipboard API is
// tried first; when it is missing or refuses, the box text is selected and copied with execCommand. The label changes
// to «Хуулсан» only when one of the two routes reports success. When both fail, the label stays and the text stays
// selected for a manual copy. It never throws.
export function CopyLink({ targetId }: { targetId: string }) {
  const [copied, setCopied] = useState(false);

  const onClick = async () => {
    const box = document.getElementById(targetId) as HTMLInputElement | null;
    if (!box) return;
    box.select();
    // execCommand answers true only when the copy worked; a missing or throwing one counts as a failure.
    const fallback = (): boolean => {
      try {
        return document.execCommand("copy") === true;
      } catch {
        return false;
      }
    };
    let ok = false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(box.value);
        ok = true;
      } else {
        ok = fallback();
      }
    } catch {
      ok = fallback();
    }
    if (ok) setCopied(true);
  };

  return (
    <button
      type="button"
      onClick={onClick}
      className="select-none rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50"
    >
      {copied ? "Хуулсан" : "Холбоос хуулах"}
    </button>
  );
}
