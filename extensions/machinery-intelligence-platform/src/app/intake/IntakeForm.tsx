"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMachineTypes } from "@/components/useMachineTypes";

export function IntakeForm() {
  const router = useRouter();
  const machineTypes = useMachineTypes();
  const [machineTypeId, setMachineTypeId] = useState("");
  const [model, setModel] = useState("");
  const [manufacturerPreference, setManufacturerPreference] = useState("");
  const [minYear, setMinYear] = useState<number | "">("");
  const [minWattage, setMinWattage] = useState<number | "">("");
  const [tonnage, setTonnage] = useState<number | "">("");
  const [bedLength, setBedLength] = useState<number | "">("");
  const [axis, setAxis] = useState<number | "">("");
  const [location, setLocation] = useState("Eastern PA");
  const [budgetMax, setBudgetMax] = useState<number | "">("");
  const [mustHave, setMustHave] = useState("");
  const [niceToHave, setNiceToHave] = useState("");
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("Saving…");
    const res = await fetch("/api/searches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        machineTypeId: machineTypeId || undefined,
        model,
        manufacturerPreference,
        minYear: minYear === "" ? undefined : minYear,
        minWattage: minWattage === "" ? undefined : minWattage,
        tonnage: tonnage === "" ? undefined : tonnage,
        bedLength: bedLength === "" ? undefined : bedLength,
        axis: axis === "" ? undefined : axis,
        location,
        budgetMax: budgetMax === "" ? undefined : budgetMax,
        mustHaveOptions: mustHave.split(",").map((s) => s.trim()).filter(Boolean),
        niceToHaveOptions: niceToHave.split(",").map((s) => s.trim()).filter(Boolean),
        notes,
      }),
    });
    if (!res.ok) {
      setStatus("Error saving search.");
      return;
    }
    const body = await res.json();
    router.push(`/searches/${body.search.id}`);
  }

  return (
    <form className="card" onSubmit={submit}>
      <h3>Customer Requirement Intake</h3>
      <div className="field-row">
        <div className="field">
          <label>Machine Type</label>
          <select value={machineTypeId} onChange={(e) => setMachineTypeId(e.target.value)}>
            <option value="">Any</option>
            {machineTypes.map((mt) => (
              <option key={mt.id} value={mt.id}>
                {mt.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Manufacturer Preference</label>
          <input value={manufacturerPreference} onChange={(e) => setManufacturerPreference(e.target.value)} />
        </div>
        <div className="field">
          <label>Model</label>
          <input value={model} onChange={(e) => setModel(e.target.value)} />
        </div>
      </div>
      <div className="field-row">
        <div className="field">
          <label>Min Year</label>
          <input type="number" value={minYear} onChange={(e) => setMinYear(e.target.value === "" ? "" : Number(e.target.value))} />
        </div>
        <div className="field">
          <label>Min Wattage</label>
          <input type="number" value={minWattage} onChange={(e) => setMinWattage(e.target.value === "" ? "" : Number(e.target.value))} />
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
          <label>Location</label>
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </div>
        <div className="field">
          <label>Budget (max)</label>
          <input type="number" value={budgetMax} onChange={(e) => setBudgetMax(e.target.value === "" ? "" : Number(e.target.value))} />
        </div>
      </div>
      <div className="field-row">
        <div className="field">
          <label>Must-Have Options (comma separated)</label>
          <input value={mustHave} onChange={(e) => setMustHave(e.target.value)} />
        </div>
        <div className="field">
          <label>Nice-to-Have Options (comma separated)</label>
          <input value={niceToHave} onChange={(e) => setNiceToHave(e.target.value)} />
        </div>
      </div>
      <div className="field-row">
        <div className="field">
          <label>Customer Notes</label>
          <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
      </div>
      <button type="submit">Save &amp; Search</button>
      {status && <p>{status}</p>}
    </form>
  );
}
