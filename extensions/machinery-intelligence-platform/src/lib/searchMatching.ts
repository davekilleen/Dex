import type { SupabaseClient } from "@supabase/supabase-js";
import { scoreListingAgainstSearch, type ListingCandidate } from "@/lib/matching";

/**
 * Server-side helper shared by the /api/searches/[id]/refresh route and the
 * /searches/[id] results page, so both trigger the same scoring logic
 * without one having to self-fetch the other over HTTP.
 */
export async function refreshSearchMatches(supabase: SupabaseClient, searchId: string) {
  const { data: search, error: searchError } = await supabase
    .from("searches")
    .select("*")
    .eq("id", searchId)
    .single();

  if (searchError || !search) {
    throw new Error(searchError?.message ?? "Search not found");
  }

  let listingsQuery = supabase.from("listings").select("*").eq("is_active", true);
  if (search.machine_type_id) {
    listingsQuery = listingsQuery.eq("machine_type_id", search.machine_type_id);
  }
  const { data: listings, error: listingsError } = await listingsQuery;
  if (listingsError) throw new Error(listingsError.message);

  const [{ data: manufacturers }, { data: options }] = await Promise.all([
    supabase.from("manufacturers").select("name, is_mam_represented"),
    supabase.from("listing_options").select("listing_id, option_name"),
  ]);

  const mamBrandNames = new Set(
    (manufacturers ?? []).filter((m) => m.is_mam_represented).map((m) => m.name.toLowerCase())
  );
  const optionsByListing = new Map<string, string[]>();
  for (const opt of options ?? []) {
    const list = optionsByListing.get(opt.listing_id) ?? [];
    list.push(opt.option_name);
    optionsByListing.set(opt.listing_id, list);
  }

  const searchCriteria = {
    machineTypeId: search.machine_type_id,
    manufacturerPreference: search.manufacturer_preference,
    minYear: search.min_year,
    minWattage: search.min_wattage,
    tonnage: search.tonnage,
    bedLength: search.bed_length,
    axis: search.axis,
    location: search.location,
    budgetMax: search.budget_max,
    mustHaveOptions: search.must_have_options ?? [],
  };

  const scored = (listings ?? []).map((listing) => {
    const candidate: ListingCandidate = {
      machineTypeId: listing.machine_type_id,
      manufacturerRawText: listing.manufacturer_raw_text,
      isMamRepresented: mamBrandNames.has((listing.manufacturer_raw_text ?? "").toLowerCase()),
      year: listing.year,
      wattage: listing.wattage,
      tonnage: listing.tonnage,
      bedLength: listing.bed_length,
      axis: listing.axis,
      location: listing.location,
      askingPrice: Number(listing.asking_price),
      optionNames: optionsByListing.get(listing.id),
    };
    return { listing, result: scoreListingAgainstSearch(searchCriteria, candidate) };
  });

  const matchRows = scored
    .filter(({ result }) => !result.excluded)
    .map(({ listing, result }) => ({
      search_id: searchId,
      listing_id: listing.id,
      match_score: result.score,
      fit_rating: result.fitRating,
      ai_rationale: result.reasons.join("; ") || null,
    }));

  if (matchRows.length > 0) {
    const { error: upsertError } = await supabase
      .from("search_matches")
      .upsert(matchRows, { onConflict: "search_id,listing_id" });
    if (upsertError) throw new Error(upsertError.message);
  }

  return { search, matchedCount: matchRows.length, consideredCount: scored.length };
}
