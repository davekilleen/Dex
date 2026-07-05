"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMachineTypes } from "@/components/useMachineTypes";

export function NewListingForm() {
  const router = useRouter();
  const machineTypes = useMachineTypes();
  const [machineTypeId, setMachineTypeId] = useState("");
  const [manufacturerRawText, setManufacturerRawText] = useState("");
  const [modelRawText, setModelRawText] = useState("");
  const [listingUrl, setListingUrl] = useState("");
  const [year, setYear] = useState<number | "">("");
  const [tonnage, setTonnage] = useState<number | "">("");
  const [bedLength, setBedLength] = useState<number | "">("");
  const [axis, setAxis] = useState<number | "">("");
  const [condition, setCondition] = useState("");
  const [location, setLocation] = useState("Eastern PA");
  const [askingPrice, setAskingPrice] = useState<number | "">("");
  const [acquisitionType, setAcquisitionType] = useState<"dealer_inventory" | "direct_purchase">(
    "dealer_inventory"
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const res = await fetch("/api/listings/manual-capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        machineTypeId: machineTypeId || undefined,
        manufacturerRawText,
        modelRawText,
        listingUrl: listingUrl || undefined,
        year: year === "" ? undefined : year,
        tonnage: tonnage === "" ? undefined : tonnage,
        bedLength: bedLength === "" ? undefined : bedLength,
        axis: axis === "" ? undefined : axis,
        condition: condition || undefined,
        location,
        askingPrice,
        acquisitionType,
      }),
    });
    const body = await res.json();
    setSaving(false);
    if (!res.ok) {
      setError(body.error ?? "Error saving listing.");
      return;
    }
    router.push(`/listings/${body.listing.id}`);
  }

  return (
    <form className="card" onSubmit={submit}>
      <h3>Add a Listing</h3>
      <p style={{ color: "#57606a", fontSize: 13 }}>
        Manual entry — paste the source URL for reference. Automated scraping is not enabled for
        any marketplace yet (see ARCHITECTURE.md §5/§15).
      </p>
      <div className="field-row">
        <div className="field">
          <label>Machine Type</label>
          <select value={machineTypeId} onChange={(e) => setMachineTypeId(e.target.value)}>
            <option value="">Select…</option>
            {machineTypes.map((mt) => (
              <option key={mt.id} value={mt.id}>
                {mt.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Manufacturer</label>
          <input required value={manufacturerRawText} onChange={(e) => setManufacturerRawText(e.target.value)} />
        </div>
        <div className="field">
          <label>Model</label>
          <input value={modelRawText} onChange={(e) => setModelRawText(e.target.value)} />
        </div>
        <div className="field">
          <label>Source Listing URL</label>
          <input value={listingUrl} onChange={(e) => setListingUrl(e.target.value)} />
        </div>
      </div>
      <div className="field-row">
        <div className="field">
          <label>Year</label>
          <input type="number" value={year} onChange={(e) => setYear(e.target.value === "" ? "" : Number(e.target.value))} />
        </div>
        <div className="field">
          <label>Tonnage</label>
          <input type="number" value={tonnage} onChange={(e) => setTonnage(e.target.value === "" ? "" : Number(e.target.value))} />
        </div>
        <div className="field">
          <label>Bed Length</label>
          <input type="number" value={bedLength} onChange={(e) => setBedLength(e.target.value === "" ? "" : Number(e.target.value))} />
        </div>
        <div className="field">
          <label>Axis</label>
          <input type="number" value={axis} onChange={(e) => setAxis(e.target.value === "" ? "" : Number(e.target.value))} />
        </div>
      </div>
      <div className="field-row">
        <div className="field">
          <label>Condition</label>
          <input value={condition} onChange={(e) => setCondition(e.target.value)} />
        </div>
        <div className="field">
          <label>Location</label>
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </div>
        <div className="field">
          <label>Asking Price</label>
          <input
            type="number"
            required
            value={askingPrice}
            onChange={(e) => setAskingPrice(e.target.value === "" ? "" : Number(e.target.value))}
          />
        </div>
        <div className="field">
          <label>Acquisition Type</label>
          <select
            value={acquisitionType}
            onChange={(e) => setAcquisitionType(e.target.value as "dealer_inventory" | "direct_purchase")}
          >
            <option value="dealer_inventory">Dealer Inventory</option>
            <option value="direct_purchase">Direct Purchase</option>
          </select>
        </div>
      </div>
      <button type="submit" disabled={saving}>
        {saving ? "Saving…" : "Save Listing"}
      </button>
      {error && <p style={{ color: "#b91c1c" }}>{error}</p>}
    </form>
  );
}
