/**
 * Pricing & Profitability Engine
 *
 * Pure, framework-free functions so the same logic can run client-side
 * (live recompute while a rep is on the phone) and server-side (persisting
 * a pricing_snapshots row). No I/O in this file on purpose.
 */

export type DiscountType = "percent" | "fixed";

export interface AcquisitionInput {
  dealerAskingPrice: number;
  discountType: DiscountType;
  discountValue: number; // percent as 0-100, or a fixed dollar amount
  netCostOverride?: number | null;
}

export interface MarginBand {
  minMarginPct: number; // inclusive lower bound, 0-1 scale
  maxMarginPct: number | null; // exclusive upper bound, null = no ceiling
  label: string;
  color: string;
}

export const DEFAULT_MARGIN_BANDS: MarginBand[] = [
  { minMarginPct: 0.20, maxMarginPct: null, label: "Excellent", color: "green" },
  { minMarginPct: 0.15, maxMarginPct: 0.20, label: "Very Good", color: "teal" },
  { minMarginPct: 0.10, maxMarginPct: 0.15, label: "Good", color: "yellow" },
  { minMarginPct: 0.07, maxMarginPct: 0.10, label: "Thin", color: "orange" },
  { minMarginPct: -Infinity, maxMarginPct: 0.07, label: "Low Margin", color: "red" },
];

export const DEFAULT_TARGET_MARGIN_PCT = 0.20;
export const DEFAULT_NEGOTIABLE_MARGIN_PCT = 0.15;
export const DEFAULT_FLOOR_MARGIN_PCT = 0.10;

/** Net Cost = Dealer Asking Price - Dealer Discount. Override wins if set. */
export function calcNetCost(input: AcquisitionInput): number {
  if (input.netCostOverride != null) return input.netCostOverride;

  const discount =
    input.discountType === "percent"
      ? input.dealerAskingPrice * (input.discountValue / 100)
      : input.discountValue;

  return input.dealerAskingPrice - discount;
}

export interface SalesFigures {
  quotePrice: number;
  netCost: number;
  grossProfit: number;
  grossMarginPct: number; // 0-1 scale
  markupPct: number; // 0-1 scale
}

/**
 * Gross Profit = Quote Price - Net Cost
 * Gross Margin = Gross Profit / Quote Price
 * Markup       = Gross Profit / Net Cost
 */
export function calcSalesFigures(quotePrice: number, netCost: number): SalesFigures {
  const grossProfit = quotePrice - netCost;
  const grossMarginPct = quotePrice !== 0 ? grossProfit / quotePrice : 0;
  const markupPct = netCost !== 0 ? grossProfit / netCost : 0;
  return { quotePrice, netCost, grossProfit, grossMarginPct, markupPct };
}

export interface PricingScenarioRow extends SalesFigures {}

/**
 * Generates the Quick Pricing Scenarios table: steps the quote price up/down
 * from a center price by `increment`, holding net cost fixed.
 */
export function generatePricingScenarios(
  netCost: number,
  centerQuotePrice: number,
  increment: number,
  stepsEachSide = 2
): PricingScenarioRow[] {
  if (increment <= 0) throw new Error("increment must be > 0");
  const rows: PricingScenarioRow[] = [];
  for (let step = -stepsEachSide; step <= stepsEachSide; step++) {
    const quotePrice = centerQuotePrice + step * increment;
    rows.push(calcSalesFigures(quotePrice, netCost));
  }
  return rows;
}

export type AskingComparison = "above" | "at" | "below";

export interface AskingIndicator {
  comparison: AskingComparison;
  delta: number; // quotePrice - dealerAskingPrice; sign preserved
}

/** Compares the quote price to dealer asking price. `at` uses a small tolerance. */
export function compareToDealerAsking(
  quotePrice: number,
  dealerAskingPrice: number,
  tolerance = 0.005
): AskingIndicator {
  const delta = quotePrice - dealerAskingPrice;
  const relativeTolerance = Math.abs(dealerAskingPrice) * tolerance;
  if (Math.abs(delta) <= relativeTolerance) return { comparison: "at", delta };
  return { comparison: delta > 0 ? "above" : "below", delta };
}

export type MarketComparison = "above" | "at" | "below";

export interface MarketIndicator {
  comparison: MarketComparison;
  deltaFromPoint: number; // quotePrice - fmvPoint
}

/** Compares the quote price to the fair market value band. */
export function compareToFairMarketValue(
  quotePrice: number,
  fmvLow: number,
  fmvHigh: number
): MarketIndicator {
  const fmvPoint = (fmvLow + fmvHigh) / 2;
  const deltaFromPoint = quotePrice - fmvPoint;
  if (quotePrice < fmvLow) return { comparison: "below", deltaFromPoint };
  if (quotePrice > fmvHigh) return { comparison: "above", deltaFromPoint };
  return { comparison: "at", deltaFromPoint };
}

/** Classifies a margin against the configured bands (defaults to DEFAULT_MARGIN_BANDS). */
export function rateProfitability(
  grossMarginPct: number,
  bands: MarginBand[] = DEFAULT_MARGIN_BANDS
): MarginBand {
  for (const band of bands) {
    const belowCeiling = band.maxMarginPct == null || grossMarginPct < band.maxMarginPct;
    if (grossMarginPct >= band.minMarginPct && belowCeiling) return band;
  }
  return bands[bands.length - 1];
}

export type Competitiveness = "aggressive" | "competitive" | "market" | "premium";

/**
 * Rates the dealer asking price's competitiveness against the fair market
 * value band (not the quote price — this describes the acquisition, not the sale).
 */
export function rateCompetitiveness(
  dealerAskingPrice: number,
  fmvLow: number,
  fmvHigh: number
): Competitiveness {
  const fmvPoint = (fmvLow + fmvHigh) / 2;
  const bandWidth = fmvHigh - fmvLow;
  const aggressiveThreshold = fmvLow - bandWidth * 0.5;

  if (dealerAskingPrice < aggressiveThreshold) return "aggressive";
  if (dealerAskingPrice < fmvPoint) return "competitive";
  if (dealerAskingPrice <= fmvHigh) return "market";
  return "premium";
}

export interface NegotiationRange {
  idealQuotePrice: number;
  targetSellingPrice: number;
  lowestAcceptablePrice: number;
}

/**
 * Ideal Quote Price: priced near the top of the FMV band at/above target margin.
 * Target Selling Price: realistic close point — FMV midpoint, floored at the negotiable margin.
 * Lowest Acceptable Price: Net Cost / (1 - floorMarginPct) — the price at which margin hits the floor.
 */
export function calcNegotiationRange(
  netCost: number,
  fmvLow: number,
  fmvHigh: number,
  targetMarginPct = DEFAULT_TARGET_MARGIN_PCT,
  negotiableMarginPct = DEFAULT_NEGOTIABLE_MARGIN_PCT,
  floorMarginPct = DEFAULT_FLOOR_MARGIN_PCT
): NegotiationRange {
  const priceForTargetMargin = netCost / (1 - targetMarginPct);
  const priceForNegotiableMargin = netCost / (1 - negotiableMarginPct);
  const lowestAcceptablePrice = netCost / (1 - floorMarginPct);

  const idealQuotePrice = Math.max(fmvHigh, priceForTargetMargin);

  const fmvPoint = (fmvLow + fmvHigh) / 2;
  const targetSellingPrice = Math.max(fmvPoint, priceForNegotiableMargin);

  return { idealQuotePrice, targetSellingPrice, lowestAcceptablePrice };
}

export interface DealSummary {
  dealerAskingPrice: number;
  dealerDiscountDisplay: string;
  netCost: number;
  fmvLow: number;
  fmvHigh: number;
  quotePrice: number;
  grossProfit: number;
  grossMarginPct: number;
  markupPct: number;
  askingIndicator: AskingIndicator;
  marketIndicator: MarketIndicator;
  profitability: MarginBand;
  competitiveness: Competitiveness;
}

export function buildDealSummary(
  acquisition: AcquisitionInput,
  quotePrice: number,
  fmvLow: number,
  fmvHigh: number,
  marginBands: MarginBand[] = DEFAULT_MARGIN_BANDS
): DealSummary {
  const netCost = calcNetCost(acquisition);
  const sales = calcSalesFigures(quotePrice, netCost);
  const dealerDiscountDisplay =
    acquisition.discountType === "percent"
      ? `${acquisition.discountValue}%`
      : `$${acquisition.discountValue.toLocaleString()}`;

  return {
    dealerAskingPrice: acquisition.dealerAskingPrice,
    dealerDiscountDisplay,
    netCost,
    fmvLow,
    fmvHigh,
    quotePrice,
    grossProfit: sales.grossProfit,
    grossMarginPct: sales.grossMarginPct,
    markupPct: sales.markupPct,
    askingIndicator: compareToDealerAsking(quotePrice, acquisition.dealerAskingPrice),
    marketIndicator: compareToFairMarketValue(quotePrice, fmvLow, fmvHigh),
    profitability: rateProfitability(sales.grossMarginPct, marginBands),
    competitiveness: rateCompetitiveness(acquisition.dealerAskingPrice, fmvLow, fmvHigh),
  };
}
