import { describe, expect, it } from "vitest";

import { resolveWebRuntimeConfig } from "../lib/runtime-config";

describe("NFR-03 ADR-014 web demo-mode switch", () => {
  it("enables demo mode only for the exact value 1", () => {
    expect(resolveWebRuntimeConfig({ DEMO_MODE: "1" }).demoMode).toBe(true);
    expect(resolveWebRuntimeConfig({ DEMO_MODE: "0" }).demoMode).toBe(false);
    expect(resolveWebRuntimeConfig({}).demoMode).toBe(false);
  });

  it("fails closed on ambiguous values", () => {
    expect(() => resolveWebRuntimeConfig({ DEMO_MODE: "true" })).toThrow(
      "DEMO_MODE must be exactly '0' or '1'",
    );
  });
});
