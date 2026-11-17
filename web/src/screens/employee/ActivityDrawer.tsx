import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState } from "react";
import { useEmployeeActivity, type EmployeeActivityOut } from "../../api/employee";
import { AppLink, openLegacyEmployee } from "../../lib/AppLink";
import { cn } from "../../lib/utils";
import { ScrollFloat } from "../../widgets/Scrollbar";
import { useWide } from "./activityStore";

// Port of the «Түүх» drawer: `#activity-backdrop`, `#activity-drawer`, `_activity.html` and `_activity_entries.html`
// (employees/detail.html and the employees/_activity*.html partials). Classes, Mongolian text, ids and hooks are copied
// from the templates. React renders the strings and flags the API sends (day_heading, starts_day, dot_class,
// badge_class, message_class, log_url); it works out no rights, tones or headings itself.
//
// Open and close (detail.html's inline script): the backdrop and the panel are always mounted. Closed, the panel is off
// screen (translate-x-full), aria-hidden and inert; open, it slides in (transition-transform). Wide screens dock it and
// push the page (body.drawer-open); narrow screens cover the page with a backdrop. Opening moves focus to its «Хаах»;
// closing hands focus back to the button that opened it. Escape closes it only when no pop-up is open.

export interface ActivityDrawerProps {
  pk: number;
  // head.activity_count. A change after a write refetches the loaded batches.
  count: number;
  // head.can.manage: the note form is shown (the Django `can_manage` flag).
  canManage: boolean;
  open: boolean;
  onClose: () => void;
}

export function ActivityDrawer({ pk, count, canManage, open, onClose }: ActivityDrawerProps) {
  const wide = useWide();
  // The first batch is asked for on the first open, and kept after that (lazy, then cached).
  const [asked, setAsked] = useState(open);
  if (open && !asked) setAsked(true);
  const activity = useEmployeeActivity(pk, asked);

  const asideRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(open);

  // The latest close, read by the Escape listener and the buttons. Set after each render.
  const closeNow = useRef<() => void>(() => {});
  useEffect(() => {
    closeNow.current = () => {
      // Focus is handed back only when it was inside the panel (detail.html's closeDrawer).
      const back = asideRef.current?.contains(document.activeElement) ?? false;
      onClose();
      const target = opener.current;
      if (back && target && target.isConnected) target.focus();
      opener.current = null;
    };
  });

  // The body class that pushes the page on wide screens (detail.html: body.drawer-open #page).
  useEffect(() => {
    document.body.classList.toggle("drawer-open", open);
    return () => document.body.classList.remove("drawer-open");
  }, [open]);

  // Opening by the user moves focus to «Хаах». A panel that is open when the page loads does not take focus.
  useEffect(() => {
    const opened = open && !wasOpen.current;
    wasOpen.current = open;
    if (!opened) return;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
  }, [open]);

  // Escape closes the drawer unless an inner pop-up already used it (defaultPrevented) or a pop-up (#modal,
  // .fixed.inset-0.z-50) is open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.querySelector("#modal > *, .fixed.inset-0.z-50")) return;
      closeNow.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // A change in the header count (a write elsewhere added entries) refetches the batches already loaded.
  const queryClient = useQueryClient();
  const lastCount = useRef(count);
  useEffect(() => {
    if (lastCount.current === count) return;
    lastCount.current = count;
    void queryClient.invalidateQueries({ queryKey: ["employee", pk, "activity"] });
  }, [count, pk, queryClient]);

  // The end pill loads the next batch once it scrolls into view (htmx `revealed`). The pill is kept in state through a
  // callback ref, so the observer follows the element: it is set up for each pill that is shown and not loading, and
  // disconnected when the pill goes or a batch starts loading. A reopen needs nothing: the panel slides in and the
  // observer reports it.
  const [pill, setPill] = useState<HTMLButtonElement | null>(null);
  const hasNext = activity.hasNextPage;
  const fetching = activity.isFetchingNextPage;
  const pageCount = activity.data?.pages.length ?? 0;
  const { fetchNextPage } = activity;
  useEffect(() => {
    if (!pill || !hasNext || fetching || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      io.disconnect();
      void fetchNextPage();
    });
    io.observe(pill);
    return () => io.disconnect();
  }, [pill, hasNext, fetching, pageCount, fetchNextPage]);

  const close = () => closeNow.current();
  const pages = activity.data?.pages ?? [];
  // Every batch carries the same link (empty without macs.view_employees).
  const logUrl = pages[0]?.log_url ?? "";

  return (
    <>
      <div
        id="activity-backdrop"
        className={cn("fixed inset-0 top-14 z-30", open && !wide ? "" : "hidden", "bg-black/30 lg:hidden")}
        onClick={close}
      />
      <aside
        ref={asideRef}
        id="activity-drawer"
        className={cn(
          "fixed top-14 bottom-0 right-0 z-30 flex w-full flex-col border-l border-slate-200 bg-surface transition-transform duration-200 lg:w-(--drawer-w)",
          !open && "translate-x-full",
        )}
        aria-label="Үйл ажиллагааны бүртгэл"
        aria-hidden={open ? "false" : "true"}
        inert={!open}
      >
        <ScrollFloat className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain px-6 pb-6">
          <div
            className={cn(
              "sticky top-0 z-20 -mx-6 flex h-[72px] shrink-0 items-center gap-2 bg-surface px-6",
              !canManage && "mb-4 border-b border-slate-100",
            )}
          >
            <h2 className="mr-auto font-medium">Үйл ажиллагааны бүртгэл</h2>
            {logUrl ? (
              <AppLink to={logUrl} className="shrink-0 whitespace-nowrap text-sm text-violet-700 hover:underline">
                Бүрэн харах
              </AppLink>
            ) : null}
            <button
              ref={closeRef}
              type="button"
              onClick={close}
              aria-label="Хаах"
              data-drawer-close=""
              className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            >
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
          <div id="activity">
            <div>
              {canManage ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    openLegacyEmployee(pk);
                  }}
                  className="sticky top-[72px] z-10 -mx-6 mb-4 flex gap-2 border-b border-slate-100 bg-surface px-6 pb-4"
                >
                  <input
                    name="text"
                    required
                    placeholder="Тэмдэглэл бичих…"
                    className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                  <button className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white">Нэмэх</button>
                </form>
              ) : null}
              <div id="activity-list">
                {pages.map((page, index) =>
                  page.entries.length === 0 ? (
                    <p key={index} className="text-sm text-slate-500">
                      {page.empty_label}
                    </p>
                  ) : (
                    <EntryGroups key={index} batch={index} entries={page.entries} />
                  ),
                )}
                {hasNext ? (
                  <div className="col-span-full flex justify-center py-4">
                    <button
                      ref={setPill}
                      type="button"
                      data-more-batch=""
                      onClick={() => void fetchNextPage()}
                      className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-surface px-4 py-1.5 text-sm text-slate-600 hover:border-violet-300 hover:text-violet-700"
                    >
                      <svg
                        aria-hidden="true"
                        className={cn("htmx-indicator h-4 w-4 animate-spin", fetching && "htmx-request")}
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={3}
                      >
                        <path d="M12 3a9 9 0 1 0 9 9" strokeLinecap="round" />
                      </svg>
                      Цааш харуулах
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </ScrollFloat>
      </aside>
    </>
  );
}

type Entry = EmployeeActivityOut["entries"][number];

// One batch's entries, grouped by the API's starts_day flag: each day opens a heading (when the API sends one) and an
// ordered list, as `_activity_entries.html` does.
function EntryGroups({ batch, entries }: { batch: number; entries: Entry[] }) {
  const groups: { heading: string; items: Entry[] }[] = [];
  for (const entry of entries) {
    if (entry.starts_day || groups.length === 0) groups.push({ heading: entry.day_heading, items: [] });
    groups[groups.length - 1].items.push(entry);
  }
  return (
    <>
      {groups.map((group, g) => (
        <Fragment key={`${batch}-${g}`}>
          {group.heading ? (
            <h3 className="mt-5 mb-2 text-xs font-medium uppercase tracking-wide text-slate-400 first:mt-0">
              {group.heading}
            </h3>
          ) : null}
          <ol className="ml-1 border-l border-slate-200">
            {group.items.map((e, i) => (
              <li key={i} className="relative pb-4 pl-4 text-sm last:pb-1">
                <span className={e.dot_class} />
                <div className="flex items-baseline gap-2">
                  <span className="truncate font-medium">{e.by}</span>
                  <span className={e.badge_class}>{e.kind_label}</span>
                  <span className="ml-auto shrink-0 text-xs text-slate-400">{e.time}</span>
                </div>
                <p className={e.message_class}>{e.message}</p>
                {e.changes.length > 0 ? (
                  <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                    {e.changes.map((c, ci) => (
                      <Fragment key={ci}>
                        <dt className="text-slate-500">{c.field}</dt>
                        <dd className="text-slate-800">
                          {c.old ? (
                            <>
                              <s className="text-slate-400">{c.old}</s>
                              {" → "}
                            </>
                          ) : null}
                          {c.new}
                        </dd>
                      </Fragment>
                    ))}
                  </dl>
                ) : null}
              </li>
            ))}
          </ol>
        </Fragment>
      ))}
    </>
  );
}
