import { NextRequest, NextResponse } from "next/server";
import { getServerSupabaseClient } from "@/lib/supabaseClient";

/** Returns a saved search plus its ranked matches, joined with listing fields. */
export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = getServerSupabaseClient();

  const { data: search, error: searchError } = await supabase
    .from("searches")
    .select("*")
    .eq("id", id)
    .single();

  if (searchError || !search) {
    return NextResponse.json({ error: searchError?.message ?? "Search not found" }, { status: 404 });
  }

  const { data: matches, error: matchesError } = await supabase
    .from("search_matches")
    .select("*, listings(*)")
    .eq("search_id", id)
    .order("match_score", { ascending: false });

  if (matchesError) {
    return NextResponse.json({ error: matchesError.message }, { status: 500 });
  }

  return NextResponse.json({ search, matches: matches ?? [] });
}
