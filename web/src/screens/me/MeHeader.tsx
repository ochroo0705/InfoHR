import type { MeOut } from "../../api/me";
import { openLegacyPopup } from "../../lib/AppLink";

// The header card of `me.html`: the photo (or the gradient initial), the name, the job lines and «Чөлөө хүсэх».
export function MeHeader({
  employee,
  job,
  canRequest,
}: {
  employee: MeOut["employee"];
  job: MeOut["job"];
  canRequest: boolean;
}) {
  return (
    <section className="rounded-xl bg-surface p-4 shadow-sm">
      <div className="flex items-center gap-4">
        {employee.photo ? (
          <img
            src={employee.photo}
            alt=""
            width={80}
            height={80}
            className="h-20 w-20 shrink-0 rounded-2xl object-cover"
          />
        ) : (
          <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-100 to-amber-100 text-3xl font-extrabold text-violet-700">
            {employee.initial}
          </div>
        )}
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold">{employee.full_name}</h1>
          {job ? (
            <>
              <p className="text-sm text-slate-700">{job.position}</p>
              <p className="text-sm text-slate-500">{job.department}</p>
              {job.manager ? <p className="text-sm text-slate-500">Шууд удирдлага: {job.manager}</p> : null}
            </>
          ) : (
            <p className="text-sm text-slate-400">Ажлын мэдээлэл алга</p>
          )}
        </div>
      </div>
      {canRequest ? (
        <button
          type="button"
          onClick={() => openLegacyPopup("leave_request", "/me/")}
          className="mt-4 w-full rounded-lg bg-violet-600 px-4 py-3 text-base text-white hover:bg-violet-700"
        >
          Чөлөө хүсэх
        </button>
      ) : null}
    </section>
  );
}
