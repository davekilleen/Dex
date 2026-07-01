import { getServerSupabaseClient } from "@/lib/supabaseClient";
import { PricingPanel } from "@/components/PricingPanel";

export default async function ListingDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let listing: Record<string, unknown> | null = null;
  let valuation: Record<string, unknown> | null = null;
  let configError: string | null = null;

  try {
    const supabase = getServerSupabaseClient();
    const { data: listingData } = await supabase
      .from("listings")
      .select("*")
      .eq("id", id)
      .single();
    listing = listingData;

    const { data: valuationData } = await supabase
      .from("valuations")
      .select("*")
      .eq("listing_id", id)
      .order("computed_at", { ascending: false })
      .limit(1)
      .maybeSingle();
    valuation = valuationData;
  } catch (err) {
    configError = (err as Error).message;
  }

  if (configError) {
    return (
      <div className="card">
        <h3>Supabase not configured</h3>
        <p>{configError}</p>
      </div>
    );
  }

  if (!listing) {
    return (
      <div className="card">
        <h3>Listing not found</h3>
      </div>
    );
  }

  const askingPrice = Number(listing.asking_price ?? 0);
  const fmvLow = Number(valuation?.fair_market_low ?? askingPrice * 0.95);
  const fmvHigh = Number(valuation?.fair_market_high ?? askingPrice * 1.05);
  const confidence = (valuation?.confidence as "high" | "medium" | "low") ?? "medium";

  return (
    <div>
      <div className="card">
        <h2>
          {String(listing.manufacturer_raw_text)} {String(listing.model_raw_text ?? "")}
        </h2>
        <p>
          Year: {String(listing.year ?? "—")} · Location: {String(listing.location ?? "—")} ·
          Condition: {String(listing.condition ?? "—")}
        </p>
        {!!listing.listing_url && (
          <p>
            <a href={String(listing.listing_url)} target="_blank" rel="noreferrer">
              View original listing ↗
            </a>
          </p>
        )}
      </div>

      <PricingPanel
        listingId={id}
        initialDealerAskingPrice={askingPrice}
        initialFmvLow={fmvLow}
        initialFmvHigh={fmvHigh}
        initialConfidence={confidence}
      />
    </div>
  );
}
