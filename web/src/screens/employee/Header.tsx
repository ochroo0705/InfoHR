import { useEffect, useRef, useState, type ChangeEvent } from "react";
import type { EmployeeHeadOut } from "../../api/employee";
import { AppLink, openLegacyEmployee } from "../../lib/AppLink";
import { photoSrc, photoSrcSet } from "../../lib/photo";
import { ClashChoice } from "./ClashChoice";
import { LoginModal } from "./LoginModal";
import { usePageField, usePageFormState } from "./PageForm";

// Port of `#header` (employees/_header.html, _state.html, _activity_latest.html). Classes, Mongolian text, order, ids
// and hooks are copied from the templates. For a manager the names, the code, the work phone and the e-mail are
// edit-on-the-spot boxes of the page form (the `field` tag with the INLINE look, UI_RULES §2e), and the photo has its
// own controls. The login is a pop-up of its own (LoginModal). Every other write (event menu) is a full page load into
// Django (openLegacyEmployee, ruling D2).
// React never works out a right or a state: it renders what the API sends.

type Head = EmployeeHeadOut;

// The INLINE look of `hr.field`: a borderless edit-in-place box.
const INLINE = "border-b border-transparent bg-transparent hover:border-slate-300 focus:border-violet-600 focus:outline-none";

// One edit-on-the-spot box of the header. Its value, errors and clash come from the page form. A box the page form does
// not have (before it has loaded) shows the head's text, read-only, so the header keeps its width. `required` is the
// page form's Django flag (a hint only: the page form is noValidate, so the browser does not block the save).
function HeaderField({
  name,
  label,
  width,
  fallback,
  type = "text",
}: {
  name: string;
  label: string;
  width: string;
  fallback: string;
  type?: string;
}) {
  const box = usePageField(name);
  if (!box.editable) {
    return (
      <input
        type={type}
        readOnly
        value={fallback}
        aria-label={label}
        placeholder="—"
        autoComplete="off"
        className={`${width} ${INLINE}`}
      />
    );
  }
  return (
    <>
      <input
        type={type}
        name={box.name}
        form="emp-form"
        value={box.value}
        onChange={(event) => box.set(event.target.value)}
        required={box.required}
        aria-label={box.label || label}
        aria-invalid={box.error ? true : undefined}
        placeholder={box.placeholder || "—"}
        autoComplete="off"
        className={`${width} ${INLINE}`}
      />
      {box.error?.map((message) => (
        <p key={message} className="mt-1 text-xs text-red-600">
          {message}
        </p>
      ))}
      {box.conflict ? (
        <ClashChoice name={box.name} theirs={box.conflict} value={box.resolve} onPick={box.setResolve} />
      ) : null}
    </>
  );
}

// Revokes a blob: URL (the object URL of a picked file). A data: URL, or no URL, is left alone.
function revokeBlob(url: string | null) {
  if (url?.startsWith("blob:")) URL.revokeObjectURL(url);
}

// Port of previewPhoto (detail.html): crop the picture to a square, halve it step by step down to the circle's size
// (one big downscale looks grainy), and return a JPEG data URL.
async function squarePreview(file: File, target: number): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const side = Math.min(bitmap.width, bitmap.height);
  let source: CanvasImageSource = bitmap;
  let sx = (bitmap.width - side) / 2;
  let sy = (bitmap.height - side) / 2;
  let size = side;
  let next: number;
  let canvas: HTMLCanvasElement;
  do {
    next = Math.max(target, Math.round(size / 2));
    canvas = document.createElement("canvas");
    canvas.width = next;
    canvas.height = next;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("no 2d context");
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    context.drawImage(source, sx, sy, size, size, 0, 0, next, next);
    source = canvas;
    sx = 0;
    sy = 0;
    size = next;
  } while (next > target);
  return canvas.toDataURL("image/jpeg", 0.92);
}

// The preview of a picked file. Without the decoder or canvas, the file's object URL is shown (the template's fallback).
async function photoPreview(file: File, target: number): Promise<string | null> {
  try {
    return await squarePreview(file, target);
  } catch {
    try {
      return URL.createObjectURL(file);
    } catch {
      return null;
    }
  }
}

// The page's header (`#header`): photo, name, position, contact line, the latest-change line, the state badge, the
// next event, the buttons, and the narrow screens' fact strip. `onOpenActivity` opens the «Түүх» drawer (Task 14).
export function Header({ head, onOpenActivity }: { head: Head; onOpenActivity: () => void }) {
  const { can, facts, state, latest_activity: latest, next_event: next } = head;
  const form = usePageFormState();
  const photo = head.photo_url;
  const manage = can.manage;
  const edit = () => openLegacyEmployee(head.pk);
  // The login pop-up. Each open gets a new serial, so the pop-up starts afresh (the password step never lingers).
  const [login, setLogin] = useState({ serial: 0, open: false });
  const dash = (value: string) => value || "—";

  // The photo the user picked, shown before the save. `preview` is null when none is shown.
  const imgRef = useRef<HTMLImageElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  // The URL on screen. A blob: URL is revoked when it is replaced, dropped or the header unmounts.
  const shown = useRef<string | null>(null);
  // Counts the picks: a preview that arrives after the pick was dropped, or after a newer pick, is not shown.
  const pick = useRef(0);
  useEffect(() => () => revokeBlob(shown.current), []);
  // A save or a cancel takes the picked file away (Django reloads the page then), so the preview goes too.
  useEffect(() => {
    if (form.photo) return;
    pick.current += 1;
    revokeBlob(shown.current);
    shown.current = null;
    setPreview(null);
    if (fileRef.current) fileRef.current.value = "";
  }, [form.photo]);

  const showPreview = (src: string) => {
    if (shown.current !== src) revokeBlob(shown.current);
    shown.current = src;
    setPreview(src);
  };

  const onPhoto = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    const token = ++pick.current;
    form.setPhoto(file);
    if (!file) return;
    // A new picture replaces the one marked for removal (previewPhoto unticks the × box).
    form.setPhotoClear(false);
    const target = Math.round(imgRef.current?.clientWidth || 80) * (window.devicePixelRatio || 1);
    void photoPreview(file, target).then((src) => {
      if (!src) return;
      if (token === pick.current) {
        showPreview(src);
      } else {
        // An older pick's preview arrived late: it is not shown, and its object URL is not kept.
        revokeBlob(src);
      }
    });
  };

  const hasImage = preview !== null || Boolean(photo);
  const dimmed = manage && form.photoClear;
  // The note under the photo (detail.html: #photo-chosen).
  const chosen = form.photoClear ? "Хадгалахад устгагдана" : form.photo ? "Хадгалахад солигдоно" : "";

  return (
    <div id="header">
      {login.serial > 0 ? (
        <LoginModal
          key={login.serial}
          pk={head.pk}
          open={login.open}
          onClose={() => setLogin((prev) => ({ ...prev, open: false }))}
        />
      ) : null}
      <div className="rounded-2xl border border-slate-200 bg-surface p-4 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-start gap-x-5 gap-y-4 sm:items-center">
          <div className="flex flex-col items-center gap-1">
            <div className="relative h-20 w-20">
              <img
                ref={imgRef}
                id="photo-img"
                src={preview ?? (photo ? photoSrc(photo) : undefined)}
                srcSet={preview === null && photo ? photoSrcSet(head.photo_srcset) : undefined}
                alt=""
                className={`h-20 w-20 rounded-2xl object-cover transition-opacity${hasImage ? "" : " hidden"}${dimmed ? " opacity-30" : ""}`}
              />
              {!hasImage && (
                <div
                  id="photo-initial"
                  className="flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-100 to-amber-100 text-3xl font-extrabold text-violet-700"
                >
                  {head.given_initial}
                </div>
              )}
              {manage && (
                <label
                  className="absolute -right-1 -bottom-1 flex h-7 w-7 cursor-pointer items-center justify-center rounded-full border border-slate-200 bg-surface text-slate-600 shadow-sm hover:text-violet-700 focus-within:ring-2 focus-within:ring-violet-500"
                  title={photo ? "Зураг солих" : "Зураг нэмэх"}
                >
                  <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true">
                    <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h2l1.2-1.8h4.6L13.5 6h2A1.5 1.5 0 0 1 17 7.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 14.5z" />
                    <circle cx="10" cy="10.5" r="2.8" />
                  </svg>
                  <span className="sr-only">{photo ? "Зураг солих" : "Зураг нэмэх"}</span>
                  <input ref={fileRef} type="file" name="photo" accept="image/*" className="sr-only" onChange={onPhoto} />
                </label>
              )}
              {manage && photo && (
                <label
                  className="absolute -right-1 -top-1 flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border border-slate-200 bg-surface text-slate-500 shadow-sm hover:text-red-600 has-[:checked]:border-red-300 has-[:checked]:bg-red-50 has-[:checked]:text-red-600 focus-within:ring-2 focus-within:ring-violet-500"
                  title="Зураг устгах"
                >
                  <input
                    type="checkbox"
                    name="photo_clear"
                    className="sr-only"
                    checked={form.photoClear}
                    onChange={(event) => form.setPhotoClear(event.target.checked)}
                  />
                  <svg viewBox="0 0 20 20" width="12" height="12" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true">
                    <path d="M5 5l10 10M15 5L5 15" />
                  </svg>
                  <span className="sr-only">Зураг устгах</span>
                </label>
              )}
            </div>
            {manage && (
              <>
                <span id="photo-chosen" className="max-w-32 truncate text-xs text-slate-500">
                  {chosen}
                </span>
                {form.errorsOf("photo").map((message) => (
                  <p key={message} className="text-xs text-red-600">
                    {message}
                  </p>
                ))}
              </>
            )}
          </div>
          <div className="min-w-0 flex-1 basis-56 break-words">
            {manage ? (
              <h1 className="flex flex-wrap gap-x-2 text-2xl font-extrabold">
                <HeaderField name="family_name" label="Эцэг/эхийн нэр" width="[field-sizing:content] min-w-16" fallback={head.family_name} />
                <HeaderField name="given_name" label="Нэр" width="[field-sizing:content] min-w-16" fallback={head.given_name} />
              </h1>
            ) : (
              <h1 className="text-2xl font-extrabold">{head.full_name}</h1>
            )}
            <p className="text-slate-600">{facts.position_line}</p>
            {manage ? (
              <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-sm text-slate-500">
                <HeaderField name="code" label="Ажилтны код" width="[field-sizing:content] min-w-20" fallback={head.code} />
                <span>·</span>
                <HeaderField name="work_phone" label="Ажлын утас" width="[field-sizing:content] min-w-20" fallback={facts.work_phone} />
                <span>·</span>
                <HeaderField name="email" type="email" label="И-мэйл" width="[field-sizing:content] min-w-24" fallback={head.email} />
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
                  onClick={() => setLogin((prev) => ({ serial: prev.serial + 1, open: true }))}
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
