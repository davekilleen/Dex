import { getServerSupabaseClient } from "@/lib/supabaseClient";
import { refreshSearchMatches } from "@/lib/searchMatching";

const FIT_BADGE_CLASS: Record<string, string> = {
  strong: "badge-green",
  moderate: "badge-yellow",
  weak: "badge-orange",
};

function money(n: number) {
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export default async function SearchResultsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let configError: string | null = null;
  let search: Record<string, unknown> | null = null;
  let matches: Array<Record<string, any>> = [];

  try {
    const supabase = getServerSupabaseClient();
    const result = await refreshSearchMatches(supabase, id);
    search = result.search;

    const { data } = await supabase
      .from("search_matches")
      .select("*, listings(*)")
      .eq("search_id", id)
      .order("match_score", { ascending: false });
    matches = data ?? [];
  } catch (err) {
    configError = (err as Error).message;
  }

  if (configError) {
    return (
      <div className="card">
        <h3>Could not load search results</h3>
        <p>{configError}</p>
      </div>
    );
  }

  if (!search) {
    return (
      <div className="card">
        <h3>Search not found</h3>
      </div>
    );
  }

  return (
    <div>
      <div className="card">
        <h2>Customer Search Results</h2>
        <p>
          Manufacturer preference: {String(search.manufacturer_preference ?? "—")} · Min year:{" "}
          {String(search.min_year ?? "—")} · Budget: {String(search.budget_max ?? "—")} · Location:{" "}
          {String(search.location ?? "—")}
        </p>
        {search.notes ? <p>Notes: {String(search.notes)}</p> : null}
      </div>

      <div className="card">
        <h3>Matches ({matches.length})</h3>
        <table>
          <thead>
            <tr>
              <th>Fit</th>
              <th>Manufacturer</th>
              <th>Model</th>
              <th>Year</th>
              <th>Asking Price</th>
              <th>Why</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {matches.map((m) => (
              <tr key={m.id}>
                <td>
                  <span className={`badge ${FIT_BADGE_CLASS[m.fit_rating] ?? "badge-orange"}`}>
                    {m.fit_rating}
                  </span>
                </td>
                <td>{m.listings?.manufacturer_raw_text ?? "—"}</td>
                <td>{m.listings?.model_raw_text ?? "—"}</td>
                <td>{m.listings?.year ?? "—"}</td>
                <td>{money(Number(m.listings?.asking_price ?? 0))}</td>
                <td style={{ fontSize: 12, color: "#57606a" }}>{m.ai_rationale}</td>
                <td>
                  <a href={`/listings/${m.listing_id}`}>Price this deal →</a>
                </td>
              </tr>
            ))}
            {matches.length === 0 && (
              <tr>
                <td colSpan={7}>No matching listings yet — add some under Listings.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
