import { NextRequest, NextResponse } from "next/server";

/**
 * Plumbing only — deliberately not wired to real Salesforce OAuth.
 * Pushing a deal to Salesforce needs a connected-app client id/secret and
 * instance URL that only the account owner can provision (see README.md
 * "Not yet built"). This route exists so the UI has a stable place to call
 * once those credentials are configured, without silently faking the
 * integration in the meantime.
 */
export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return NextResponse.json(
    {
      error: "Salesforce push is not configured yet.",
      dealId: id,
      nextStep:
        "Add SALESFORCE_CLIENT_ID, SALESFORCE_CLIENT_SECRET, and SALESFORCE_INSTANCE_URL to .env.local, then implement the Opportunity create/update call here.",
    },
    { status: 501 }
  );
}
