---
name: scrape
description: Scrape web pages using Scrapling MCP — stealth fetching, anti-bot bypass, CSS selectors. No API key needed.
---

# scrape

Extract data from any website using Scrapling's MCP tools. Bypasses Cloudflare, handles dynamic JS-rendered pages, supports CSS selectors to pre-filter content (saves tokens).

## Usage

```
/scrape <url>
/scrape <url> with selector .article-content
/scrape stealth <url>
/scrape bulk <url1> <url2> <url3>
```

## When to Use (Tool Selection)

| Scenario | Tool | Why |
|----------|------|-----|
| Simple page, no anti-bot | `scrapling_get` | Fastest. HTTP with browser TLS fingerprint |
| JS-rendered / SPA content | `scrapling_fetch` | Uses real Chromium browser |
| Cloudflare / anti-bot protected | `scrapling_stealthy_fetch` | Stealth mode, solves captchas |
| Multiple pages, same pattern | `scrapling_bulk_get` / `scrapling_bulk_fetch` | Parallel processing |

## Implementation

### Step 1: Parse User Intent

Determine from the user's request:
- **URL(s)** to scrape
- **CSS selector** (if specified — e.g., `.main-content`, `#article`, `table.data`)
- **Stealth needed?** (Cloudflare sites, login-protected, anti-bot mentions)
- **Bulk?** (multiple URLs)

### Step 2: Choose the Right Scrapling MCP Tool

**Default path (try in order, escalate on failure):**

1. Start with `scrapling_get` — fast HTTP, handles most sites
2. If content is empty/blocked → escalate to `scrapling_fetch` (real browser)
3. If still blocked → escalate to `scrapling_stealthy_fetch` (stealth mode)

**User explicitly asks for stealth:** Go straight to `scrapling_stealthy_fetch`

**Multiple URLs:** Use the `bulk_` variants for parallel processing

### Step 3: Call the MCP Tool

Use the Scrapling MCP server tools. All tools accept:
- `url` (required): The URL to scrape
- `css_selector` (optional): CSS selector to extract specific elements — **always use this when possible to reduce token consumption**

**Single page:**
```
Call scrapling MCP tool: get
Arguments: { "url": "<url>", "css_selector": "<selector if provided>" }
```

**Stealth:**
```
Call scrapling MCP tool: stealthy_fetch
Arguments: { "url": "<url>", "css_selector": "<selector if provided>" }
```

**Bulk:**
```
Call scrapling MCP tool: bulk_get
Arguments: { "urls": ["<url1>", "<url2>"], "css_selector": "<selector>" }
```

### Step 4: Process Results

The MCP returns extracted content (HTML or text depending on selector).

**If user wants raw data:** Present it formatted
**If user wants summary:** Summarize the extracted content
**If user wants vault storage:** Save to `00-Inbox/Scrape - [Title].md`:

```markdown
# [Page Title]

**Source:** [URL]
**Scraped:** YYYY-MM-DD
**Selector:** [CSS selector used, if any]

## Content

[Extracted content]
```

### Step 5: Handle Failures

| Error | Action |
|-------|--------|
| Empty content | Escalate to next fetcher tier |
| Connection refused | Check URL is valid |
| Cloudflare challenge | Auto-escalate to `stealthy_fetch` |
| Timeout | Retry with longer timeout, suggest `fetch` for slow JS sites |

## Smart Defaults

- **News/blog articles:** Auto-suggest `article, .post-content, .entry-content` selectors
- **Product pages:** Auto-suggest `.product, .price, .description` selectors  
- **Tables:** Auto-suggest `table` selector, offer to convert to markdown table
- **Lists:** Auto-suggest `ul, ol` selectors

## Examples

```
User: /scrape https://example.com/blog/ai-trends
→ Use scrapling_get, auto-detect article content

User: /scrape stealth https://protected-site.com/data
→ Use scrapling_stealthy_fetch with Cloudflare bypass

User: scrape this page and grab just the pricing table: https://saas.com/pricing
→ Use scrapling_get with css_selector="table" or ".pricing"

User: scrape these 5 competitor pages and compare their features
→ Use scrapling_bulk_get, extract feature lists, present comparison
```

## Prerequisites

Scrapling must be installed with MCP support:
```bash
pip install "scrapling[ai]"
scrapling install
```

The `scrapling` MCP server must be configured in `.mcp.json`.

## Relationship to Other Tools

- **WebFetch (native):** Basic URL fetch, no anti-bot, no selectors. Use for simple known-good pages.
- **Firecrawl MCP:** Cloud-based, requires API key, good for crawling entire sites. Use when you need recursive crawl.
- **Scrapling:** Local, free, stealthy, selector-based. **Default choice for single-page or small-batch scraping.**
- **Apify:** Marketplace of specialized scrapers. Use for platform-specific extraction (LinkedIn, Twitter, etc.)
