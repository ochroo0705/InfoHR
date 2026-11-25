import { useRef, useState, type FormEvent } from "react";
import type { components } from "../../api/schema";
import type { ApiFailure } from "../../api/mutate";
import { candidateFileUrl, useUploadCandidateFile } from "../../api/recruitment";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// The files of a candidate (port of app/recruitment/templates/recruitment/_files.html). Each file is a plain link to its
// download; the whole row is the link's hit area, as the Django row. Managers get the upload box: a styled label over a
// hidden file input (UI_RULES 4a), the chosen name, and «Файл хавсаргах». The input is cleared after a saved upload.

export type FileItem = components["schemas"]["RecruitFileOut"];

export interface FilesProps {
  candidate: number;
  files: FileItem[];
  canManage: boolean;
  // The allowed types and the size limit, as the server states them (managers only see the upload box).
  extensions: string;
  maxMb: number;
}

export function Files({ candidate, files, canManage, extensions, maxMb }: FilesProps) {
  const upload = useUploadCandidateFile(candidate);
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current || file === null) return;
    inFlight.current = true;
    setPending(true);
    try {
      const result = await upload.mutateAsync(file);
      if (result.ok) {
        setError("");
        setFile(null);
        if (inputRef.current) inputRef.current.value = "";
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
      {files.length > 0 ? (
        <ul className="divide-y divide-slate-100 text-sm">
          {files.map((item) => (
            <li
              key={item.id}
              className="relative -mx-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-2 py-2 transition-colors hover:bg-violet-50 focus-within:bg-violet-50"
            >
              <a
                href={candidateFileUrl(item.id)}
                className="font-medium text-violet-700 after:absolute after:inset-0 after:content-[''] focus-visible:outline-none"
              >
                {item.name}
              </a>
              <span className="text-xs text-slate-500">
                {item.uploaded} · {item.by}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-500">Файл бүртгэгдээгүй</p>
      )}
      {canManage ? (
        <form onSubmit={submit} noValidate className="mt-3 flex flex-wrap items-center gap-2">
          <label className="cursor-pointer rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50 focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-violet-500">
            Файл сонгох
            <input
              ref={inputRef}
              type="file"
              aria-label="Файл"
              className="sr-only"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setError("");
              }}
            />
          </label>
          <span className="min-w-0 flex-1 truncate text-sm text-slate-600" aria-live="polite">
            {file?.name ?? ""}
          </span>
          <button
            type="submit"
            disabled={file === null || pending}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:opacity-50"
          >
            Файл хавсаргах
          </button>
          {error ? (
            <p role="alert" className="w-full rounded bg-red-50 p-2 text-sm text-red-700">
              {error}
            </p>
          ) : null}
          <p className="w-full text-xs text-slate-500">
            {extensions} · {maxMb} MB хүртэл
          </p>
        </form>
      ) : null}
    </div>
  );
}
