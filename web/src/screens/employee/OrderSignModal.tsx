import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { invalidateEmployee } from "../../api/employeeWrites";
import { useDeleteSavedSignature, useOrderSignState, useSubmitOrderSign } from "../../api/orderDetail";
import type { ApiFailure } from "../../api/mutate";
import { useUnsavedFlag } from "../../lib/unsaved";
import { confirm } from "../../widgets/confirm";
import { Modal } from "../../widgets/Modal";
import { SignaturePad, type SignaturePadHandle } from "../../widgets/SignaturePad";
import { tryClose } from "../../widgets/modalLogic";
import { SAVE_FAILED_TEXT } from "./PageForm";
import { loadMessagesOf, STALE_TEXT, useStaleRefresh, usePopupGuards } from "./popupGuards";

// The order-signing pop-up of `employees/_order_sign.html`. The title and whether the user has a saved signature come
// from the API (React never decides has_saved). Two sections, as in the template: the saved picture (when has_saved) and
// the draw pad. Both stay mounted; `hidden` switches them, as the legacy script did, so the pad keeps its drawing.
// Contract: the parent remounts the pop-up with a new key for each open, and keeps it mounted while `open` goes false so
// the Modal plays its exit. The query is disabled while closed.

export type OrderSignModalProps = {
  pk: number;
  orderId: number;
  open: boolean;
  // Called once the pop-up may close (Болих, ✕, Escape, outside click, or a successful signing). The parent sets open false.
  onClose: () => void;
};

// The section the user is looking at. null: the default (saved when has_saved, else draw).
type View = "saved" | "draw" | null;

export function OrderSignModal({ pk, orderId, open, onClose }: OrderSignModalProps) {
  const queryClient = useQueryClient();
  const load = useOrderSignState(pk, orderId, open);
  const submitSign = useSubmitOrderSign(pk, orderId);
  const deleteSaved = useDeleteSavedSignature();
  const shown = load.data ?? null;
  const hasSaved = shown?.has_saved ?? false;

  const [view, setView] = useState<View>(null);
  // The saved section shows when the user has one and did not ask for the draw pad.
  const savedShown = hasSaved && view !== "draw";
  const mode = savedShown ? "saved" : "drawn";

  // The pad's picture (a PNG data URL, "" when blank) and the «Хадгалах» tick.
  const [signature, setSignature] = useState("");
  const [remember, setRemember] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [messages, setMessages] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second Enter or click in the same tick sends nothing.
  const inFlight = useRef(false);
  const padRef = useRef<SignaturePadHandle>(null);
  const { formRef, isCurrent, isMounted } = usePopupGuards(open);

  // Typed or drawn: a stroke on the pad, or the «Хадгалах» tick. Feeds the Modal's dirty check and the unsaved registry.
  const dirty = signature !== "" || remember;
  useUnsavedFlag("ordersign", open && dirty);

  // A load that answers 404 means the page changed: refresh the employee's work and activity.
  const loadFailure = load.isError ? (load.error as Partial<ApiFailure>) : null;
  useStaleRefresh(loadFailure?.status === 404, pk, queryClient, ["work", "activity"]);

  const showDraw = () => setView("draw");
  const showSaved = () => {
    // Going back to the saved signature clears the drawing, as the legacy script did.
    padRef.current?.clear();
    setRemember(false);
    setView("saved");
  };

  // Sends the sign request. A refusal keeps the pop-up open with the pad as it is.
  const send = async () => {
    if (inFlight.current || !shown) return;
    // The legacy guard: no drawn submit without a stroke (the button is disabled then too).
    if (mode === "drawn" && signature === "") return;
    inFlight.current = true;
    setPending(true);
    setMessages([]);
    let closing = false;
    try {
      const answer = await submitSign.mutateAsync({
        mode,
        signature: mode === "saved" ? "" : signature,
        remember,
      });
      if (!isCurrent()) return;
      if (answer.ok) {
        // The guard stays set: the pop-up is closing, and a second Enter must not send again.
        closing = true;
        onClose();
        return;
      }
      setMessages(answer.errors);
      // A refusal may mean the saved signature is gone (Django re-rendered and recomputed has_saved): read the sign
      // state again, so the pop-up shows the draw pad when the user has no saved signature any more.
      void load.refetch();
    } catch (error) {
      if (!isCurrent()) return;
      const failure = error as Partial<ApiFailure>;
      if (failure.status === 404) {
        // The order changed elsewhere: keep the pad, refresh the page data.
        setMessages([STALE_TEXT]);
        void invalidateEmployee(queryClient, pk, ["work", "activity"]);
      } else {
        setMessages(failure.formErrors?.length ? failure.formErrors : [SAVE_FAILED_TEXT]);
      }
    } finally {
      if (!closing) {
        inFlight.current = false;
        if (isMounted()) setPending(false);
      }
    }
  };

  // «Тийм»: deletes the saved signature, then reads the sign state again, so the pop-up shows the draw pad.
  const deleteSignature = async () => {
    try {
      await deleteSaved.mutateAsync();
    } catch (error) {
      if (!isCurrent()) return;
      const failure = error as Partial<ApiFailure>;
      setMessages(failure.formErrors?.length ? failure.formErrors : [SAVE_FAILED_TEXT]);
      return;
    }
    if (!isCurrent()) return;
    setConfirmingDelete(false);
    setView("draw");
    await load.refetch();
  };

  // «Болих» closes through the same dirty check as ✕, Escape and an outside click.
  const cancel = () => {
    void tryClose({ dirty, leaving: false, close: onClose }, (message) => confirm(message, { ok: "Хаах" }));
  };

  const loadMessages = loadMessagesOf(loadFailure);
  const showing = open && (shown !== null || load.isError);

  return (
    <Modal open={showing} onClose={onClose} dirty={dirty} title={shown?.title}>
      {shown ? (
        <form
          ref={formRef}
          noValidate
          className="space-y-3"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            void send();
          }}
        >
          {messages.length > 0 ? (
            <ul className="list-disc rounded bg-red-50 p-2 pl-6 text-sm text-red-700">
              {messages.map((message, i) => (
                <li key={i}>{message}</li>
              ))}
            </ul>
          ) : null}

          {hasSaved ? (
            <section data-sign-section="saved" hidden={!savedShown} className="space-y-4">
              <div className="flex justify-center rounded-lg border border-slate-300 bg-white p-4">
                <img
                  src={shown.saved_url}
                  alt="Хадгалсан гарын үсэг"
                  width={300}
                  height={100}
                  className="h-24 w-auto object-contain"
                />
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-t border-slate-100 pt-4">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                  <button type="button" onClick={showDraw} className="text-violet-700 hover:underline">
                    Өөр гарын үсэг зурах
                  </button>
                  <span hidden={confirmingDelete}>
                    <button
                      type="button"
                      onClick={() => setConfirmingDelete(true)}
                      className="rounded px-2 py-1 text-red-600 hover:bg-red-50"
                    >
                      Устгах
                    </button>
                  </span>
                  <span hidden={!confirmingDelete} className="text-xs text-slate-700">
                    <span>Хадгалсан гарын үсгийг устгах уу?</span>{" "}
                    <button
                      type="button"
                      onClick={() => void deleteSignature()}
                      disabled={deleteSaved.isPending}
                      className="rounded px-1.5 py-1 font-medium text-red-600 hover:bg-red-50"
                    >
                      Тийм
                    </button>{" "}
                    <button
                      type="button"
                      onClick={() => setConfirmingDelete(false)}
                      disabled={deleteSaved.isPending}
                      className="rounded px-1.5 py-1 hover:bg-slate-100"
                    >
                      Үгүй
                    </button>
                  </span>
                </div>
                <div className="ml-auto flex gap-2">
                  <button type="button" onClick={cancel} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
                    Болих
                  </button>
                  <button
                    type="submit"
                    disabled={pending || deleteSaved.isPending}
                    className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:opacity-60"
                  >
                    Баталгаажуулж гарын үсэг зурах
                  </button>
                </div>
              </div>
            </section>
          ) : null}

          <section data-sign-section="draw" hidden={savedShown} className="space-y-4">
            <p className="text-xs text-slate-500">Гарын үсгээ доорх хайрцагт хулгана, хуруу эсвэл үзгээр зурна уу.</p>
            <SignaturePad ref={padRef} onChange={setSignature} />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                name="remember"
                checked={remember}
                onChange={(event) => setRemember(event.target.checked)}
                className="rounded border-slate-300"
              />{" "}
              Хадгалах
            </label>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-t border-slate-100 pt-4">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                <button type="button" onClick={() => padRef.current?.clear()} className="text-violet-700 hover:underline">
                  Цэвэрлэх
                </button>
                {hasSaved ? (
                  <button type="button" onClick={showSaved} className="text-violet-700 hover:underline">
                    Буцах
                  </button>
                ) : null}
              </div>
              <div className="ml-auto flex gap-2">
                <button type="button" onClick={cancel} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
                  Болих
                </button>
                <button
                  type="submit"
                  disabled={signature === "" || pending}
                  className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Гарын үсэг зурах
                </button>
              </div>
            </div>
          </section>
        </form>
      ) : (
        <>
          <p className="rounded bg-red-50 p-2 text-sm text-red-700">{loadMessages.join(" ")}</p>
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
