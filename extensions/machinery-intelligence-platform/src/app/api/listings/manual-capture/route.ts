import { NextRequest, NextResponse } from "next/server";
import { getServerSupabaseClient } from "@/lib/supabaseClient";

interface ManualCaptureBody {
  sourceId?: string;
  listingUrl?: string;
  manufacturerRawText: string;
  modelRawText?: string;
  machineModelId?: string;
  machineTypeId?: string;
  year?: number;
  wattage?: number;
  tonnage?: number;
  bedLength?: number;
  axis?: number;
  condition?: string;
  location?: string;
  askingPrice: number;
  acquisitionType?: "dealer_inventory" | "direct_purchase";
}

/**
 * MVP listing capture: a rep pastes one listing's URL and enters its specs by
 * hand. No automated fetching/scraping — see ARCHITECTURE.md §5 and §15
 * (scraping stays manual-only per source until each site's ToS is reviewed).
 */
export async function POST(req: NextRequest) {
  const body = (await req.json()) as ManualCaptureBody;

  if (!body.manufacturerRawText || !body.askingPrice) {
    return NextResponse.json(
      { error: "manufacturerRawText and askingPrice are required" },
      { status: 400 }
    );
  }

  const supabase = getServerSupabaseClient();
  const { data, error } = await supabase
    .from("listings")
    .insert({
      source_id: body.sourceId ?? null,
      machine_model_id: body.machineModelId ?? null,
      machine_type_id: body.machineTypeId ?? null,
      manufacturer_raw_text: body.manufacturerRawText,
      model_raw_text: body.modelRawText ?? null,
      year: body.year ?? null,
      wattage: body.wattage ?? null,
      tonnage: body.tonnage ?? null,
      bed_length: body.bedLength ?? null,
      axis: body.axis ?? null,
      condition: body.condition ?? null,
      location: body.location ?? null,
      asking_price: body.askingPrice,
      listing_url: body.listingUrl ?? null,
      acquisition_type: body.acquisitionType ?? "dealer_inventory",
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  await supabase.from("listing_price_history").insert({
    listing_id: data.id,
    price: body.askingPrice,
  });

  return NextResponse.json({ listing: data });
}
