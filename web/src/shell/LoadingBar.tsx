import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import { useEffect } from "react";

// The top loading bar. It only flags the page: while any query or mutation runs, body[data-loading] is set, and
// motion.css draws the bar from that attribute (inventory M-02). Renders nothing.
export function LoadingBar() {
  const fetching = useIsFetching();
  const mutating = useIsMutating();
  const busy = fetching + mutating > 0;

  useEffect(() => {
    if (busy) {
      document.body.dataset.loading = "";
    } else {
      delete document.body.dataset.loading;
    }
  }, [busy]);

  useEffect(
    () => () => {
      delete document.body.dataset.loading;
    },
    [],
  );

  return null;
}
