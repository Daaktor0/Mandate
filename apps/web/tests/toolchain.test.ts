import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("NFR-03 web toolchain", () => {
  it("pins the supported Next.js and TypeScript lines", () => {
    const packageJson = JSON.parse(
      readFileSync(resolve(process.cwd(), "package.json"), "utf8"),
    ) as {
      dependencies: Record<string, string>;
      devDependencies: Record<string, string>;
    };

    expect(packageJson.dependencies.next).toMatch(/^15\./);
    expect(packageJson.dependencies.react).toMatch(/^19\./);
    expect(packageJson.devDependencies.typescript).toMatch(/^5\.8\./);
  });
});
