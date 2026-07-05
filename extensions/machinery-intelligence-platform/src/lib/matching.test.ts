import { describe, it, expect } from "vitest";
import { scoreListingAgainstSearch, type SearchCriteria, type ListingCandidate } from "./matching";

const baseSearch: SearchCriteria = {
  machineTypeId: "press-brake",
  manufacturerPreference: "Baykal",
  minYear: 2015,
  tonnage: 66,
  bedLength: 6,
  axis: 6,
  location: "Eastern PA",
  budgetMax: 130000,
  mustHaveOptions: [],
};

const baseListing: ListingCandidate = {
  machineTypeId: "press-brake",
  manufacturerRawText: "Baykal",
  isMamRepresented: true,
  year: 2019,
  tonnage: 66,
  bedLength: 6,
  axis: 6,
  location: "Eastern PA",
  askingPrice: 120000,
  optionNames: ["Laser guard", "CNC backgauge"],
};

describe("scoreListingAgainstSearch", () => {
  it("scores a near-perfect match as strong", () => {
    const result = scoreListingAgainstSearch(baseSearch, baseListing);
    expect(result.excluded).toBe(false);
    expect(result.fitRating).toBe("strong");
    expect(result.score).toBeGreaterThanOrEqual(75);
  });

  it("excludes a mismatched machine type", () => {
    const result = scoreListingAgainstSearch(baseSearch, {
      ...baseListing,
      machineTypeId: "plasma-table",
    });
    expect(result.excluded).toBe(true);
    expect(result.exclusionReason).toMatch(/machine type/i);
    expect(result.score).toBe(0);
  });

  it("excludes a listing missing a must-have option", () => {
    const search: SearchCriteria = { ...baseSearch, mustHaveOptions: ["Laser guard", "Auto tool changer"] };
    const result = scoreListingAgainstSearch(search, baseListing);
    expect(result.excluded).toBe(true);
    expect(result.exclusionReason).toMatch(/Auto tool changer/);
  });

  it("does not exclude when listing has no option data at all", () => {
    const search: SearchCriteria = { ...baseSearch, mustHaveOptions: ["Auto tool changer"] };
    const result = scoreListingAgainstSearch(search, { ...baseListing, optionNames: undefined });
    expect(result.excluded).toBe(false);
  });

  it("penalizes but does not exclude an over-budget listing", () => {
    const overBudget = scoreListingAgainstSearch(baseSearch, { ...baseListing, askingPrice: 200000 });
    const withinBudget = scoreListingAgainstSearch(baseSearch, baseListing);
    expect(overBudget.excluded).toBe(false);
    expect(overBudget.score).toBeLessThan(withinBudget.score);
  });

  it("scores a listing missing several requirements as weak, not excluded", () => {
    const result = scoreListingAgainstSearch(baseSearch, {
      ...baseListing,
      manufacturerRawText: "Amada",
      isMamRepresented: false,
      year: 2005,
      tonnage: 40,
      bedLength: 4,
      location: "Texas",
      askingPrice: 250000,
    });
    expect(result.excluded).toBe(false);
    expect(result.fitRating).toBe("weak");
  });

  it("gives partial credit for a below-minimum year, scaled by shortfall", () => {
    const closeYear = scoreListingAgainstSearch(baseSearch, { ...baseListing, year: 2013 });
    const farYear = scoreListingAgainstSearch(baseSearch, { ...baseListing, year: 2000 });
    expect(closeYear.score).toBeGreaterThan(farYear.score);
  });
});
