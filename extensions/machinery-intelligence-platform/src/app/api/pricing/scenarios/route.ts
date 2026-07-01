import { NextRequest, NextResponse } from "next/server";
import { generatePricingScenarios } from "@/lib/pricing";

/**
 * GET /api/pricing/scenarios?netCost=108000&centerQuotePrice=125000&increment=2500
 * Pure computation, no persistence — used to render the Quick Pricing Scenarios table.
 */
export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const netCost = Number(params.get("netCost"));
  const centerQuotePrice = Number(params.get("centerQuotePrice"));
  const increment = Number(params.get("increment") ?? 2500);
  const stepsEachSide = Number(params.get("stepsEachSide") ?? 2);

  if (!Number.isFinite(netCost) || !Number.isFinite(centerQuotePrice)) {
    return NextResponse.json(
      { error: "netCost and centerQuotePrice are required numeric query params" },
      { status: 400 }
    );
  }

  try {
    const rows = generatePricingScenarios(netCost, centerQuotePrice, increment, stepsEachSide);
    return NextResponse.json({ rows });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 400 });
  }
}
