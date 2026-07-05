import { NextRequest, NextResponse } from "next/server";
import { getServerSupabaseClient } from "@/lib/supabaseClient";
import {
  calcNetCost,
  buildDealSummary,
  calcNegotiationRange,
  type DiscountType,
} from "@/lib/pricing";

interface PricingRequestBody {
  listingId: string;
  dealId?: string;
  dealerAskingPrice: number;
  discountType: DiscountType;
  discountValue: number;
  netCostOverride?: number | null;
  quotePrice: number;
  fmvLow: number;
  fmvHigh: number;
}

/**
 * Creates a new pricing_snapshots row. Snapshots are append-only so a rep's
 * pricing history on a call isn't lost as numbers are adjusted live.
 */
export async function POST(req: NextRequest) {
  const body = (await req.json()) as PricingRequestBody;

  const acquisition = {
    dealerAskingPrice: body.dealerAskingPrice,
    discountType: body.discountType,
    discountValue: body.discountValue,
    netCostOverride: body.netCostOverride ?? null,
  };

  const netCost = calcNetCost(acquisition);
  const summary = buildDealSummary(acquisition, body.quotePrice, body.fmvLow, body.fmvHigh);
  const negotiation = calcNegotiationRange(netCost, body.fmvLow, body.fmvHigh);

  const supabase = getServerSupabaseClient();
  const { data, error } = await supabase
    .from("pricing_snapshots")
    .insert({
      listing_id: body.listingId,
      deal_id: body.dealId ?? null,
      dealer_asking_price: body.dealerAskingPrice,
      dealer_discount_pct: body.discountType === "percent" ? body.discountValue : null,
      dealer_discount_fixed: body.discountType === "fixed" ? body.discountValue : null,
      net_cost: netCost,
      net_cost_override: body.netCostOverride ?? null,
      quote_price: body.quotePrice,
      gross_profit: summary.grossProfit,
      gross_margin_pct: summary.grossMarginPct,
      markup_pct: summary.markupPct,
      ideal_quote_price: negotiation.idealQuotePrice,
      target_selling_price: negotiation.targetSellingPrice,
      walkaway_price: negotiation.lowestAcceptablePrice,
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ snapshot: data, summary, negotiation });
}
