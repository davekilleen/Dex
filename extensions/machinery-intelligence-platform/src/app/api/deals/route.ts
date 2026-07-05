import { NextRequest, NextResponse } from "next/server";
import { getServerSupabaseClient } from "@/lib/supabaseClient";

interface DealRequestBody {
  listingId?: string;
  customerId?: string;
  salesforceOpportunityId?: string;
  status?: "open" | "won" | "lost";
  freightEstimate?: number;
  rigging_estimate?: number;
}

/**
 * Creates a deal record. Salesforce Opportunity sync (§11 of the architecture
 * doc) is a follow-up wired through the Salesforce MCP already used elsewhere
 * in this vault — this route just persists the salesforce_opportunity_id
 * once a rep has created/linked the Opportunity.
 */
export async function POST(req: NextRequest) {
  const body = (await req.json()) as DealRequestBody;

  const supabase = getServerSupabaseClient();
  const { data, error } = await supabase
    .from("deals")
    .insert({
      listing_id: body.listingId ?? null,
      customer_id: body.customerId ?? null,
      salesforce_opportunity_id: body.salesforceOpportunityId ?? null,
      status: body.status ?? "open",
      freight_estimate: body.freightEstimate ?? null,
      rigging_estimate: body.rigging_estimate ?? null,
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ deal: data });
}
