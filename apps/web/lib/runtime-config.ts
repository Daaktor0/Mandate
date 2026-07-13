export type WebRuntimeConfig = Readonly<{
  demoMode: boolean;
}>;

export function resolveWebRuntimeConfig(
  environment: Readonly<Record<string, string | undefined>> = process.env,
): WebRuntimeConfig {
  const rawDemoMode = environment.DEMO_MODE ?? "0";
  if (rawDemoMode !== "0" && rawDemoMode !== "1") {
    throw new Error("DEMO_MODE must be exactly '0' or '1'");
  }

  return Object.freeze({ demoMode: rawDemoMode === "1" });
}
