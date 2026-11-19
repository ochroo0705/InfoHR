import { useQueryClient } from "@tanstack/react-query";
import { Fragment } from "react";
import { useOrderDetail, type OrderDetailOut } from "../../api/orderDetail";
import type { ApiFailure } from "../../api/mutate";
import { AppLink } from "../../lib/AppLink";
import { Modal } from "../../widgets/Modal";
import { AttachIcon, BanIcon, EditIcon, PdfIcon, WordIcon } from "./icons";
import { loadMessagesOf, useStaleRefresh } from "./popupGuards";

// The order pop-up of `employees/_order_detail.html`: every line, class and text comes from the API (OrderDetailOut),
// except the fixed headings and labels, which are copied from the template. Which footer buttons show is decided only by
// the API's `actions` flags; nothing here is derived. The buttons call `actions`, which the provider wires to its own
// pop-ups (each closes this one first). Word and PDF are plain links to the API paths.
// Contract: the parent remounts the pop-up with a new key for each open, and keeps it mounted while `open` goes false so
// the Modal plays its exit. The query is disabled while closed, so a late answer after close is never shown.

export type OrderDetailOpeners = {
  // The other order's employee is the shown detail's `employee_pk`, passed by this pop-up.
  openOrder(orderId: number, employeePk: number): void;
  edit(orderId: number): void;
  upload(orderId: number): void;
  cancelOrder(orderId: number): void;
  cancelEvent(eventId: number): void;
  sign(orderId: number): void;
};

export type OrderDetailModalProps = {
  pk: number;
  orderId: number;
  open: boolean;
  // Called once the pop-up may close (✕, Escape, outside click). The parent sets open to false.
  onClose: () => void;
  actions: OrderDetailOpeners;
};

const LABEL = "text-slate-500";
const LINK = "text-violet-700 hover:underline";
const GREY = "text-slate-400";
const SECTION = "mb-2 border-b border-slate-200 pb-1 text-sm font-semibold text-slate-800";
const DL = "grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm";
const ICON_BUTTON = "flex h-9 w-9 items-center justify-center rounded-lg border border-slate-300 bg-surface hover:bg-slate-50";

export function OrderDetailModal({ pk, orderId, open, onClose, actions }: OrderDetailModalProps) {
  const queryClient = useQueryClient();
  const load = useOrderDetail(pk, orderId, open);
  const shown: OrderDetailOut | null = load.data ?? null;

  // A load that answers 404 means the page changed: refresh the employee's work and activity.
  const loadFailure = load.isError ? (load.error as Partial<ApiFailure>) : null;
  useStaleRefresh(loadFailure?.status === 404, pk, queryClient, ["work", "activity"]);

  // A failed load shows its message and no detail. Loading draws nothing (the Modal stays closed until the data or the
  // failure arrives).
  const showing = open && (shown !== null || load.isError);

  return (
    <Modal open={showing} onClose={onClose} title={shown?.title}>
      {shown ? (
        <Detail detail={shown} orderId={orderId} actions={actions} />
      ) : (
        <>
          <p className="rounded bg-red-50 p-2 text-sm text-red-700">{loadMessagesOf(loadFailure).join(" ")}</p>
          <div className="flex justify-end pt-3">
            <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
              Хаах
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}

function Detail({
  detail,
  orderId,
  actions,
}: {
  detail: OrderDetailOut;
  orderId: number;
  actions: OrderDetailOpeners;
}) {
  const { actions: buttons } = detail;
  const eventId = buttons.cancel_event_id;
  return (
    <>
      {/* The Modal's title sits above this line; the negative margin removes its gap, as the template has none. */}
      <div className="-mt-4 mb-1 flex items-start gap-3">
        <div>
          <p className="text-sm text-slate-500">
            <AppLink to={`/employees/${detail.employee_pk}/`} className={LINK}>
              {detail.employee_name}
            </AppLink>{" "}
            <span className="text-xs text-slate-400">{detail.employee_code}</span>
          </p>
        </div>
        <div className="ml-auto mr-8 flex items-center gap-2">
          {detail.status_chip ? <span className={detail.status_chip.tone}>{detail.status_chip.label}</span> : null}
        </div>
      </div>

      <h3 className={`mt-5 ${SECTION}`}>Өөрчлөлт</h3>
      {detail.awaiting_note ? <p className="mb-2 text-xs text-slate-500">{detail.awaiting_note}</p> : null}
      <dl className={DL}>
        {detail.change_rows.map((row, i) => (
          <Fragment key={i}>
            <dt className={LABEL}>{row.label}</dt>
            <dd>
              {!row.arrow ? (
                row.value
              ) : (
                <>
                  {row.before} <span className={GREY}>→</span> <span className="font-medium">{row.after}</span>
                </>
              )}
            </dd>
          </Fragment>
        ))}
      </dl>

      <h3 className={`mt-5 flex items-center gap-2 ${SECTION}`}>
        {detail.order_heading}
        <span className="ml-auto font-normal">
          <span className={detail.state_chip.tone}>{detail.state_chip.label}</span>
        </span>
      </h3>
      <dl className={DL}>
        {detail.order_rows.map((row, i) => (
          <Fragment key={i}>
            <dt className={LABEL}>{row.label}</dt>
            <dd>{row.value}</dd>
          </Fragment>
        ))}
        <dt className={LABEL}>Гарын үсэгтэй файл</dt>
        <dd>
          {detail.scan.url ? (
            <a href={detail.scan.url} target="_blank" rel="noopener" className={LINK}>
              {detail.scan.note}
            </a>
          ) : (
            <span className={GREY}>{detail.scan.note}</span>
          )}
        </dd>
        {detail.signing ? (
          <>
            <dt className={LABEL}>Гарын үсэг зурсан</dt>
            <dd>
              {detail.signing.text}
              <img
                src={detail.signing.image_url}
                alt="Гарын үсэг"
                width={180}
                height={60}
                loading="lazy"
                className="mt-2 h-16 rounded border border-slate-200 bg-white object-contain"
              />
            </dd>
          </>
        ) : null}
        {detail.cancel_rows.map((row, i) => (
          <Fragment key={i}>
            <dt className={LABEL}>{row.label}</dt>
            <dd>
              {row.reason}
              {row.text_prefix}
              {row.order_pk !== null ? (
                <a
                  href="#"
                  className={LINK}
                  onClick={(event) => {
                    event.preventDefault();
                    actions.openOrder(row.order_pk as number, detail.employee_pk);
                  }}
                >
                  {row.link_text}
                </a>
              ) : (
                row.link_text
              )}
              {row.suffix}
            </dd>
          </Fragment>
        ))}
      </dl>

      <h3 className={`mt-6 ${SECTION}`}>Түүх</h3>
      {detail.entries.length === 0 ? (
        <p className="text-sm text-slate-400">Бүртгэл алга</p>
      ) : (
        <ol className="ml-1 border-l border-slate-200">
          {detail.entries.map((entry, i) => (
            <li key={i} className="relative pb-3 pl-4 text-sm last:pb-1">
              <span className="absolute top-1.5 -left-[5px] h-2.5 w-2.5 rounded-full border-2 border-surface bg-violet-500"></span>
              <div className="flex items-baseline gap-2">
                <span className="truncate font-medium">{entry.by}</span>
                <span className="ml-auto shrink-0 text-xs text-slate-400">{entry.at}</span>
              </div>
              <p className="mt-0.5 text-slate-700">{entry.message}</p>
              {entry.changes.length > 0 ? (
                <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                  {entry.changes.map((change, j) => (
                    <Fragment key={j}>
                      <dt className={LABEL}>{change.field}</dt>
                      <dd className="text-slate-800">
                        {change.old ? (
                          <>
                            <s className={GREY}>{change.old}</s> →{" "}
                          </>
                        ) : null}
                        {change.new || "(хоосон)"}
                      </dd>
                    </Fragment>
                  ))}
                </dl>
              ) : null}
            </li>
          ))}
        </ol>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4">
        <div className="flex flex-wrap items-center gap-2">
          {buttons.word_url ? (
            <a
              href={buttons.word_url}
              title="Word татах"
              aria-label="Word татах"
              className={`${ICON_BUTTON} text-sky-700`}
            >
              <WordIcon />
            </a>
          ) : null}
          {buttons.pdf_url ? (
            <a
              href={buttons.pdf_url}
              title="PDF татах"
              aria-label="PDF татах"
              className={`${ICON_BUTTON} text-red-700`}
            >
              <PdfIcon />
            </a>
          ) : null}
          {buttons.upload ? (
            <button
              type="button"
              title="Файл хавсаргах"
              aria-label="Файл хавсаргах"
              className={`${ICON_BUTTON} text-slate-700`}
              onClick={() => actions.upload(orderId)}
            >
              <AttachIcon />
            </button>
          ) : null}
          {buttons.edit ? (
            <button
              type="button"
              title="Засах"
              aria-label="Засах"
              className={`${ICON_BUTTON} text-slate-700`}
              onClick={() => actions.edit(orderId)}
            >
              <EditIcon />
            </button>
          ) : null}
          {eventId !== null ? (
            <button
              type="button"
              title="Цуцлах"
              aria-label="Цуцлах"
              className={`${ICON_BUTTON} ml-3 text-red-700`}
              onClick={() => actions.cancelEvent(eventId)}
            >
              <BanIcon />
            </button>
          ) : null}
          {buttons.cancel_order ? (
            <button
              type="button"
              title="Тушаал цуцлах"
              aria-label="Тушаал цуцлах"
              className={`${ICON_BUTTON} ml-3 text-red-700`}
              onClick={() => actions.cancelOrder(orderId)}
            >
              <BanIcon />
            </button>
          ) : null}
        </div>
        {buttons.sign ? (
          <button
            type="button"
            className="ml-auto rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
            onClick={() => actions.sign(orderId)}
          >
            Гарын үсэг зурах
          </button>
        ) : null}
      </div>
    </>
  );
}
