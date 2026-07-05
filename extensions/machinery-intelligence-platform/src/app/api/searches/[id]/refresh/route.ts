import { NextRequest, NextResponse } from "next/server";
import { getServerSupabaseClient } from "@/lib/supabaseClient";
import { refreshSearchMatches } from "@/lib/searchMatching";

/**
 * Re-scores every active listing against a saved search and upserts the
 * ranked results into search_matches. Rule-based only (MVP) — see
 * ARCHITECTURE.md §9 for the planned AI fit-rationale layer (V2).
 */
export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = getServerSupabaseClient();
  try {
    const { matchedCount, consideredCount } = await refreshSearchMatches(supabase, id);
    return NextResponse.json({ matched: matchedCount, consideredListings: consideredCount });
  } catch (err) {
    const message = (err as Error).message;
    return NextResponse.json({ error: message }, { status: message === "Search not found" ? 404 : 500 });
  }
}
