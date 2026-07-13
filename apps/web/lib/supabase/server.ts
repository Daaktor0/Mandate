import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

function requireServerEnvironment(name: string): string {
  const value = process.env[name];
  if (value === undefined || value.trim() === "") {
    throw new Error(`Missing required server environment: ${name}`);
  }
  return value;
}

export async function createRequestSupabaseClient() {
  const cookieStore = await cookies();
  const url = requireServerEnvironment("NEXT_PUBLIC_SUPABASE_URL");
  const anonKey = requireServerEnvironment("NEXT_PUBLIC_SUPABASE_ANON_KEY");

  return createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(values) {
        for (const { name, value, options } of values) {
          cookieStore.set(name, value, options);
        }
      },
    },
  });
}
