import { getServerSupabaseClient } from "@/lib/supabaseClient";

function money(n: number) {
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export default async function ListingsPage() {
  let listings: Record<string, unknown>[] = [];
  let configError: string | null = null;

  try {
    const supabase = getServerSupabaseClient();
    const { data } = await supabase
      .from("listings")
      .select("*")
      .eq("is_active", true)
      .order("created_at", { ascending: false });
    listings = data ?? [];
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

  return (
    <div className="card">
      <h2>Listings</h2>
      <p>
        <a href="/listings/new">+ Add a listing</a>
      </p>
      <table>
        <thead>
          <tr>
            <th>Manufacturer</th>
            <th>Model</th>
            <th>Year</th>
            <th>Asking Price</th>
            <th>Location</th>
          </tr>
        </thead>
        <tbody>
          {listings.map((l) => (
            <tr key={String(l.id)}>
              <td>
                <a href={`/listings/${l.id}`}>{String(l.manufacturer_raw_text ?? "—")}</a>
              </td>
              <td>{String(l.model_raw_text ?? "—")}</td>
              <td>{String(l.year ?? "—")}</td>
              <td>{money(Number(l.asking_price ?? 0))}</td>
              <td>{String(l.location ?? "—")}</td>
            </tr>
          ))}
          {listings.length === 0 && (
            <tr>
              <td colSpan={5}>No listings yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
