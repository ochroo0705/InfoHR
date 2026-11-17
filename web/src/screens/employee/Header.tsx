import type { EmployeeHeadOut } from "../../api/employee";
import { AppLink, openLegacyEmployee } from "../../lib/AppLink";
import { photoSrc, photoSrcSet } from "../../lib/photo";

// Port of `#header` (employees/_header.html, _state.html, _activity_latest.html). Classes, Mongolian text, order, ids
// and hooks are copied from the templates. Everything here is read-only: the edit-on-the-spot boxes render readOnly,
// and every write (photo, names, event menu, login) is a full page load into Django (openLegacyEmployee, ruling D2).
// React never works out a right or a state: it renders what the API sends.

type Head = EmployeeHeadOut;

// An edit-on-the-spot box (the `field` tag with the INLINE look, UI_RULES §2e). Read-only until step 3b wires it.
function EditBox({ label, width, value }: { label: string; width: string; value: string }) {
  return (
    <input
      type="text"
      readOnly
      value={value}
      aria-label={label}
      placeholder="—"
      autoComplete="off"
      className={`${width} border-b border-transparent bg-transparent hover:border-slate-300 focus:border-violet-600 focus:outline-none`}
    />
  );
}

// The page's header (`#header`): photo, name, position, contact line, the latest-change line, the state badge, the
// next event, the buttons, and the narrow screens' fact strip. `onOpenActivity` opens the «Түүх» drawer (Task 14).
export function Header({ head, onOpenActivity }: { head: Head; onOpenActivity: () => void }) {
  const { can, facts, state, latest_activity: latest, next_event: next } = head;
  const photo = head.photo_url;
  const manage = can.manage;
  const edit = () => openLegacyEmployee(head.pk);
  const dash = (value: string) => value || "—";

  return (
    <div id="header">
      <div className="rounded-2xl border border-slate-200 bg-surface p-4 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-start gap-x-5 gap-y-4 sm:items-center">
          <div className="flex flex-col items-center gap-1">
            <div className="relative h-20 w-20">
              <img
                id="photo-img"
                src={photo ? photoSrc(photo) : undefined}
                srcSet={photo ? photoSrcSet(head.photo_srcset) : undefined}
                alt=""
                className={`h-20 w-20 rounded-2xl object-cover transition-opacity${photo ? "" : " hidden"}`}
              />
              {!photo && (
                <div
                  id="photo-initial"
                  className="flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-100 to-amber-100 text-3xl font-extrabold text-violet-700"
                >
                  {head.given_initial}
                </div>
              )}
              {manage && (
                <button
                  type="button"
                  onClick={edit}
                  className="absolute -right-1 -bottom-1 flex h-7 w-7 cursor-pointer items-center justify-center rounded-full border border-slate-200 bg-surface text-slate-600 shadow-sm hover:text-violet-700 focus-within:ring-2 focus-within:ring-violet-500"
                  title={photo ? "Зураг солих" : "Зураг нэмэх"}
                >
                  <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true">
                    <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h2l1.2-1.8h4.6L13.5 6h2A1.5 1.5 0 0 1 17 7.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 14.5z" />
                    <circle cx="10" cy="10.5" r="2.8" />
                  </svg>
                  <span className="sr-only">{photo ? "Зураг солих" : "Зураг нэмэх"}</span>
                </button>
              )}
              {manage && photo && (
                <button
                  type="button"
                  onClick={edit}
                  className="absolute -right-1 -top-1 flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border border-slate-200 bg-surface text-slate-500 shadow-sm hover:text-red-600 focus-within:ring-2 focus-within:ring-violet-500"
                  title="Зураг устгах"
                >
                  <svg viewBox="0 0 20 20" width="12" height="12" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true">
                    <path d="M5 5l10 10M15 5L5 15" />
                  </svg>
                  <span className="sr-only">Зураг устгах</span>
                </button>
              )}
            </div>
            {manage && <span id="photo-chosen" className="max-w-32 truncate text-xs text-slate-500" />}
          </div>
          <div className="min-w-0 flex-1 basis-56 break-words">
            {manage ? (
              <h1 className="flex flex-wrap gap-x-2 text-2xl font-extrabold">
                <EditBox label="Эцэг/эхийн нэр" width="[field-sizing:content] min-w-16" value={head.family_name} />
                <EditBox label="Нэр" width="[field-sizing:content] min-w-16" value={head.given_name} />
              </h1>
            ) : (
              <h1 className="text-2xl font-extrabold">{head.full_name}</h1>
            )}
            <p className="text-slate-600">{facts.position_line}</p>
            {manage ? (
              <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-sm text-slate-500">
                <EditBox label="Ажилтны код" width="[field-sizing:content] min-w-20" value={head.code} />
                <span>·</span>
                <EditBox label="Ажлын утас" width="[field-sizing:content] min-w-20" value={facts.work_phone} />
                <span>·</span>
                <EditBox label="И-мэйл" width="[field-sizing:content] min-w-24" value={head.email} />
              </div>
            ) : (
              <p className="mt-1 text-sm text-slate-500">
                {head.code} · {facts.work_phone}
                {head.email ? ` · ${head.email}` : ""}
              </p>
            )}
            <p id="activity-latest" className="mt-1 text-xs text-slate-500">
              {latest && (
                <button
                  type="button"
                  onClick={onOpenActivity}
                  title="Бүх өөрчлөлтийг харах"
                  className="line-clamp-2 text-left hover:text-violet-700 hover:underline"
                >
                  Сүүлийн өөрчлөлт: {latest.by}, {latest.at} — {latest.text}
                </button>
              )}
            </p>
          </div>
          <div className="flex w-full flex-col gap-3 self-start sm:w-auto sm:items-end">
            <div className="flex flex-col gap-1 sm:items-end">
              <span className={state.tone}>{state.label}</span>
              {next && (
                <AppLink
                  to="#work"
                  className="flex items-center gap-1 text-xs text-slate-500 hover:text-violet-700"
                  title="Ажлын түүхээс харах, цуцлах"
                >
                  <svg viewBox="0 0 20 20" width="13" height="13" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true">
                    <rect x="3" y="4.5" width="14" height="12" rx="2" />
                    <path d="M3 8.5h14M7 2.5v4M13 2.5v4" />
                  </svg>
                  {next.text}
                </AppLink>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2 sm:justify-end">
              {can.create_login && (
                <button
                  type="button"
                  onClick={edit}
                  className="flex h-11 sm:h-9 items-center whitespace-nowrap rounded-lg border border-slate-300 bg-surface px-3 text-sm hover:bg-slate-50"
                >
                  Нэвтрэх эрх үүсгэх
                </button>
              )}
              {head.event_menu.length > 0 && (
                <details className="relative">
                  <summary className="flex h-11 sm:h-9 cursor-pointer list-none items-center whitespace-nowrap rounded-lg border border-slate-300 bg-surface px-3 text-sm hover:bg-slate-50">
                    Өөрчлөлт бүртгэх ▾
                  </summary>
                  <div className="absolute right-0 z-20 mt-1 w-64 rounded-lg border border-slate-200 bg-surface py-1 shadow-lg">
                    {head.event_menu.map((item) => (
                      <button
                        key={item.value}
                        type="button"
                        onClick={edit}
                        className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-50"
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </details>
              )}
              <button
                type="button"
                onClick={onOpenActivity}
                className="flex h-11 sm:h-9 items-center gap-1.5 whitespace-nowrap rounded-lg border border-slate-300 bg-surface px-3 text-sm hover:bg-slate-50"
                title="Үйл ажиллагааны түүх"
              >
                <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true">
                  <circle cx="10" cy="10" r="7" />
                  <path d="M10 6v4l2.5 2" />
                </svg>
                <span>
                  Түүх (<span id="activity-count">{head.activity_count}</span>)
                </span>
              </button>
            </div>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-slate-100 pt-4 lg:hidden md:grid-cols-4">
          <div className="min-w-0">
            <div className="text-xs text-slate-600">Ажилд орсон</div>
            <div className="mt-0.5 font-semibold">{dash(facts.first_hire_date)}</div>
          </div>
          <div className="min-w-0">
            <div className="text-xs text-slate-500">Ажилтны төрөл</div>
            <div className="mt-0.5 truncate font-semibold">{dash(facts.employee_type)}</div>
          </div>
          <div className="min-w-0">
            <div className="text-xs text-slate-500">Гэрээ дуусах</div>
            <div className="mt-0.5 truncate font-semibold">{dash(facts.contract_end)}</div>
          </div>
          <div className="min-w-0">
            <div className="text-xs text-slate-500">Шууд удирдлага</div>
            <div className="mt-0.5 truncate font-semibold">{dash(facts.manager_label)}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
