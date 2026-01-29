# Career MCP Server

## Overview

The Career MCP Server provides deterministic data aggregation for career development, making the `/career-coach` command faster, more consistent, and trackable over time.

## What It Does

**Core Philosophy:** MCP handles data aggregation → LLM interprets and coaches

Instead of having the LLM read and parse 20+ evidence files every assessment, the MCP server:
- Scans and structures evidence files systematically
- Parses career ladder into competency requirements
- Maps evidence to competencies with coverage statistics
- Tracks evidence trends over time

## Architecture

```
core/mcp/
├── career_server.py          # Main MCP server with 4 tools
├── career_parser.py           # Parsing utilities (dates, markdown, matching)
└── test_career_parser.py      # Test suite
```

## The 4 Tools

### 1. `scan_evidence()`
**Purpose:** Aggregate all career evidence files with structured parsing

**Example:**
```json
{
  "date_range": "last-6-months",
  "category": "Achievements"
}
```

**Returns:**
- Total file counts by category and date
- Parsed evidence with extracted fields (skills, impact, ladder alignment)
- Last modified timestamps

### 2. `parse_ladder()`
**Purpose:** Parse career ladder into structured competency tree

**Returns:**
- Current and target levels
- List of competencies with requirements
- Competency count

### 3. `analyze_coverage()`
**Purpose:** Map evidence to competencies and calculate coverage

**Example:**
```json
{
  "date_range": "last-12-months",
  "include_examples": true
}
```

**Returns:**
- Coverage by competency (strong/moderate/weak/none)
- Evidence counts per competency
- Under-documented vs well-documented areas
- Example files demonstrating each competency

### 4. `timeline_analysis()`
**Purpose:** Track evidence trends and growth velocity

**Example:**
```json
{
  "period": "last-12-months",
  "group_by": "quarter"
}
```

**Returns:**
- Evidence density by period
- Competency trends (increasing/stable/decreasing)
- Staleness flags (no evidence in 90+ days)
- Growth velocity (accelerating/stable/decelerating)

## How `/career-coach` Uses It

### Before (LLM-only):
1. Read 20+ evidence files individually (expensive, slow)
2. LLM synthesizes patterns (inconsistent results)
3. Generate assessment (varies each run)

### After (with MCP):
1. Call `scan_evidence()` → aggregated data in milliseconds
2. Call `parse_ladder()` → structured competency tree
3. Call `analyze_coverage()` → evidence-to-competency mapping
4. LLM interprets structured data → coaching insights (fast, consistent)

## Benefits

✅ **10x faster** - Evidence scanning without reading every file  
✅ **Consistent** - Same data → same baseline every time  
✅ **Trackable** - Compare coverage "June vs December"  
✅ **Complete** - Systematic discovery, nothing missed  
✅ **Flexible** - Handles template variations gracefully

## Configuration

Already added to `System/.mcp.json.example`:

```json
{
  "career-mcp": {
    "type": "stdio",
    "command": "python",
    "args": ["{{VAULT_PATH}}/core/mcp/career_server.py"],
    "env": {"VAULT_PATH": "{{VAULT_PATH}}"}
  }
}
```

## Testing

Run the test suite:
```bash
cd core/mcp
python test_career_parser.py
```

All tests should pass with ✓ markers.

## Data Flow Example

**User runs `/career-coach` → Promotion Assessment mode:**

```
1. MCP: scan_evidence()
   → Returns: "42 files, 8 in Q4, 15 in Q3..."

2. MCP: parse_ladder()
   → Returns: "8 competencies: Technical Depth, Product Strategy..."

3. MCP: analyze_coverage()
   → Returns: "Technical Depth: 2 examples (weak), Product Strategy: 8 examples (strong)..."

4. LLM receives structured data:
   "Based on your evidence:
    - Strong: Product Strategy (8 examples)
    - Weak: Technical Depth (only 2 examples)
    
    Let's explore ways to strengthen Technical Depth evidence..."
```

## What It Doesn't Do

❌ Score promotion readiness (LLM interprets)  
❌ Judge evidence quality (LLM coaches)  
❌ Make recommendations (LLM advises)  
❌ Predict timeline (too context-dependent)

The MCP provides **data**, the LLM provides **wisdom**.

## Template Compatibility

Works with career evidence templates:
- `System/Templates/Career_Evidence_Achievement.md`
- `System/Templates/Career_Evidence_Feedback.md`

Gracefully handles:
- Missing fields (uses defaults)
- Free-form content (extracts what it can)
- Non-standard formatting (falls back to filename/date)

## Future Enhancements

Potential additions (not yet implemented):
- LLM-powered semantic matching for ambiguous competencies
- Evidence quality metrics (requires subjective judgment)
- Automatic extraction from meeting notes
- Visual timeline charts

## Success Metrics

Track these to validate value:
- Speed: Evidence scanning <1 second vs previous 10+ seconds
- Consistency: Same data → identical coverage analysis
- Completeness: 100% evidence discovery vs potential misses
- Utility: User prefers MCP-powered assessments

---

**Built:** January 2026  
**Status:** Production-ready  
**Integration:** `/career-coach` command
