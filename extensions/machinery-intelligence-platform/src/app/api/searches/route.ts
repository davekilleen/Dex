import { NextRequest, NextResponse } from "next/server";
import { getServerSupabaseClient } from "@/lib/supabaseClient";

interface SearchRequestBody {
  customerId?: string;
  machineTypeId?: string;
  manufacturerPreference?: string;
  model?: string;
  minYear?: number;
  minWattage?: number;
  tonnage?: number;
  bedLength?: number;
  axis?: number;
  location?: string;
  budgetMax?: number;
  mustHaveOptions?: string[];
  niceToHaveOptions?: string[];
  notes?: string;
  alertEnabled?: boolean;
}

/** Creates a saved customer search from the intake form. */
export async function POST(req: NextRequest) {
  const body = (await req.json()) as SearchRequestBody;

  const supabase = getServerSupabaseClient();
  const { data, error } = await supabase
    .from("searches")
    .insert({
      customer_id: body.customerId ?? null,
      machine_type_id: body.machineTypeId ?? null,
      manufacturer_preference: body.manufacturerPreference ?? null,
      model: body.model ?? null,
      min_year: body.minYear ?? null,
      min_wattage: body.minWattage ?? null,
      tonnage: body.tonnage ?? null,
      bed_length: body.bedLength ?? null,
      axis: body.axis ?? null,
      location: body.location ?? null,
      budget_max: body.budgetMax ?? null,
      must_have_options: body.mustHaveOptions ?? [],
      nice_to_have_options: body.niceToHaveOptions ?? [],
      notes: body.notes ?? null,
      alert_enabled: body.alertEnabled ?? false,
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ search: data });
}

export async function GET() {
  const supabase = getServerSupabaseClient();
  const { data, error } = await supabase
    .from("searches")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ searches: data });
}
