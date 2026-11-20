import type { Plugin } from "vite";
import { PORTED } from "./src/lib/ported";

// The Python front server reads this list, so it must be plain regex sources: no flags, no named groups.
export function portedManifest(patterns: RegExp[]): string[] {
  return patterns.map((pattern) => {
    if (pattern.flags !== "") {
      throw new Error(`PORTED pattern ${pattern} has flags "${pattern.flags}", which the Python server does not read`);
    }
    if (pattern.source.includes("(?<")) {
      throw new Error(`PORTED pattern ${pattern} has a named group, which Python reads differently`);
    }
    return pattern.source;
  });
}

// Writes dist/ported.json on `vite build` so the front server knows which paths the React app serves.
export default function portedPlugin(): Plugin {
  return {
    name: "macs-ported-manifest",
    apply: "build",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "ported.json",
        source: JSON.stringify(portedManifest(PORTED)),
      });
    },
  };
}
