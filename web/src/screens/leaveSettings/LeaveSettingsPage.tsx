import { useEffect, useState } from "react";
import { useLeaveSettings } from "../../api/leaveSetup";
import { AppLink } from "../../lib/AppLink";
import { Forbidden } from "../../routes/ErrorPage";
import { AutoGrantForm } from "./AutoGrantForm";
import { ApprovalForm } from "./ApprovalForm";
import { TypeModal } from "./TypeModal";
import { TypesTable } from "./TypesTable";

// Port of app/leave/templates/leave/settings.html at /leave/settings/: the leave types, who approves leave, and the automatic
// annual grant. Classes, Mongolian text and the element order are copied from the template. The page keeps the default
// (narrow) width, as the Django page does. Each form saves on its own; the type pop-up is open while `modal` is set.
const TITLE = "Чөлөөний тохиргоо";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const TYPES_LEAD =
  "Ээлжийн амралтаас хасна гэж тэмдэглэсэн төрлийн чөлөө л ээлжийн амралтын үлдэгдэлд тооцогдоно. Ашиглагдаж байгаа төрлийг устгах боломжгүй.";

// The open type pop-up: id null is the add pop-up. Absent when no pop-up is open.
type TypeModalState = { id: number | null };

export function LeaveSettingsPage() {
  const query = useLeaveSettings();
  const data = query.data;
  const [modal, setModal] = useState<TypeModalState | null>(null);

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // A user without the right is refused on the first request: the forbidden screen, as the other pages.
  if ((query.error as { status?: number } | null)?.status === 403) return <Forbidden />;
  if (data === undefined) {
    return query.isError ? (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    ) : null;
  }

  return (
    <div>
      <div className="flex items-center gap-3">
        <h1 className="mr-auto text-xl font-semibold">{TITLE}</h1>
        <AppLink to="/leave/holidays/" className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          Баярын өдрүүд
        </AppLink>
        <button
          type="button"
          onClick={() => setModal({ id: null })}
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white"
        >
          Төрөл нэмэх
        </button>
      </div>

      <h2 className="mt-6 font-medium">Чөлөөний төрөл</h2>
      <p className="mt-1 text-sm text-slate-500">{TYPES_LEAD}</p>
      <TypesTable types={data.types} onOpen={(id) => setModal({ id })} />

      <ApprovalForm
        approval={data.approval}
        step1Choices={data.step1_choices}
        step2Choices={data.step2_choices}
      />

      <AutoGrantForm auto={data.auto_annual_grant} />

      {modal === null ? null : <TypeModal id={modal.id} onClose={() => setModal(null)} />}
    </div>
  );
}
