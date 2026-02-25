# CLAUDE.md - Trade Fair Discovery (Cialona Sales App)

## Wat is dit project?

Een **agentic trade fair discovery platform** voor Cialona ("Eye for Attention"). Het ontdekt automatisch exposantendocumenten van beurswebsites: plattegronden, exposantenhandleidingen, technische richtlijnen, opbouw/afbouw schema's en exposantenlijsten.

## Taal

De gebruiker communiceert in het **Nederlands**. Reageer altijd in het Nederlands.

## Architectuur

Het project heeft **twee engines**:

1. **Rule-based engine** (TypeScript/Node.js) - State machine: SEARCH → ENTRY → DOWNLOADS → PDF_PARSE → SELECT → DONE
2. **Claude Computer Use engine** (TypeScript) - Claude navigeert websites met vision + browser control

En een **Streamlit web dashboard** (Python) als frontend.

## Project structuur

```
salesapp/
├── src/                          # TypeScript core
│   ├── agent/
│   │   ├── loop.ts               # Hoofd state machine (677 regels)
│   │   └── tools/
│   │       ├── web-search.ts     # DuckDuckGo zoeken
│   │       ├── open-page.ts      # Playwright pagina openen
│   │       ├── download-file.ts  # Bestanden downloaden + caching
│   │       ├── parse-pdf.ts      # PDF tekst extractie
│   │       └── extract-schedule.ts # Schema datum/tijd extractie
│   ├── claude-agent/
│   │   ├── claude-agent.ts       # Claude Computer Use agent (700 regels)
│   │   └── browser-controller.ts # Browser besturing via Claude
│   ├── schemas/output.ts         # Zod schemas (DiscoveryOutput etc.)
│   ├── guards/domain.ts          # Domain validatie + foreign fair detectie
│   ├── scoring/candidates.ts     # Kandidaat scoring & ranking (0-100)
│   ├── cache/manager.ts          # Cache beheer (pagina's: 24u, downloads: 7d)
│   └── utils/
│       ├── logger.ts             # Action logging
│       ├── rate-limit.ts         # Rate limiting (700-1200ms per request)
│       └── text-extract.ts       # HTML extractie + keyword matching
│
├── cli/
│   ├── discover.ts               # Rule-based CLI
│   └── discover-claude.ts        # Claude Computer Use CLI
│
├── streamlit-app/                # Python Streamlit web dashboard
│   ├── app.py                    # Hoofd dashboard
│   ├── config.py                 # Cialona branding (oranje #F7931E, navy #1E2A5E)
│   ├── data_manager.py           # File-based JSON opslag (thread-safe)
│   ├── job_manager.py            # Achtergrond job scheduling
│   ├── pages/
│   │   ├── 1_Discovery.py        # Nieuwe discovery starten
│   │   ├── 2_Fair_Details.py     # Beurs details bekijken
│   │   └── 3_Email_Generator.py  # E-mail concept generator
│   └── discovery/
│       ├── schemas.py            # Python dataclasses
│       ├── document_classifier.py
│       ├── document_types.py
│       ├── browser_controller.py
│       └── claude_agent.py
│
├── scripts/regression.ts         # Regressie test runner
├── inputs/testcases.json         # 10 test beurzen
├── outputs/                      # JSON resultaten (gitignored)
├── reports/                      # Markdown rapporten
└── .cache/                       # Runtime cache
```

## Commando's

```bash
# TypeScript discovery
pnpm discover --name "Beurs" --url https://example.com
pnpm discover:claude --name "Beurs" --url https://example.com

# Regressie tests (10 Duitse beurzen)
pnpm regression
pnpm regression fruit-logistica-2025

# Development
pnpm build          # TypeScript compileren
pnpm typecheck      # Type checking
pnpm test           # Vitest unit tests

# Streamlit dashboard
streamlit run streamlit-app/app.py
```

## Tech stack

**TypeScript/Node.js (>=20):** Playwright, Cheerio, Zod, Commander, pdf-parse, Sharp, @anthropic-ai/sdk
**Python:** Streamlit, Pandas, Plotly, Anthropic SDK, Playwright, pypdf
**Build:** pnpm, TypeScript 5.3+, Vitest
**CI/CD:** GitHub Actions

## Belangrijke concepten

### Quality levels
- **strong** (score >=70): URL + titel + content snippet bevestigd
- **weak** (score 40-69): URL + titel match, beperkte content
- **missing** (score <40): Niet gevonden of geblokkeerd

### Hard limits
| Limit | Waarde |
|-------|--------|
| Max pagina opens | 30 |
| Max downloads | 15 |
| Max runtime | 10 min |
| Rate limit | 700-1200ms |

### Domain Guard
Voorkomt "foreign fair contamination" - strikte controle dat gevonden documenten bij de juiste beurs horen. Whitelisted CDN's: CloudFront, S3, Azure Blob, Cloudflare.

### Meertalige keywords
Keywords voor document matching in: Engels, Duits, Nederlands, Frans.
- Opbouw: "build-up", "Aufbau", "opbouw", "montage"
- Afbouw: "tear-down", "Abbau", "afbouw", "démontage"

## Veelvoorkomende patronen

### State machine pattern (loop.ts)
```typescript
type AgentState = 'SEARCH' | 'ENTRY' | 'DOWNLOADS' | 'PDF_PARSE' | 'SELECT' | 'DONE';
while (ctx.state !== 'DONE' && !isOverLimit(ctx)) {
  switch (ctx.state) { ... }
}
```

### Evidence-based scoring
Alleen "strong" claimen met: URL geopend/gedownload + titel expliciet relevant + content snippet met keywords. NOOIT strong op basis van alleen anchor tekst of URL pattern.

### Web search
Gebruikt DuckDuckGo HTML search (geen API key nodig). Wordt alleen getriggerd als `known_url` leeg is.

## Streamlit app details

- Admin PIN: `cialona2026`
- Branding: Cialona oranje (#F7931E) + navy (#1E2A5E)
- Data opslag: file-based JSON met fcntl file locking (thread-safe)
- Multi-threaded achtergrond discovery jobs

## Database

Geen traditionele database. Alles is file-based:
- `streamlit-app/data/fairs.json` - Beurs resultaten
- `.cache/` - Pagina en download cache
- `outputs/` - JSON discovery resultaten
- `reports/` - Markdown rapporten

## Test beurzen (regressie suite)

1. Fruit Logistica (Berlin) - PDF heavy
2. ISE (Barcelona) - Grote tech beurs
3. Ambiente (Frankfurt) - Messe Frankfurt
4. bauma (Munich) - Bouwbeurs
5. Hannover Messe - Industriebeurs
6. Anuga (Cologne) - Voedingsbeurs
7. MEDICA (Dusseldorf) - Medische beurs
8. interzum (Cologne) - Meubelindustrie
9. drupa (Dusseldorf) - Print/media
10. Automechanika (Frankfurt) - Automotive

## Bekende aandachtspunten

- De DuckDuckGo web search wordt alleen aangeroepen als er geen `known_url` is meegegeven. Als een beurs altijd met URL wordt gestart, wordt de zoekfunctie nooit getest.
- Bot protection (403) is een veelvoorkomend probleem. De agent probeert alternatieve routes (andere taal, perskit, exhibitor portal).
- Beursnamen met speciale tekens (bijv. `&` in "Zorg & Facility") moeten correct URL-encoded worden voor zoekopdrachten.
