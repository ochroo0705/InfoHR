import { useEffect, useRef, useState } from "react";
import { usePurge, usePurgePage } from "../../api/recruitment";
import { AppLink } from "../../lib/AppLink";
import { Forbidden, NotFound } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { confirm } from "../../widgets/confirm";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// Port of app/recruitment/templates/recruitment/purge.html at /recruitment/purge/ (max-w-4xl). Classes, Mongolian texts and
// the element order are copied from the template. Nothing runs by itself: «Устгах» asks through the in-app confirm first,
// then posts once. The count comes from the answer; the Django ?done= address is not used. The list refetches after the
// purge (the ["recruitment"] prefix is invalidated by the write).

const TITLE = "Татгалзсан ажил хүсэгч цэвэрлэх";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const MAIN_WIDTH = "max-w-4xl px-4";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const EMPTY_TEXT = "Цэвэрлэх ажил хүсэгч олдсонгүй";
const COLUMNS = 4;

function httpStatus(error: unknown): number | undefined {
  return (error as { status?: number } | null)?.status;
}

export function PurgePage() {
  useMainWidth(MAIN_WIDTH);
  const query = usePurgePage();
  const purge = usePurge();
  // The count of the last purge that went through, or null before one.
  const [deleted, setDeleted] = useState<number | null>(null);
  const [error, setError] = useState("");
  // A ref, not state: a second click in the same tick asks nothing and posts nothing.
  const inFlight = useRef(false);

  const data = query.data ?? null;

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on this page.
  useEffect(() => {
    if (!data) return;
    const previous = document.title;
    document.title = TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, [data]);

  // The first load failed: the not-found page, the forbidden page, or the load failure.
  if (query.isError && data === null) {
    const status = httpStatus(query.error);
    if (status === 404) return <NotFound />;
    if (status === 403) return <Forbidden />;
    return (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    );
  }
  if (data === null) return null;

  const count = data.rows.length;

  // «Устгах»: the question first; a yes posts once. A failed request shows the general save text in the red box.
  const remove = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError("");
    try {
      if (!(await confirm(`${count} ажил хүсэгчийг бүрмөсөн устгах уу?`, { ok: "Устгах" }))) return;
      const result = await purge.mutateAsync();
      setDeleted(result.deleted);
    } catch {
      setError(SAVE_FAILED_TEXT);
    } finally {
      inFlight.current = false;
    }
  };

  return (
    <div>
      <p className="text-sm">
        <AppLink to="/recruitment/" className="text-violet-700 hover:underline">
          ← Ажилд авах
        </AppLink>
      </p>
      <h1 className="mt-2 text-xl font-semibold">{TITLE}</h1>
      <p className="mt-2 text-sm text-slate-600">
        {`Татгалзсан эсвэл өөрөө татгалзсан ажил хүсэгчийг ${data.months} сарын дараа устгана (файл, сэтгэгдэлтэй нь). Автоматаар устгахгүй: энд дарж баталгаажуулна. `}
        {data.is_admin ? (
          <a href="/admin/recruitment/recruitmentsettings/" className="text-violet-700 hover:underline">
            Хадгалах хугацаа өөрчлөх
          </a>
        ) : (
          "Хугацааг админ өөрчилнө."
        )}
      </p>
      {deleted !== null ? (
        <p className="mt-3 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800" role="status">
          {`Устгасан: ${deleted} ажил хүсэгч.`}
        </p>
      ) : null}
      {error ? (
        <p className="mt-3 rounded bg-red-50 p-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}

      <div className="card-soft mt-3 overflow-x-auto px-4 pb-2">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="py-2">Ажил хүсэгч</th>
              <th>Ажлын байр</th>
              <th>Шат</th>
              <th>Хаагдсан огноо</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.id}>
                <td className="py-1.5">{row.name}</td>
                <td>{row.vacancy_title}</td>
                <td>{row.stage_label}</td>
                <td className="whitespace-nowrap">{row.closed ?? ""}</td>
              </tr>
            ))}
            {count === 0 ? (
              <tr>
                <td colSpan={COLUMNS} className="py-6 text-center text-slate-500">
                  {EMPTY_TEXT}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {count > 0 ? (
        <div className="mt-4 flex items-center justify-end gap-3">
          <span className="text-sm text-slate-600">{`${count} ажил хүсэгч`}</span>
          <button
            type="button"
            onClick={() => void remove()}
            disabled={purge.isPending}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-60"
          >
            Устгах
          </button>
        </div>
      ) : null}
    </div>
  );
}
