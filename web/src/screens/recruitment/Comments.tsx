import { useRef, useState, type FormEvent } from "react";
import type { components } from "../../api/schema";
import type { ApiFailure } from "../../api/mutate";
import { useCommentCandidate } from "../../api/recruitment";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// The comments of a candidate and the box to add one (port of app/recruitment/templates/recruitment/_comments.html).
// Any user who sees the candidate may comment. A refusal keeps the typed text and shows the message above the box; a
// saved comment clears the box.

export type CommentItem = components["schemas"]["RecruitCommentOut"];

export interface CommentsProps {
  candidate: number;
  comments: CommentItem[];
}

export function Comments({ candidate, comments }: CommentsProps) {
  const comment = useCommentCandidate(candidate);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    try {
      const result = await comment.mutateAsync({ text });
      if (result.ok) {
        setText("");
        setError("");
      } else {
        setError(result.error || result.form_errors[0] || SAVE_FAILED_TEXT);
      }
    } catch (failure) {
      const detail = failure as Partial<ApiFailure>;
      setError(detail.formErrors?.[0] || Object.values(detail.fieldErrors ?? {})[0]?.[0] || SAVE_FAILED_TEXT);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };

  return (
    <div>
      {comments.length > 0 ? (
        <ul className="space-y-2">
          {comments.map((item) => (
            <li key={item.id} className="rounded-lg bg-slate-50 p-3 text-sm">
              <div className="whitespace-pre-line">{item.text}</div>
              <div className="mt-1 text-xs text-slate-500">
                {item.by} · {item.at}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-500">Сэтгэгдэл бүртгэгдээгүй</p>
      )}
      <form onSubmit={submit} className="mt-3 space-y-2" noValidate>
        {error ? (
          <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700">
            {error}
          </p>
        ) : null}
        <textarea
          rows={2}
          placeholder="Сэтгэгдэл бичих"
          aria-label="Сэтгэгдэл"
          value={text}
          onChange={(event) => setText(event.target.value)}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={pending}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:opacity-50"
          >
            Сэтгэгдэл нэмэх
          </button>
        </div>
      </form>
    </div>
  );
}
