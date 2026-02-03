# Trade Fair Discovery - Agentic Design Document

## Overzicht

Trade Fair Discovery is een **agentic-first** tool die doelgericht navigeert op beurswebsites om exhibitor-informatie te vinden. In tegenstelling tot traditionele scrapers die breed crawlen, gedraagt deze tool zich als een menselijke agent die strategisch zoekt, downloadt en parseert.

## Kernprincipes

1. **Geen brede crawl** - Doelgerichte acties: search → open → decide → download → parse → select
2. **PDF-first** - Download centers en PDF's zijn "gold mines", niet obstakels
3. **Evidence-based** - Geen claims zonder hard bewijs (titel + snippet)
4. **Domain guard** - Strikte controle op foreign fair contamination
5. **Early exit** - Stop zodra alle velden minimaal weak hebben

---

## Agent Loop States

```
┌─────────────┐
│   START     │
└──────┬──────┘
       ▼
┌─────────────┐     ┌─────────────────────┐
│   SEARCH    │────▶│ Web search voor     │
│             │     │ official_url +      │
└──────┬──────┘     │ entry points        │
       │            └─────────────────────┘
       ▼
┌─────────────┐     ┌─────────────────────┐
│   ENTRY     │────▶│ Open official site  │
│             │     │ Find exhibitor/     │
└──────┬──────┘     │ download sections   │
       │            └─────────────────────┘
       ▼
┌─────────────┐     ┌─────────────────────┐
│  DOWNLOADS  │────▶│ Navigeer download   │
│             │     │ center, download    │
└──────┬──────┘     │ PDF's               │
       │            └─────────────────────┘
       ▼
┌─────────────┐     ┌─────────────────────┐
│  PDF_PARSE  │────▶│ Extract text,       │
│             │     │ zoek keywords,      │
└──────┬──────┘     │ build schedule      │
       │            └─────────────────────┘
       ▼
┌─────────────┐     ┌─────────────────────┐
│   SELECT    │────▶│ Rank candidates,    │
│             │     │ kies 1 beste per    │
└──────┬──────┘     │ veld + evidence     │
       │            └─────────────────────┘
       ▼
┌─────────────┐
│    DONE     │
└─────────────┘
```

### State Details

#### SEARCH
- **Input**: fair_name, city, country, known_url (optional)
- **Actions**:
  - Als known_url gegeven: verifieer met openPage
  - Anders: webSearch(`"{fair_name}" {city} exhibitor official site`)
  - webSearch(`"{fair_name}" exhibitor manual PDF`)
  - webSearch(`"{fair_name}" download center exhibitor`)
- **Output**: official_url + lijst entry_candidates
- **Guard**: Verifieer dat official_url branding/title matcht

#### ENTRY
- **Input**: official_url, entry_candidates
- **Actions**:
  - openPage(official_url) → extract alle links
  - Zoek naar: "exhibitor", "for exhibitors", "aussteller", "service", "downloads", "documents"
  - Bouw lijst van high-value pages: exhibitor portal, download center, exhibitor service
- **Output**: downloads_overview_url, exhibitor_pages[]

#### DOWNLOADS
- **Input**: downloads_overview_url, exhibitor_pages
- **Actions**:
  - openPage(downloads_overview_url) → extract PDF links
  - Filter op keywords: manual, handbook, regulations, floorplan, hall plan
  - downloadFile voor elke relevante PDF (max 15)
- **Output**: downloaded_files[]

#### PDF_PARSE
- **Input**: downloaded_files[]
- **Actions**:
  - parsePdf(path) → text extraction
  - extractScheduleFromText(text) → build_up/tear_down entries
  - Zoek keywords per veld:
    - floorplan: "hall plan", "floor plan", "plattegrond", "hallenplan"
    - manual: "exhibitor manual", "handbook", "service manual", "exhibitor guide"
    - rules: "regulations", "guidelines", "construction rules", "technical guidelines"
    - schedule: "build-up", "set-up", "move-in", "Aufbau", "Abbau", "dismantling", "tear-down"
- **Output**: candidates per veld met scores

#### SELECT
- **Input**: candidates per veld
- **Actions**:
  - rankCandidates(field, candidates) → select 1 beste
  - Bepaal quality (strong/weak/missing)
  - Extract evidence (title + snippet)
- **Output**: final documents{}, quality{}, evidence{}

---

## Scoring Model

### Score Criteria (0-100)

| Criterium | Punten | Beschrijving |
|-----------|--------|--------------|
| URL match | 0-20 | URL bevat relevante keywords |
| Title match | 0-30 | Document/pagina titel matcht field |
| Content match | 0-40 | Inhoud bevat expliciete keywords |
| Freshness | 0-10 | Recent jaar in URL/content |

### Quality Thresholds

- **strong** (≥70): URL + title + content snippet die expliciet veld bevestigt
- **weak** (40-69): URL + title match, maar beperkte content snippet
- **missing** (<40): Niets bruikbaars of blocked

### Evidence Rules

Een claim is alleen **strong** als:
1. Document/pagina is geopend of gedownload
2. Titel is expliciet relevant
3. Content snippet bevat expliciete keywords voor het veld

**NOOIT strong op basis van alleen:**
- Anchor tekst
- URL pattern
- Link op een pagina zonder te openen

---

## Domain Guard Logic

```typescript
function isDomainAllowed(url: string, officialDomain: string): boolean {
  const urlDomain = new URL(url).hostname;

  // Exact match
  if (urlDomain === officialDomain) return true;

  // Subdomain match (bv. service.messe-frankfurt.com)
  if (urlDomain.endsWith('.' + officialDomain)) return true;

  // Whitelisted domains (CDN, document hosting)
  const whitelist = [
    'cloudfront.net',
    's3.amazonaws.com',
    'blob.core.windows.net'
  ];
  if (whitelist.some(w => urlDomain.endsWith(w))) return true;

  return false;
}

// Foreign fair detection
const FOREIGN_PATTERNS = [
  /mapyourshow\.com/,
  /a]2z\.events/,
  /expocad\.com/,
  // Fair-specific patterns
  /ise\d{4}/,  // ISE beurs
  /ces\d{4}/,  // CES beurs
];

function isForeignFair(url: string, fairName: string): boolean {
  // Check if URL contains another fair's branding
  return FOREIGN_PATTERNS.some(p => p.test(url) && !url.includes(fairName.toLowerCase()));
}
```

---

## Caching Strategy

```
.cache/
├── pages/
│   └── {domain}/
│       └── {url-hash}.html       # Rendered HTML
├── downloads/
│   └── {domain}/
│       └── {filename}            # Downloaded files
└── metadata/
    └── {url-hash}.json           # Fetch metadata (status, headers, timestamp)
```

### Cache Rules
- Pages: 24 uur geldig
- Downloads: 7 dagen geldig
- Metadata: Altijd bewaren voor debugging

---

## Rate Limiting

```typescript
const RATE_LIMITS = {
  minDelayMs: 700,
  maxDelayMs: 1200,
  perHost: new Map<string, number>() // Last request timestamp per host
};

async function rateLimitedFetch(url: string): Promise<Response> {
  const host = new URL(url).hostname;
  const lastRequest = RATE_LIMITS.perHost.get(host) || 0;
  const delay = Math.max(
    0,
    lastRequest + randomBetween(700, 1200) - Date.now()
  );

  if (delay > 0) await sleep(delay);

  const response = await fetch(url);
  RATE_LIMITS.perHost.set(host, Date.now());
  return response;
}
```

---

## Hard Limits

| Limit | Waarde | Reden |
|-------|--------|-------|
| Max page opens | 30 | Voorkom runaway crawling |
| Max downloads | 15 | Voorkom bandwidth abuse |
| Max runtime | 10 min | Fail fast bij problematische sites |
| Rate limit | 700-1200ms | Respecteer servers |
| Max candidates per field | 3 | Focus op beste matches |

---

## Schedule Extraction

### Keywords per taal

| Taal | Build-up | Tear-down |
|------|----------|-----------|
| EN | build-up, set-up, move-in, installation | tear-down, dismantling, move-out, removal |
| DE | Aufbau, Aufbauzeit | Abbau, Abbauzeit |
| NL | opbouw | afbouw |
| FR | montage | démontage |

### Extraction Strategy

1. Eerst zoek in exhibitor manual PDF
2. Regex patterns voor datum/tijd:
   - `(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})` - Datums
   - `(\d{1,2}:\d{2})` - Tijden
   - `(\d{1,2}[.]\d{2}\s*(?:h|Uhr))` - Duitse tijden
3. Context window: 100 chars rond keyword match
4. Als PDF geen tijden: fallback naar schedule_page_url

---

## Output Files

### Per testcase:
- `/outputs/{id}.json` - Volledige JSON output
- `/reports/{id}.md` - Human-readable markdown rapport

### Aggregate:
- `/reports/summary.md` - Scorecard met pass/fail per testcase

---

## Error Handling

### Bot Protection / 403
1. Log in blocked_urls met status + reason
2. Probeer alternatieve routes:
   - Andere taalpagina (/en/, /de/)
   - Perskit / newsroom
   - Exhibitor service portal
3. Als critical data mist: genereer email_draft_if_missing

### Timeout / Network Errors
1. Retry max 2x met exponential backoff
2. Log in action_log met failure reason
3. Ga door met volgende candidate

---

## Project Structure

```
/home/user/salesapp/
├── DESIGN.md
├── README.md
├── package.json
├── tsconfig.json
├── vitest.config.ts
├── .gitignore
├── src/
│   ├── index.ts              # Main exports
│   ├── schemas/
│   │   └── output.ts         # Zod schemas
│   ├── agent/
│   │   ├── loop.ts           # Main agent loop
│   │   ├── states/
│   │   │   ├── search.ts
│   │   │   ├── entry.ts
│   │   │   ├── downloads.ts
│   │   │   ├── pdf-parse.ts
│   │   │   └── select.ts
│   │   └── tools/
│   │       ├── web-search.ts
│   │       ├── open-page.ts
│   │       ├── download-file.ts
│   │       ├── parse-pdf.ts
│   │       └── extract-schedule.ts
│   ├── guards/
│   │   └── domain.ts         # Domain validation
│   ├── scoring/
│   │   └── candidates.ts     # Scoring & ranking
│   ├── cache/
│   │   └── manager.ts        # Cache management
│   └── utils/
│       ├── rate-limit.ts
│       ├── logger.ts
│       └── text-extract.ts
├── cli/
│   └── discover.ts           # CLI entry point
├── scripts/
│   └── regression.ts         # Regression runner
├── inputs/
│   └── testcases.json        # Test cases
├── outputs/                  # JSON outputs
├── reports/                  # Markdown reports
└── .cache/                   # Runtime cache
```

---

## Next Steps

1. ✅ DESIGN.md (dit document)
2. Scaffold project + dependencies
3. Implementeer Zod schemas
4. Implementeer agent tools
5. Implementeer agent loop
6. CLI + regression runner
7. 10 testcases + run
