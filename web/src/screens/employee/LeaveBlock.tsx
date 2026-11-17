import { useState } from "react";
import type { EmployeeWorkOut } from "../../api/employee";
import { AppLink, openLegacyEmployee } from "../../lib/AppLink";
import { ScrollFloat } from "../../widgets/Scrollbar";

// Port of `leave/_employee_section.html` («Ээлжийн амралт»), the leave block at the end of the Work tab. Classes, Mongolian
// text, element order and data-old-year / data-old-toggle hooks are copied from the template. The API sends every string,
// class string and flag: the fold toggle shows only when there are old years to fold (`fold_old`), and its two labels come
// from Python. React only holds the fold state (folded until the user opens the old years). «Чөлөө бүртгэх» opens the
// Django page (openLegacyEmployee, ruling D2). The leave settings and the full leave list are Django pages: AppLink sends them to Django.

type Work = EmployeeWorkOut;
type Leave = Work["leave"];
type Period = Leave["periods"][number];

// One year: its <tbody>, then the details row (grants, leaves, the doubled-rights warning).
function PeriodBody({ period, hidden }: { period: Period; hidden: boolean }) {
  return (
    <tbody
      className={hidden ? `${period.row_class} hidden` : period.row_class}
      data-old-year={period.old ? "" : undefined}
    >
      <tr>
        <td className="whitespace-nowrap">
          <span className={period.period_class}>{period.period_text}</span>
          {period.badge && (
            <>
              {" "}
              <span className={period.badge.tone}>{period.badge.label}</span>
            </>
          )}
        </td>
        <td className="text-right">{period.granted}</td>
        <td className="text-right">{period.taken}</td>
        <td className="text-right">
          <span className={period.left_tone}>{period.left}</span>
        </td>
      </tr>
      <tr>
        <td colSpan={4} className="border-0 pt-0 text-xs text-slate-500">
          {period.doubled_note && <p className="mb-1 font-medium text-amber-700">{period.doubled_note}</p>}
          <ul className="space-y-0.5">
            {period.grants.map((g, i) => (
              <li key={`g${i}`}>
                {g.label}: <span className="text-slate-700">{g.days}</span>
                {g.breakdown && <> = {g.breakdown}</>}
                {g.comment && <> · {g.comment}</>}
                {g.old_chip && (
                  <>
                    {" "}
                    <span className="rounded bg-slate-100 px-1.5 text-slate-600">Хуучин системээс</span>
                  </>
                )}
              </li>
            ))}
            {period.leaves.map((l, i) => (
              <li key={`l${i}`}>
                {l.label}: <span className="text-slate-700">{l.text}</span>
                {l.old_chip && (
                  <>
                    {" "}
                    <span className="rounded bg-slate-100 px-1.5 text-slate-600">Хуучин системээс</span>
                  </>
                )}
              </li>
            ))}
          </ul>
        </td>
      </tr>
    </tbody>
  );
}

export function LeaveBlock({ work, pk }: { work: Work; pk: number }) {
  const leave = work.leave;
  // The template's script folds the old years on load (`fold_old`); the toggle opens and closes them.
  const [expanded, setExpanded] = useState(false);
  if (!leave.visible) return null;
  const folded = leave.fold_old && !expanded;

  return (
    <section className="mt-10">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="sec-title mr-auto">Ээлжийн амралт</h3>
        {leave.can_record && (
          <button
            type="button"
            onClick={() => openLegacyEmployee(pk)}
            className="rounded-lg bg-violet-600 px-3 py-1.5 text-sm text-white"
          >
            Чөлөө бүртгэх
          </button>
        )}
      </div>
      {leave.start_missing ? (
        <p className="text-sm text-amber-700">Ажилд орсон огноо бүртгэлгүй тул ээлжийн амралтыг тооцох боломжгүй.</p>
      ) : !leave.configured ? (
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          Ээлжийн амралтын төрлийг сонгоогүй байна.
          {leave.can_manage_settings && (
            <>
              {" "}
              <AppLink to={leave.settings_url} className="text-violet-700 hover:underline">
                Төрөл тохируулах
              </AppLink>
            </>
          )}
        </p>
      ) : null}
      {leave.periods.length > 0 && (
        <>
          <ScrollFloat className="ptable">
            <table>
              <thead>
                <tr>
                  <th>Ажлын жил</th>
                  <th className="text-right">Эрх</th>
                  <th className="text-right">Авсан</th>
                  <th className="text-right">Үлдэгдэл</th>
                </tr>
              </thead>
              {leave.periods.map((p, i) => (
                <PeriodBody key={i} period={p} hidden={folded && p.old} />
              ))}
            </table>
          </ScrollFloat>
          {leave.fold_old && (
            <button
              type="button"
              data-old-toggle
              onClick={() => setExpanded((open) => !open)}
              className="mt-2 text-sm text-violet-700 hover:underline"
            >
              {expanded ? leave.fold_hide_label : leave.fold_show_label}
            </button>
          )}
        </>
      )}
      {leave.no_year_started && <p className="text-sm text-slate-400">Ажлын жил эхлээгүй байна.</p>}
      {leave.nowhere.length > 0 && (
        <div className="border-t border-slate-100 py-3 text-sm">
          <span className="font-medium text-amber-700">Эрхийн хугацаагүй чөлөө</span>
          <ul className="mt-1 text-slate-600">
            {leave.nowhere.map((l, i) => (
              <li key={i}>
                {l.label}: {l.text}
                {l.old_chip && (
                  <>
                    {" "}
                    <span className="rounded bg-slate-100 px-1.5 text-xs text-slate-600">Хуучин системээс</span>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {leave.old_absences.length > 0 && (
        <div className="border-t border-slate-100 py-3 text-sm" data-old-absences>
          <span className="font-medium text-slate-700">MACS-ын «Амралт» бүртгэл</span>
          <span className="ml-1 rounded bg-slate-100 px-1.5 text-xs text-slate-600">Зөвхөн харах</span>
          <ul className="mt-1 space-y-0.5 text-slate-600">
            {leave.old_absences.map((a, i) => (
              <li key={i}>
                {a.date}: <span className="text-slate-700">{a.name}</span>
                {a.note && <> · {a.note}</>}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-slate-400">Энэ бүртгэл ээлжийн амралтын үлдэгдэлд орохгүй.</p>
        </div>
      )}
      <AppLink to={leave.all_leaves_url} className="mt-3 block text-sm text-violet-700 hover:underline">
        Бүх чөлөө (өвчний, цалингүй…)
      </AppLink>
    </section>
  );
}
