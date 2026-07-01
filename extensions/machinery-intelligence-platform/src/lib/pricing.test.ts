import { describe, it, expect } from "vitest";
import {
  calcNetCost,
  calcSalesFigures,
  generatePricingScenarios,
  compareToDealerAsking,
  compareToFairMarketValue,
  rateProfitability,
  rateCompetitiveness,
  calcNegotiationRange,
  buildDealSummary,
  DEFAULT_MARGIN_BANDS,
} from "./pricing";

describe("calcNetCost", () => {
  it("applies a percent discount", () => {
    expect(
      calcNetCost({ dealerAskingPrice: 120000, discountType: "percent", discountValue: 10 })
    ).toBe(108000);
  });

  it("applies a fixed discount", () => {
    expect(
      calcNetCost({ dealerAskingPrice: 120000, discountType: "fixed", discountValue: 12000 })
    ).toBe(108000);
  });

  it("prefers the override when set", () => {
    expect(
      calcNetCost({
        dealerAskingPrice: 120000,
        discountType: "percent",
        discountValue: 10,
        netCostOverride: 100000,
      })
    ).toBe(100000);
  });
});

describe("calcSalesFigures", () => {
  it("matches the worked example from the spec (Net Cost $108,000, Quote $124,500)", () => {
    const result = calcSalesFigures(124500, 108000);
    expect(result.grossProfit).toBe(16500);
    expect(result.grossMarginPct).toBeCloseTo(16500 / 124500, 10);
    expect(result.markupPct).toBeCloseTo(16500 / 108000, 10);
  });
});

describe("generatePricingScenarios", () => {
  it("reproduces the example Quick Pricing Scenarios table", () => {
    // Net cost implied by the $125,000 row: 13.6% margin -> profit = 125000*0.136 = 17000
    const netCost = 125000 - 17000;
    const rows = generatePricingScenarios(netCost, 125000, 2500, 2);

    expect(rows.map((r) => r.quotePrice)).toEqual([120000, 122500, 125000, 127500, 130000]);

    const expectedProfits = [12000, 14500, 17000, 19500, 22000];
    rows.forEach((row, i) => {
      expect(row.grossProfit).toBe(expectedProfits[i]);
    });

    expect(rows[0].grossMarginPct * 100).toBeCloseTo(10.0, 1);
    expect(rows[4].grossMarginPct * 100).toBeCloseTo(16.9, 1);
  });

  it("throws on non-positive increment", () => {
    expect(() => generatePricingScenarios(100000, 120000, 0)).toThrow();
  });
});

describe("compareToDealerAsking", () => {
  it("flags below with correct delta", () => {
    const result = compareToDealerAsking(112500, 120000);
    expect(result.comparison).toBe("below");
    expect(result.delta).toBe(-7500);
  });

  it("flags above", () => {
    const result = compareToDealerAsking(124500, 120000);
    expect(result.comparison).toBe("above");
    expect(result.delta).toBe(4500);
  });

  it("flags at within tolerance", () => {
    const result = compareToDealerAsking(120000, 120000);
    expect(result.comparison).toBe("at");
  });
});

describe("compareToFairMarketValue", () => {
  it("flags below market", () => {
    const result = compareToFairMarketValue(110000, 118000, 126000);
    expect(result.comparison).toBe("below");
  });

  it("flags at market and computes delta from midpoint", () => {
    const result = compareToFairMarketValue(124500, 118000, 126000);
    expect(result.comparison).toBe("at");
    expect(result.deltaFromPoint).toBe(124500 - 122000);
  });

  it("flags above market", () => {
    const result = compareToFairMarketValue(130000, 118000, 126000);
    expect(result.comparison).toBe("above");
  });
});

describe("rateProfitability", () => {
  it.each([
    [0.25, "Excellent"],
    [0.20, "Excellent"],
    [0.18, "Very Good"],
    [0.15, "Very Good"],
    [0.12, "Good"],
    [0.10, "Good"],
    [0.08, "Thin"],
    [0.07, "Thin"],
    [0.05, "Low Margin"],
    [-0.1, "Low Margin"],
  ])("rates margin %f as %s", (margin, label) => {
    expect(rateProfitability(margin, DEFAULT_MARGIN_BANDS).label).toBe(label);
  });

  it("matches the worked example (13.3% margin -> Very Good... wait Good boundary)", () => {
    // 13.3% falls in the 10-15% "Good" band per the default table.
    expect(rateProfitability(0.133).label).toBe("Good");
  });
});

describe("rateCompetitiveness", () => {
  const fmvLow = 118000;
  const fmvHigh = 126000;

  it("rates well below FMV band as aggressive", () => {
    expect(rateCompetitiveness(95000, fmvLow, fmvHigh)).toBe("aggressive");
  });

  it("rates below midpoint but within reach as competitive", () => {
    expect(rateCompetitiveness(120000, fmvLow, fmvHigh)).toBe("competitive");
  });

  it("rates within band above midpoint as market", () => {
    expect(rateCompetitiveness(124000, fmvLow, fmvHigh)).toBe("market");
  });

  it("rates above the band as premium", () => {
    expect(rateCompetitiveness(130000, fmvLow, fmvHigh)).toBe("premium");
  });
});

describe("calcNegotiationRange", () => {
  it("computes ideal/target/walkaway consistently with margin targets", () => {
    const netCost = 108000;
    const range = calcNegotiationRange(netCost, 118000, 126000);

    // Lowest acceptable price should be the price at exactly the 10% floor margin.
    const { grossMarginPct } = calcSalesFigures(range.lowestAcceptablePrice, netCost);
    expect(grossMarginPct).toBeCloseTo(0.10, 5);

    // Ideal quote should be at least the FMV high and at least the target-margin price.
    expect(range.idealQuotePrice).toBeGreaterThanOrEqual(126000);
    const { grossMarginPct: idealMargin } = calcSalesFigures(range.idealQuotePrice, netCost);
    expect(idealMargin).toBeGreaterThanOrEqual(0.20 - 1e-9);

    // Ordering: lowest acceptable <= target <= ideal
    expect(range.lowestAcceptablePrice).toBeLessThanOrEqual(range.targetSellingPrice);
    expect(range.targetSellingPrice).toBeLessThanOrEqual(range.idealQuotePrice);
  });
});

describe("buildDealSummary", () => {
  it("matches the worked example from the spec end-to-end", () => {
    const summary = buildDealSummary(
      { dealerAskingPrice: 120000, discountType: "percent", discountValue: 10 },
      124500,
      118000,
      126000
    );

    expect(summary.netCost).toBe(108000);
    expect(summary.grossProfit).toBe(16500);
    expect(summary.grossMarginPct * 100).toBeCloseTo(13.3, 1);
    expect(summary.markupPct * 100).toBeCloseTo(15.3, 1);
    expect(summary.askingIndicator.comparison).toBe("above");
    expect(summary.askingIndicator.delta).toBe(4500);
    expect(summary.marketIndicator.comparison).toBe("at");
    expect(summary.profitability.label).toBe("Good");
  });
});
