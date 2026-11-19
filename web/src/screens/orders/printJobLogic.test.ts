import { describe, expect, it } from "vitest";
import { POLL_MS, reduceJob, shouldBackground, type JobState } from "./printJobLogic";

const IDLE: JobState = { kind: "idle" };

describe("printJobLogic", () => {
  it("polls every 1500 ms", () => {
    expect(POLL_MS).toBe(1500);
  });

  it("reduceJob transitions", () => {
    const running = reduceJob(IDLE, { type: "start" });
    expect(running).toEqual({ kind: "running" });

    expect(reduceJob(running, { type: "ready", file: "/api/v1/orders/print/t1/file" })).toEqual({
      kind: "ready",
      file: "/api/v1/orders/print/t1/file",
    });

    expect(reduceJob(running, { type: "failed", message: "Сервер унтарсан." })).toEqual({
      kind: "failed",
      message: "Сервер унтарсан.",
    });

    // A failure without a message uses the default text of print_job.js.
    expect(reduceJob(running, { type: "failed" })).toEqual({ kind: "failed", message: "Бэлтгэж чадсангүй." });

    expect(reduceJob(running, { type: "close" })).toEqual(IDLE);
    expect(reduceJob({ kind: "failed", message: "x" }, { type: "close" })).toEqual(IDLE);
  });

  it("a start while a job runs changes nothing", () => {
    const running: JobState = { kind: "running" };
    expect(reduceJob(running, { type: "start" })).toBe(running);
  });

  it("shouldBackground at 10 and 11", () => {
    expect(shouldBackground(10, 11)).toBe(false);
    expect(shouldBackground(11, 11)).toBe(true);
    expect(shouldBackground(12, 11)).toBe(true);
  });
});
