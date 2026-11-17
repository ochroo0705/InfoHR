import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LoadingBar } from "./LoadingBar";

function deferred() {
  let resolve: (value: string) => void = () => {};
  const promise = new Promise<string>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("LoadingBar", () => {
  afterEach(() => {
    cleanup();
    delete document.body.dataset.loading;
  });

  it("sets body[data-loading] while a query is pending and removes it when it resolves", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const slow = deferred();

    function Slow() {
      useQuery({ queryKey: ["slow"], queryFn: () => slow.promise });
      return null;
    }

    render(
      <QueryClientProvider client={client}>
        <LoadingBar />
        <Slow />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(document.body.hasAttribute("data-loading")).toBe(true));

    slow.resolve("ok");

    await waitFor(() => expect(document.body.hasAttribute("data-loading")).toBe(false));
  });
});
