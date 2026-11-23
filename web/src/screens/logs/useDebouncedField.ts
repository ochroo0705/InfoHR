import { useEffect, useLayoutEffect, useRef, useState } from "react";

// A search box of the log filters (the Django `delay:300ms` of employee.html). The box shows what the user typed and
// sends it 300 ms after the last keystroke; `flush` sends it at once (Enter in the box, as RegisterFilters does).
//
// The address value (`paramValue`) is the page's own parameter for this box. It is watched for changes only: when it
// changes to a value this box did not send, the change came from outside (Back or forward, «Цэвэрлэх», a link, a
// change of this box's own parameter). A send still waiting is then dropped and the box shows the new value. Changes
// of other parameters (the chip «×» does not touch `q`) do not drop it. The server's cleaned echo is never used for
// this decision; the page passes the address, not the echo.
// When the address changes to a value this box sent, it is this box's own render: the box is left alone, so typing that
// came meanwhile is kept.
//
// Remaining gap (accepted, as in RegisterFilters): a change from outside to exactly the value this box has just sent, while
// that send's address change has not yet come back, is taken as the box's own render, so the pending send is not dropped.
// The timer is cleared on unmount, so nothing is sent from a page that has gone.
export function useDebouncedField(
  paramValue: string,
  onCommit: (text: string) => void,
  delayMs = 300,
): [string, (text: string) => void, () => void] {
  const [text, setTextState] = useState(paramValue);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The newest text typed (may not be sent yet): what a flush sends.
  const textRef = useRef(paramValue);
  // Texts this box sent whose address change has not come back yet, oldest first.
  const sent = useRef<string[]>([]);
  // The address value of the latest render. A send equal to it changes nothing, so no render is waited for.
  const addressRef = useRef(paramValue);
  // The timer fires after a render, so it calls the latest onCommit (the page may have changed the other filters).
  const commitRef = useRef(onCommit);

  useLayoutEffect(() => {
    commitRef.current = onCommit;
    addressRef.current = paramValue;
  });

  function cancelTimer() {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }

  function send(next: string) {
    cancelTimer();
    if (next !== addressRef.current) sent.current.push(next);
    commitRef.current(next);
  }

  useEffect(() => () => cancelTimer(), []);

  useEffect(() => {
    const at = sent.current.indexOf(paramValue);
    if (at !== -1) {
      sent.current = sent.current.slice(at + 1);
      return;
    }
    // A change from outside: a pending send is dropped and the box shows the address.
    cancelTimer();
    sent.current = [];
    textRef.current = paramValue;
    setTextState(paramValue);
  }, [paramValue]);

  function setText(next: string) {
    textRef.current = next;
    setTextState(next);
    cancelTimer();
    timer.current = setTimeout(() => send(next), delayMs);
  }

  // Sends the waiting text now. Nothing happens when no send is waiting.
  function flush() {
    if (timer.current === null) return;
    send(textRef.current);
  }

  return [text, setText, flush];
}
