import ipaddr from "ipaddr.js";
import { domainToASCII } from "node:url";

const BLOCKED_HOST_SUFFIXES = [
  ".localhost",
  ".local",
  ".internal",
  ".home.arpa",
];
const ALLOWED_PORTS = new Set(["", "80", "443"]);
const HOST_LABEL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const CREDENTIAL_QUERY_KEY =
  /(?:^|[-_.])(auth|code|credential|jwt|key|password|secret|session|sig|signature|token)(?:$|[-_.])/i;

export class UnsafeIntakeUrlError extends Error {
  constructor() {
    super("The website URL must use a public HTTP or HTTPS address.");
    this.name = "UnsafeIntakeUrlError";
  }
}

function reject(): never {
  throw new UnsafeIntakeUrlError();
}

function stripIpv6Brackets(hostname: string): string {
  if (hostname.startsWith("[") && hostname.endsWith("]")) {
    return hostname.slice(1, -1);
  }
  return hostname;
}

function isPublicIp(hostname: string): boolean {
  if (!ipaddr.isValid(hostname)) {
    return false;
  }

  let address = ipaddr.parse(hostname);
  if (address instanceof ipaddr.IPv6 && address.isIPv4MappedAddress()) {
    address = address.toIPv4Address();
  }
  return address.range() === "unicast";
}

function validateHostname(rawHostname: string): string {
  const withoutBrackets = stripIpv6Brackets(rawHostname)
    .replace(/\.$/, "")
    .toLowerCase();
  if (ipaddr.isValid(withoutBrackets)) {
    if (!isPublicIp(withoutBrackets)) {
      reject();
    }
    return withoutBrackets;
  }

  const hostname = domainToASCII(withoutBrackets).toLowerCase();
  if (
    hostname.length === 0 ||
    hostname.length > 253 ||
    hostname === "localhost" ||
    BLOCKED_HOST_SUFFIXES.some((suffix) => hostname.endsWith(suffix)) ||
    !hostname.includes(".") ||
    !hostname.split(".").every((label) => HOST_LABEL.test(label))
  ) {
    reject();
  }
  return hostname;
}

/**
 * Performs the intake-time, side-effect-free portion of ADR-011.
 *
 * The worker SafeFetcher repeats these checks, resolves and vets every address,
 * pins the connection to a vetted IP and revalidates each redirect. Intake does
 * not fetch or resolve the submitted host.
 */
export function canonicalizePublicWebsiteUrl(value: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    reject();
  }

  if (
    (parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    !ALLOWED_PORTS.has(parsed.port)
  ) {
    reject();
  }
  for (const key of parsed.searchParams.keys()) {
    if (CREDENTIAL_QUERY_KEY.test(key)) {
      reject();
    }
  }

  const hostname = validateHostname(parsed.hostname);
  parsed.hostname = hostname.includes(":") ? `[${hostname}]` : hostname;
  parsed.hash = "";
  return parsed.toString();
}
