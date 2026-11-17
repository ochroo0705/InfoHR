import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// npm test runs from web/, so process.cwd() is the web/ folder.
const inputCss = readFileSync(resolve(process.cwd(), "../app/static/css/input.css"), "utf8");
const motionCss = readFileSync(resolve(process.cwd(), "src/styles/motion.css"), "utf8");

// Returns every @keyframes name with its body (the text between its outer braces), whitespace collapsed.
function keyframes(source: string): Map<string, string> {
  const found = new Map<string, string>();
  const head = /@keyframes\s+(\S+)\s*\{/g;
  for (const m of source.matchAll(head)) {
    const open = (m.index ?? 0) + m[0].length - 1;
    let depth = 0;
    let end = open;
    for (let i = open; i < source.length; i += 1) {
      if (source[i] === "{") depth += 1;
      if (source[i] === "}") {
        depth -= 1;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    found.set(m[1], source.slice(open + 1, end).replace(/\s+/g, " ").trim());
  }
  return found;
}

const inputFrames = keyframes(inputCss);
const motionFrames = keyframes(motionCss);

describe("motion.css", () => {
  it("finds the keyframes of input.css (sanity check on the parser)", () => {
    expect(inputFrames.size).toBeGreaterThanOrEqual(13);
    expect(inputFrames.has("hr-leave")).toBe(true);
  });

  it("has every @keyframes block of input.css with an identical body", () => {
    const missing = [...inputFrames.keys()].filter((name) => !motionFrames.has(name));
    expect(missing).toEqual([]);
    const different = [...inputFrames.entries()]
      .filter(([name, body]) => motionFrames.get(name) !== body)
      .map(([name]) => name);
    expect(different).toEqual([]);
  });

  it("drives the loading bar from a data-loading attribute, not from an htmx class", () => {
    expect(motionCss).toContain("body[data-loading]::before");
    expect(motionCss).not.toContain("body:has(.htmx-request)");
  });

  it("has the [data-leaving] exit rules", () => {
    expect(motionCss).toMatch(/\[data-leaving\]\s*\{[^}]*animation: hr-leave var\(--dur-out\)/);
    expect(motionCss).toMatch(/\.fixed\.inset-0\.z-50\[data-leaving\] > div \{/);
  });

  it("has the nav-panel rules, including the dark shadow", () => {
    expect(motionCss).toContain(".nav-panel {");
    expect(motionCss).toContain("details[open] > .nav-panel { animation: pal-in .12s ease-out; }");
    expect(motionCss).toContain(':root[data-theme="dark"] :is(.card-soft, .nav-panel)');
  });

  it("has the theme-switch rules of input.css 236-238, verbatim", () => {
    const rules = [
      ".theme-item .theme-check { visibility: hidden; color: var(--color-violet-600); }",
      '.theme-item[aria-pressed="true"] { font-weight: 500; }',
      '.theme-item[aria-pressed="true"] .theme-check { visibility: visible; }',
    ];
    for (const rule of rules) {
      expect(inputCss).toContain(rule);
      expect(motionCss).toContain(rule);
    }
  });

  it("keeps the header as the named view transition, and wraps the page fade in no-preference", () => {
    expect(motionCss).toContain("header.sticky { view-transition-name: topbar; }");
    expect(motionCss).toContain("@media (prefers-reduced-motion: no-preference)");
    expect(motionCss).toContain("::view-transition-group(topbar) { animation-duration: 0s; }");
  });
});
