import type { DealSummary } from "@/lib/pricing";

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

/** Always-visible deal summary — matches the example layout in ARCHITECTURE.md §10. */
export function DealSummaryCard({ summary }: { summary: DealSummary }) {
  const sellingVsDealer =
    summary.askingIndicator.comparison === "at"
      ? "At Dealer Cost"
      : `${money(Math.abs(summary.askingIndicator.delta))} ${
          summary.askingIndicator.comparison === "above" ? "Above" : "Below"
        } Dealer Cost`;

  const sellingVsMarket =
    summary.marketIndicator.comparison === "at"
      ? "At Market Average"
      : `${money(Math.abs(summary.marketIndicator.deltaFromPoint))} ${
          summary.marketIndicator.comparison === "above" ? "Above" : "Below"
        } Market Average`;

  return (
    <div className="card">
      <h3>Deal Summary</h3>
      <table>
        <tbody>
          <tr>
            <td>Dealer Asking Price</td>
            <td>{money(summary.dealerAskingPrice)}</td>
          </tr>
          <tr>
            <td>Dealer Discount</td>
            <td>{summary.dealerDiscountDisplay}</td>
          </tr>
          <tr>
            <td>Net Cost</td>
            <td>{money(summary.netCost)}</td>
          </tr>
          <tr>
            <td>Fair Market Value</td>
            <td>
              {money(summary.fmvLow)} – {money(summary.fmvHigh)}
            </td>
          </tr>
          <tr>
            <td>Customer Quote</td>
            <td>{money(summary.quotePrice)}</td>
          </tr>
          <tr>
            <td>Gross Profit</td>
            <td>{money(summary.grossProfit)}</td>
          </tr>
          <tr>
            <td>Gross Margin</td>
            <td>{pct(summary.grossMarginPct)}</td>
          </tr>
          <tr>
            <td>Markup</td>
            <td>{pct(summary.markupPct)}</td>
          </tr>
          <tr>
            <td>Selling</td>
            <td>
              {sellingVsDealer}
              <br />
              {sellingVsMarket}
            </td>
          </tr>
          <tr>
            <td>Deal Rating</td>
            <td>
              <span className={`badge ${BADGE_CLASS[summary.profitability.color]}`}>
                {summary.profitability.label}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
