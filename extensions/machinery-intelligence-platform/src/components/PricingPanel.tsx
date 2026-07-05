"use client";

import { useMemo, useState } from "react";
import {
  calcNetCost,
  buildDealSummary,
  calcNegotiationRange,
  generatePricingScenarios,
  DEFAULT_MARGIN_BANDS,
  type DiscountType,
  type MarginBand,
} from "@/lib/pricing";
import { DealSummaryCard } from "@/components/DealSummaryCard";

const BADGE_CLASS: Record<string, string> = {
  green: "badge-green",
  teal: "badge-teal",
  yellow: "badge-yellow",
  orange: "badge-orange",
  red: "badge-red",
};

function money(n: number) {
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function pct(n: number) {
  return `${(n * 100).toFixed(1)}%`;
}

export interface PricingPanelProps {
  listingId: string;
  initialDealerAskingPrice: number;
  initialFmvLow: number;
  initialFmvHigh: number;
  initialConfidence?: "high" | "medium" | "low";
  marginBands?: MarginBand[];
}

export function PricingPanel({
  listingId,
  initialDealerAskingPrice,
  initialFmvLow,
  initialFmvHigh,
  initialConfidence = "medium",
  marginBands = DEFAULT_MARGIN_BANDS,
}: PricingPanelProps) {
  const [dealerAskingPrice, setDealerAskingPrice] = useState(initialDealerAskingPrice);
  const [discountType, setDiscountType] = useState<DiscountType>("percent");
  const [discountValue, setDiscountValue] = useState(10);
  const [netCostOverride, setNetCostOverride] = useState<number | null>(null);
  const [fmvLow, setFmvLow] = useState(initialFmvLow);
  const [fmvHigh, setFmvHigh] = useState(initialFmvHigh);
  const [confidence] = useState(initialConfidence);
  const [quotePrice, setQuotePrice] = useState(
    Math.round((initialFmvLow + initialFmvHigh) / 2)
  );
  const [increment, setIncrement] = useState(2500);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const acquisition = { dealerAskingPrice, discountType, discountValue, netCostOverride };
  const netCost = useMemo(() => calcNetCost(acquisition), [
    dealerAskingPrice,
    discountType,
    discountValue,
    netCostOverride,
  ]);

  const summary = useMemo(
    () => buildDealSummary(acquisition, quotePrice, fmvLow, fmvHigh, marginBands),
    [dealerAskingPrice, discountType, discountValue, netCostOverride, quotePrice, fmvLow, fmvHigh, marginBands]
  );

  const negotiation = useMemo(
    () => calcNegotiationRange(netCost, fmvLow, fmvHigh),
    [netCost, fmvLow, fmvHigh]
  );

  const scenarios = useMemo(
    () => generatePricingScenarios(netCost, quotePrice, increment, 2),
    [netCost, quotePrice, increment]
  );

  async function savePricingSnapshot() {
    setSaving(true);
    try {
      const res = await fetch("/api/pricing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          listingId,
          dealerAskingPrice,
          discountType,
          discountValue,
          netCostOverride,
          quotePrice,
          fmvLow,
          fmvHigh,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setSavedAt(new Date().toLocaleTimeString());
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="card">
        <h3>Machine Value</h3>
        <div className="field-row">
          <div className="field">
            <label>Dealer Asking Price</label>
            <input
              type="number"
              value={dealerAskingPrice}
              onChange={(e) => setDealerAskingPrice(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label>Fair Market Value — Low</label>
            <input type="number" value={fmvLow} onChange={(e) => setFmvLow(Number(e.target.value))} />
          </div>
          <div className="field">
            <label>Fair Market Value — High</label>
            <input type="number" value={fmvHigh} onChange={(e) => setFmvHigh(Number(e.target.value))} />
          </div>
          <div className="field">
            <label>Confidence Rating</label>
            <input value={confidence} disabled />
          </div>
          <div className="field">
            <label>Expected Selling Price</label>
            <input
              type="number"
              value={quotePrice}
              onChange={(e) => setQuotePrice(Number(e.target.value))}
            />
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Acquisition</h3>
        <div className="field-row">
          <div className="field">
            <label>Dealer Discount Type</label>
            <select value={discountType} onChange={(e) => setDiscountType(e.target.value as DiscountType)}>
              <option value="percent">Percent</option>
              <option value="fixed">Fixed $</option>
            </select>
          </div>
          <div className="field">
            <label>Dealer Discount Value</label>
            <input
              type="number"
              value={discountValue}
              onChange={(e) => setDiscountValue(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label>Net Cost (auto)</label>
            <input value={money(netCost)} disabled />
          </div>
          <div className="field">
            <label>Override Net Cost</label>
            <input
              type="number"
              value={netCostOverride ?? ""}
              placeholder="optional"
              onChange={(e) =>
                setNetCostOverride(e.target.value === "" ? null : Number(e.target.value))
              }
            />
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Sales</h3>
        <div className="field-row">
          <div className="field">
            <label>Customer Quote Price</label>
            <input
              type="number"
              value={quotePrice}
              onChange={(e) => setQuotePrice(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label>Gross Profit</label>
            <input value={money(summary.grossProfit)} disabled />
          </div>
          <div className="field">
            <label>Gross Margin</label>
            <input value={pct(summary.grossMarginPct)} disabled />
          </div>
          <div className="field">
            <label>Markup</label>
            <input value={pct(summary.markupPct)} disabled />
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Quick Pricing Scenarios</h3>
        <div className="field-row" style={{ maxWidth: 240 }}>
          <div className="field">
            <label>Increment</label>
            <select value={increment} onChange={(e) => setIncrement(Number(e.target.value))}>
              <option value={1000}>$1,000</option>
              <option value={2500}>$2,500</option>
              <option value={5000}>$5,000</option>
              <option value={10000}>$10,000</option>
            </select>
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Quote Price</th>
              <th>Profit</th>
              <th>Margin</th>
              <th>Markup</th>
            </tr>
          </thead>
          <tbody>
            {scenarios.map((row) => (
              <tr key={row.quotePrice}>
                <td>{money(row.quotePrice)}</td>
                <td>{money(row.grossProfit)}</td>
                <td>{pct(row.grossMarginPct)}</td>
                <td>{pct(row.markupPct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Pricing Indicators</h3>
        <p>
          Against Dealer Asking: <strong>{summary.askingIndicator.comparison}</strong> (
          {money(Math.abs(summary.askingIndicator.delta))} {summary.askingIndicator.delta >= 0 ? "above" : "below"})
        </p>
        <p>
          Against Fair Market Value: <strong>{summary.marketIndicator.comparison}</strong> (
          {money(Math.abs(summary.marketIndicator.deltaFromPoint))}{" "}
          {summary.marketIndicator.deltaFromPoint >= 0 ? "above" : "below"} estimated market value)
        </p>
        <p>
          Profitability:{" "}
          <span className={`badge ${BADGE_CLASS[summary.profitability.color]}`}>
            {summary.profitability.label}
          </span>
        </p>
        <p>
          Competitiveness: <strong>{summary.competitiveness}</strong>
        </p>
      </div>

      <div className="card">
        <h3>Negotiation Assistant</h3>
        <div className="field-row">
          <div className="field">
            <label>Ideal Quote Price</label>
            <input value={money(negotiation.idealQuotePrice)} disabled />
          </div>
          <div className="field">
            <label>Target Selling Price</label>
            <input value={money(negotiation.targetSellingPrice)} disabled />
          </div>
          <div className="field">
            <label>Lowest Acceptable Price</label>
            <input value={money(negotiation.lowestAcceptablePrice)} disabled />
          </div>
        </div>
      </div>

      <DealSummaryCard summary={summary} />

      <button onClick={savePricingSnapshot} disabled={saving}>
        {saving ? "Saving…" : "Save Pricing Snapshot"}
      </button>
      {savedAt && <span style={{ marginLeft: 12, color: "#57606a" }}>Saved at {savedAt}</span>}
    </div>
  );
}
