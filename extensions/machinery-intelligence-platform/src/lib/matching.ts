/**
 * Rule-based Matching Engine (MVP — no AI yet, see ARCHITECTURE.md §14)
 *
 * Pure functions, no I/O, mirroring the style of pricing.ts. Specs on a
 * customer search are treated as preferences with tolerance, not hard
 * filters, except machine type and must-have options — a rep still wants to
 * see a close-but-not-exact machine rather than nothing.
 */

export type FitRating = "strong" | "moderate" | "weak";

export interface SearchCriteria {
  machineTypeId?: string | null;
  manufacturerPreference?: string | null;
  minYear?: number | null;
  minWattage?: number | null;
  tonnage?: number | null;
  bedLength?: number | null;
  axis?: number | null;
  location?: string | null;
  budgetMax?: number | null;
  mustHaveOptions?: string[];
}

export interface ListingCandidate {
  machineTypeId?: string | null;
  manufacturerRawText?: string | null;
  isMamRepresented?: boolean;
  year?: number | null;
  wattage?: number | null;
  tonnage?: number | null;
  bedLength?: number | null;
  axis?: number | null;
  location?: string | null;
  askingPrice: number;
  optionNames?: string[];
}

export interface MatchResult {
  score: number; // 0-100
  fitRating: FitRating;
  reasons: string[];
  excluded: boolean;
  exclusionReason?: string;
}

const STRONG_THRESHOLD = 75;
const MODERATE_THRESHOLD = 45;

function fitRatingForScore(score: number): FitRating {
  if (score >= STRONG_THRESHOLD) return "strong";
  if (score >= MODERATE_THRESHOLD) return "moderate";
  return "weak";
}

function numericProximityScore(
  target: number | null | undefined,
  actual: number | null | undefined,
  tolerance: number
): number | null {
  if (target == null || actual == null) return null;
  if (actual >= target) return 1;
  const shortfall = (target - actual) / target;
  return Math.max(0, 1 - shortfall / tolerance);
}

/**
 * Scores one listing against one saved search. Hard exclusions: machine
 * type mismatch (when both are specified) and missing must-have options
 * (when the listing has option data at all). Everything else is weighted
 * partial credit so near-misses still surface, ranked lower.
 */
export function scoreListingAgainstSearch(
  search: SearchCriteria,
  listing: ListingCandidate
): MatchResult {
  if (
    search.machineTypeId &&
    listing.machineTypeId &&
    search.machineTypeId !== listing.machineTypeId
  ) {
    return {
      score: 0,
      fitRating: "weak",
      reasons: [],
      excluded: true,
      exclusionReason: "Machine type does not match",
    };
  }

  const mustHave = search.mustHaveOptions ?? [];
  if (mustHave.length > 0 && listing.optionNames) {
    const missing = mustHave.filter(
      (opt) => !listing.optionNames!.some((o) => o.toLowerCase() === opt.toLowerCase())
    );
    if (missing.length > 0) {
      return {
        score: 0,
        fitRating: "weak",
        reasons: [],
        excluded: true,
        exclusionReason: `Missing must-have option(s): ${missing.join(", ")}`,
      };
    }
  }

  const reasons: string[] = [];
  const weightedScores: number[] = [];

  // Manufacturer preference: partial credit, bonus for MAM-represented brands.
  if (search.manufacturerPreference && listing.manufacturerRawText) {
    const matches = listing.manufacturerRawText
      .toLowerCase()
      .includes(search.manufacturerPreference.toLowerCase());
    if (matches) {
      weightedScores.push(listing.isMamRepresented ? 1 : 0.85);
      reasons.push(`Manufacturer matches preference (${listing.manufacturerRawText})`);
    } else {
      weightedScores.push(0.2);
    }
  } else if (listing.isMamRepresented) {
    weightedScores.push(0.9);
    reasons.push("MAM-represented brand");
  }

  // Year: at/above min_year is full credit; below is tolerance-scaled.
  if (search.minYear != null && listing.year != null) {
    const yearsShort = search.minYear - listing.year;
    const yearScore = yearsShort <= 0 ? 1 : Math.max(0, 1 - yearsShort / 10);
    weightedScores.push(yearScore);
    if (yearScore === 1) reasons.push(`Year ${listing.year} meets minimum`);
  }

  const dims: Array<[number | null | undefined, number | null | undefined, string]> = [
    [search.minWattage, listing.wattage, "wattage"],
    [search.tonnage, listing.tonnage, "tonnage"],
    [search.bedLength, listing.bedLength, "bed length"],
    [search.axis, listing.axis, "axis"],
  ];
  for (const [target, actual, label] of dims) {
    const proximity = numericProximityScore(target, actual, 0.25);
    if (proximity != null) {
      weightedScores.push(proximity);
      if (proximity === 1) reasons.push(`${label} meets requirement`);
    }
  }

  // Budget: over-budget is a penalty, not an exclusion.
  if (search.budgetMax != null) {
    if (listing.askingPrice <= search.budgetMax) {
      weightedScores.push(1);
      reasons.push("Within budget");
    } else {
      const overBy = (listing.askingPrice - search.budgetMax) / search.budgetMax;
      weightedScores.push(Math.max(0, 1 - overBy / 0.15));
    }
  }

  // Location: simple substring match for MVP (no geodistance — V2 gap, see ARCHITECTURE.md).
  if (search.location && listing.location) {
    const matches = listing.location.toLowerCase().includes(search.location.toLowerCase());
    weightedScores.push(matches ? 1 : 0.4);
    if (matches) reasons.push(`Location matches (${listing.location})`);
  }

  const score =
    weightedScores.length === 0
      ? 50
      : Math.round((weightedScores.reduce((a, b) => a + b, 0) / weightedScores.length) * 100);

  return { score, fitRating: fitRatingForScore(score), reasons, excluded: false };
}
