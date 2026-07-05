import { NextResponse } from "next/server";
import { getServerSupabaseClient } from "@/lib/supabaseClient";

/** Returns the fixed machine-type taxonomy (seeded in schema.sql) for form dropdowns. */
export async function GET() {
  const supabase = getServerSupabaseClient();
  const { data, error } = await supabase.from("machine_types").select("id, name").order("name");

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ machineTypes: data ?? [] });
}
