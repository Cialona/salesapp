# Trade Fair Discovery

An **agentic-first** tool for discovering exhibitor information from trade fair websites. Unlike traditional scrapers that crawl broadly, this tool behaves like a human agent: it strategically searches, navigates, downloads PDFs, and extracts the exact information needed.

## Why Agentic-First?

Trade fair websites are wildly inconsistent. Critical information (exhibitor manuals, schedules, regulations) is often hidden in download centers or buried in PDFs. A broad crawling approach fails because:

1. **Download Center Blind Spot** - Many sites keep everything in PDF downloads, not HTML pages
2. **False Positives** - Link text patterns often mislead without actual content verification
3. **Foreign Fair Contamination** - Third-party platforms mix content from different fairs

This tool solves these problems by:
- **Targeted navigation** - Search → Entry → Downloads → PDF Parse → Select
- **PDF-first approach** - Downloads and parses PDFs to extract schedules
- **Evidence-based scoring** - Only claims "strong" quality with verified content snippets
- **Domain guard** - Prevents contamination from other fairs

## What It Finds

For each trade fair, the tool discovers:

| Field | Description |
|-------|-------------|
| `floorplan_url` | Hall plan / venue layout |
| `exhibitor_manual_url` | Exhibitor handbook (PDF) |
| `rules_url` | Technical guidelines / regulations |
| `schedule` | Build-up and tear-down dates/times |
| `exhibitor_directory_url` | Exhibitor list / search |

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd trade-fair-discovery

# Install dependencies
pnpm install

# Install Playwright browsers
pnpm exec playwright install chromium
```

## Usage

### Single Fair Discovery

```bash
# Basic usage with known URL
pnpm discover --name "Fruit Logistica" --url https://www.fruitlogistica.com

# Search for official site
pnpm discover --name "Ambiente" --city "Frankfurt" --country "Germany"

# Save outputs
pnpm discover --name "ISE" --url https://www.iseurope.org \
  --output outputs/ise.json \
  --report reports/ise.md

# Output JSON to stdout
pnpm discover --name "bauma" --json
```

### Run Regression Tests

```bash
# Run all 10 testcases
pnpm regression

# Run specific test
pnpm regression fruit-logistica-2025
```

### Output Locations

After running:
- `outputs/<id>.json` - Full JSON output per testcase
- `reports/<id>.md` - Human-readable report per testcase
- `reports/summary.md` - Scorecard with pass/fail status
- `.cache/` - Cached pages and downloads (7-day TTL)

## Output Schema

```typescript
{
  fair_name: string;
  official_url: string | null;
  official_domain: string | null;
  country: string | null;
  city: string | null;
  venue: string | null;

  documents: {
    downloads_overview_url: string | null;
    floorplan_url: string | null;
    exhibitor_manual_url: string | null;
    rules_url: string | null;
    schedule_page_url: string | null;
    exhibitor_directory_url: string | null;
  };

  schedule: {
    build_up: Array<{
      date: string | null;  // YYYY-MM-DD
      time: string | null;
      description: string;
      source_url: string;
    }>;
    tear_down: Array<{...}>;
  };

  quality: {
    floorplan: "strong" | "weak" | "missing";
    exhibitor_manual: "strong" | "weak" | "missing";
    rules: "strong" | "weak" | "missing";
    schedule: "strong" | "weak" | "missing";
    exhibitor_directory: "strong" | "weak" | "missing";
  };

  evidence: {
    [field]: { title: string | null; snippet: string | null };
  };

  debug: {
    action_log: Array<{ step, input, output, ms }>;
    visited_urls: string[];
    downloaded_files: Array<{ url, path, content_type, bytes }>;
    blocked_urls: Array<{ url, status, reason }>;
    candidates: { [field]: Array<{ url, score, why }> };
  };

  email_draft_if_missing: { ... } | null;
}
```

## Quality Definitions

| Level | Definition |
|-------|------------|
| **strong** | URL verified + document/page title matches + content snippet confirms the field |
| **weak** | URL + title seem plausible, but limited content verification |
| **missing** | Nothing found, or blocked by auth/bot protection |

## Hard Limits

| Limit | Value | Reason |
|-------|-------|--------|
| Max page opens | 30 | Prevent runaway crawling |
| Max downloads | 15 | Respect bandwidth |
| Max runtime | 10 min | Fail fast |
| Rate limit | 700-1200ms | Server respect |

## Architecture

```
src/
├── schemas/output.ts      # Zod schemas for output contract
├── agent/
│   ├── loop.ts            # Main state machine
│   └── tools/
│       ├── web-search.ts  # DuckDuckGo search
│       ├── open-page.ts   # Playwright page opening
│       ├── download-file.ts
│       ├── parse-pdf.ts   # PDF text extraction
│       └── extract-schedule.ts
├── guards/domain.ts       # Domain validation
├── scoring/candidates.ts  # Scoring and ranking
├── cache/manager.ts       # Cache management
└── utils/
    ├── logger.ts
    ├── rate-limit.ts
    └── text-extract.ts
```

## Agent State Machine

```
SEARCH → ENTRY → DOWNLOADS → PDF_PARSE → SELECT → DONE
```

1. **SEARCH**: Find official URL via web search or verify known_url
2. **ENTRY**: Navigate exhibitor sections, find download centers
3. **DOWNLOADS**: Download relevant PDFs from download center
4. **PDF_PARSE**: Extract text, find schedules and field matches
5. **SELECT**: Rank candidates, pick best per field with evidence

## Test Cases

The regression suite includes 10 German trade fairs:

1. Fruit Logistica (Berlin) - Heavy PDF/download center
2. ISE (Barcelona) - Large tech fair
3. Ambiente (Frankfurt) - Messe Frankfurt
4. bauma (Munich) - Construction fair
5. Hannover Messe - Industrial fair
6. Anuga (Cologne) - Food fair
7. MEDICA (Düsseldorf) - Medical fair
8. interzum (Cologne) - Furniture supplies
9. drupa (Düsseldorf) - Print/media
10. Automechanika (Frankfurt) - Automotive

## Development

```bash
# Type check
pnpm typecheck

# Run tests
pnpm test

# Build
pnpm build
```

## Design Document

See [DESIGN.md](./DESIGN.md) for detailed architecture decisions.

## License

MIT
