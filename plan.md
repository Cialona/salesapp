# Exhibitor Scraper — Implementatieplan

## Analyse: Wat hergebruiken we?

### DIRECT HERBRUIKBAAR (importeren)
| Bestand | Wat | Hoe |
|---------|-----|-----|
| `browser_controller.py` | Playwright browser wrapper (26 methods: goto, click, scroll, screenshot, extract_text, extract_links) | Direct importeren. Heeft alles: navigatie, klikken, scrollen, tekst extractie, screenshots. Mist alleen tabel-extractie — dat voegen we toe als utility in de scraper module |
| `config.py` | Cialona branding, kleuren, CSS | Direct importeren in Streamlit pages |
| `data_manager.py` | JSON storage pattern met file locking, atomic writes, ID generatie | Patroon kopiëren naar eigen `scraper_data_manager.py` met exhibitor-specifiek schema |
| `job_manager.py` | Background thread runner, progress tracking, cancellation, phase management | Patroon kopiëren naar eigen `scraper_job_manager.py` — andere fases, ander agent type |

### INSPIRATIE (patroon overnemen, code opnieuw schrijven)
| Bron | Patroon | Toepassing |
|------|---------|------------|
| `claude_agent.py` | Screenshot → LLM → Action loop | Scraper agent: screenshot nemen, LLM vragen "wat zie je / hoe pagineren", actie uitvoeren |
| `claude_agent.py` | Exponential backoff retry voor API calls | Zelfde pattern, 3-5 retries |
| `claude_agent.py` | System prompt met gestructureerde tool-definitie | Eigen system prompt voor scrape-instructies |
| `claude_agent.py` | Phase callbacks (`on_status`, `on_phase`) | Zelfde callback pattern voor UI updates |
| `pages/1_Discovery.py` | Form input + progress tracking + auto-refresh | Zelfde UI pattern voor scrape pagina |
| `pages/2_Fair_Details.py` | Tabbed detail view + export | Zelfde pattern voor review pagina |
| `schemas.py` | Dataclass-based output schema | Eigen schema's voor exhibitor data |

### NIET RELEVANT
| Bestand | Reden |
|---------|-------|
| `document_classifier.py` | PDF classificatie — niets mee te maken |
| `src/` (TypeScript) | Legacy TypeScript agent — we bouwen in Python |
| `cli/` | CLI test tools — niet relevant |

---

## Nieuwe bestanden

```
streamlit-app/
├── exhibitor_scraper/           # NIEUWE MODULE
│   ├── __init__.py
│   ├── schemas.py               # Dataclasses: Exhibitor, ScrapeResult, EnrichmentResult
│   ├── scraper_agent.py         # Stap 1: Beurspagina scrapen (LLM + browser)
│   ├── enrichment_agent.py      # Stap 2: Bedrijfsgegevens verrijken (LLM + browser)
│   └── excel_export.py          # Excel generatie (openpyxl)
├── scraper_data_manager.py      # Data opslag voor scrape results (JSON, zelfde pattern als data_manager.py)
├── scraper_job_manager.py       # Background job runner voor scrape/enrich jobs
└── pages/
    ├── 4_Exhibitor_Scraper.py   # UI: Start scrape + voortgang
    └── 5_Exhibitor_Review.py    # UI: Review lijst + filter + edit + Excel export
```

---

## Schema's (exhibitor_scraper/schemas.py)

```python
@dataclass
class Exhibitor:
    company_name: str                    # Verplicht
    country: str = ""                    # Uit beurspagina of later verrijkt
    stand_number: str = ""               # Standnummer
    website: str = ""                    # Bedrijfswebsite
    email: str = ""                      # Contact email
    phone: str = ""                      # Telefoonnummer
    stand_size_raw: str = ""             # Originele tekst ("Large Stand", "42m²", "")
    stand_size_m2: float | None = None   # Numeriek in m², None als onbekend
    status: str = "scraped"              # scraped | approved | rejected | enriched
    needs_review: bool = False           # True als standgrootte onbekend
    notes: str = ""

@dataclass
class ScrapeResult:
    fair_name: str
    fair_year: int
    source_url: str                      # De exposantenlijst-URL
    exhibitors: List[Exhibitor]          # Alle gevonden exposanten
    total_found: int
    pages_visited: int
    scrape_duration_secs: float
    agent_actions: int                   # Hoeveel browser-acties
    log: List[str]

@dataclass
class FilterCriteria:
    countries: List[str] = field(default_factory=lambda: ["Netherlands", "Belgium", "NL", "BE"])
    min_stand_size_m2: float = 40.0
    include_unknown_size: bool = True    # Markeer als needs_review

@dataclass
class EnrichmentResult:
    company_name: str
    website_found: str = ""              # Gevonden via Google
    email_found: str = ""                # Gevonden op bedrijfswebsite
    phone_found: str = ""               # Gevonden op bedrijfswebsite
    enrichment_source: str = ""          # "google" / "company_website" / "contact_page"
```

---

## Stap 1: Scraper Agent (scraper_agent.py)

### Aanpak: Screenshot-driven LLM agent

De scraper werkt net als de discovery browser agent: screenshot → LLM → actie → herhaal. Maar met een **veel gerichter doel**: lees de tabel/lijst uit en pagineer door.

### Flow

```
1. Navigeer naar de opgegeven URL
2. Neem screenshot + extract tekst
3. Stuur naar LLM: "Dit is een exposantenlijst. Wat zie je?"
   LLM reageert met een van:
   - extract_exhibitors: [{name, country, stand, ...}, ...]
   - paginate: {action: "click_next" | "click_letter_B" | "scroll_down" | ...}
   - done: alle exposanten zijn uitgelezen
4. Voer de actie uit (klik volgende pagina, scroll, klik letter-tab)
5. Herhaal vanaf stap 2
```

### System prompt (kern)

```
Je bent een exposantenlijst-scraper. Je krijgt een screenshot van een beurspagina.

Jouw taak:
1. Identificeer alle exposanten op de huidige pagina
2. Per exposant: extract company_name (verplicht) + alle beschikbare velden
3. Bepaal of er meer pagina's/tabs zijn (paginering, A-Z tabs, "load more", scroll)
4. Geef aan welke actie nodig is om de volgende exposanten te laden

Tools:
- extract_exhibitors: registreer gevonden exposanten
- navigate_action: klik/scroll/type om meer exposanten te laden
- mark_complete: alle exposanten zijn uitgelezen
```

### Guardrails
- **Max 50 acties** per run (voorkomt runaway)
- **Deduplicatie**: bijhouden welke bedrijfsnamen al gezien zijn
- **Paginering-detectie**: LLM herkent Next/Volgende/→/Page 2/Letter tabs/Load More
- **Kosten**: ~€0.20-0.80 per beurs (Sonnet, max 50 iteraties)

### Tools voor de LLM

```python
tools = [
    {
        "name": "extract_exhibitors",
        "description": "Register exhibitors found on the current page",
        "input_schema": {
            "type": "object",
            "properties": {
                "exhibitors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "company_name": {"type": "string"},
                            "country": {"type": "string"},
                            "stand_number": {"type": "string"},
                            "website": {"type": "string"},
                            "email": {"type": "string"},
                            "phone": {"type": "string"},
                            "stand_size": {"type": "string"}
                        },
                        "required": ["company_name"]
                    }
                }
            },
            "required": ["exhibitors"]
        }
    },
    {
        "name": "navigate_action",
        "description": "Perform a browser action to load more exhibitors",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["click", "scroll_down", "goto_url"]},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "url": {"type": "string"},
                "reason": {"type": "string"}
            },
            "required": ["action", "reason"]
        }
    },
    {
        "name": "mark_complete",
        "description": "Signal that all exhibitors have been extracted",
        "input_schema": {
            "type": "object",
            "properties": {
                "total_found": {"type": "integer"},
                "notes": {"type": "string"}
            }
        }
    }
]
```

---

## Filtering (automatisch + review)

Na stap 1 past de app automatisch filters toe:

```python
def apply_filters(exhibitors: List[Exhibitor], criteria: FilterCriteria) -> List[Exhibitor]:
    for ex in exhibitors:
        # Parse stand_size_m2 uit stand_size_raw
        ex.stand_size_m2 = parse_stand_size(ex.stand_size_raw)  # "42m²" → 42.0, "Large" → None

        # Land filter
        country_match = any(c.lower() in ex.country.lower() for c in criteria.countries) if ex.country else False

        # Grootte filter
        if ex.stand_size_m2 is not None:
            size_match = ex.stand_size_m2 >= criteria.min_stand_size_m2
        else:
            size_match = criteria.include_unknown_size
            ex.needs_review = True  # Markeer voor handmatige check

        if country_match and size_match:
            ex.status = "approved"
        else:
            ex.status = "rejected"
```

---

## Stap 2: Enrichment Agent (enrichment_agent.py)

### Alleen voor goedgekeurde exposanten met ontbrekende gegevens

### Flow per bedrijf

```
1. Website ontbreekt?
   → Google "{company_name}" → neem eerste relevante resultaat
   → Valideer: is dit echt het bedrijf? (LLM check op bedrijfsnaam in pagina)

2. Telefoon/email ontbreekt?
   → Navigeer naar bedrijfswebsite
   → Zoek contactpagina, footer, of "about" pagina
   → Extract telefoon en/of email
   → LLM valideert: is dit een algemeen contactnummer of specifiek persoon?

3. Sla resultaat op
```

### Guardrails
- **Max 5 acties per bedrijf** (Google + website + contactpagina = genoeg)
- **Batch**: verwerk alle bedrijven sequentieel in één browser-sessie
- **Geen contactpersonen**: alleen algemene bedrijfsgegevens

---

## Streamlit UI

### Pagina 4: Exhibitor Scraper (4_Exhibitor_Scraper.py)

```
┌─────────────────────────────────────────────┐
│  🔍 Exposantenlijst Scrapen                 │
├─────────────────────────────────────────────┤
│  Beursnaam*:    [________________]          │
│  Jaar*:         [2026        ▼]             │
│  URL exposantenlijst*: [________________]   │
│                                             │
│  Filter instellingen:                       │
│  Landen:        [NL, BE           ]         │
│  Min. m²:       [40              ]          │
│  Onbekende m²:  [✓ Meenemen voor review]    │
│                                             │
│  [▶ Start Scraping]                         │
├─────────────────────────────────────────────┤
│  Actieve Jobs:                              │
│  ┌─ bauma 2026 ─────────────────────┐       │
│  │ ████████████░░░░░░ 65% · 1:23    │       │
│  │ Fase: Pagina 3 van 12 uitgelezen │       │
│  │ 234 exposanten gevonden          │       │
│  │ [■ Stop]                         │       │
│  └──────────────────────────────────┘       │
│                                             │
│  Voltooide Jobs:                            │
│  ✓ Greentech 2026 · 156 exposanten · 45 NL  │
│    [Bekijk Details]                         │
└─────────────────────────────────────────────┘
```

### Pagina 5: Exhibitor Review (5_Exhibitor_Review.py)

```
┌──────────────────────────────────────────────────────────────┐
│  📋 Exposantenlijst: bauma 2026                              │
│  312 totaal · 67 NL/BE · 45 >40m² · 12 handmatig checken    │
├──────────────────────────────────────────────────────────────┤
│  Tabs: [Goedgekeurd (45)] [Te reviewen (12)] [Afgewezen (255)] [Alle (312)]  │
├──────────────────────────────────────────────────────────────┤
│  Filter: Land [Alle ▼]  Grootte [>40m² ▼]  Zoek [______]    │
├──────────────────────────────────────────────────────────────┤
│  ☑ │ Bedrijf          │ Land │ Stand │  m²  │ Website │ Tel │
│  ──┼──────────────────┼──────┼───────┼──────┼─────────┼─────│
│  ✓ │ ACME Displays    │ NL   │ A-123 │ 64   │ ✓       │ ✗   │
│  ✓ │ Van der Berg BV  │ NL   │ B-045 │ 48   │ ✓       │ ✓   │
│  ? │ XYZ Expo NL      │ NL   │ C-089 │  ?   │ ✗       │ ✗   │  ← needs_review
│  ✓ │ Belgian Stands   │ BE   │ D-201 │ 120  │ ✓       │ ✓   │
├──────────────────────────────────────────────────────────────┤
│  Bulk acties:                                                │
│  [✓ Selectie goedkeuren] [✗ Selectie afwijzen]               │
│  [🔍 Verrijk geselecteerde] [📥 Export naar Excel]           │
│                                                              │
│  m² handmatig invullen: klik op "?" om te bewerken           │
└──────────────────────────────────────────────────────────────┘
```

---

## Excel Export (excel_export.py)

```python
def export_to_excel(fair_name: str, exhibitors: List[Exhibitor]) -> bytes:
    """Genereer Excel met exact het format dat jullie nu gebruiken."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = fair_name[:31]  # Excel tab naam max 31 chars

    # Headers (exact jullie format)
    headers = ["Company Name", "Website", "Country", "Phone", "Email",
               "Stand No.", "Number m²", "Notes"]
    ws.append(headers)

    # Header styling
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="FF6B35", fill_color="FF6B35")  # Cialona orange
        cell.font = Font(bold=True, color="FFFFFF")

    # Data
    for ex in exhibitors:
        ws.append([
            ex.company_name,
            ex.website,
            ex.country,
            ex.phone,
            ex.email,
            ex.stand_number,
            ex.stand_size_m2 or "",
            ex.notes,
        ])

    # Auto-width kolommen
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
```

---

## Bouwvolgorde

### Milestone 1: Scraper core (testbaar zonder UI)
1. `exhibitor_scraper/__init__.py` — leeg
2. `exhibitor_scraper/schemas.py` — dataclasses
3. `exhibitor_scraper/scraper_agent.py` — de LLM+browser scrape loop
4. Handmatig testen: `python -c "from exhibitor_scraper.scraper_agent import ..."` met een bekende URL

### Milestone 2: Data opslag + filtering
5. `scraper_data_manager.py` — CRUD voor scrape results
6. Filtering logica in schemas of data manager

### Milestone 3: Streamlit UI - Scrape pagina
7. `pages/4_Exhibitor_Scraper.py` — input form + job tracking
8. `scraper_job_manager.py` — background runner

### Milestone 4: Review pagina + Excel export
9. `exhibitor_scraper/excel_export.py` — openpyxl export
10. `pages/5_Exhibitor_Review.py` — tabel, filters, bulk acties, export

### Milestone 5: Enrichment
11. `exhibitor_scraper/enrichment_agent.py` — Google + website scrape
12. Enrichment integratie in review pagina ("Verrijk geselecteerde" knop)

### Milestone 6: Polish
13. Dashboard integratie (app.py — scraper stats naast discovery stats)
14. Testen met 3-5 echte beurzen, bugs fixen

---

## Eerste testbare milestone

**Milestone 1** is het eerste moment dat we kunnen testen: de scraper_agent met een hardcoded URL draaien en zien of hij exposanten kan extraheren. Dit is de kern van het hele systeem — als dit werkt, is de rest UI en plumbing.

Test command:
```python
import asyncio
from exhibitor_scraper.scraper_agent import ExhibitorScraperAgent

agent = ExhibitorScraperAgent(api_key="sk-...")
result = asyncio.run(agent.scrape("https://www.greentech.nl/amsterdam/exhibitors"))
print(f"Gevonden: {len(result.exhibitors)} exposanten")
for ex in result.exhibitors[:5]:
    print(f"  {ex.company_name} | {ex.country} | Stand {ex.stand_number}")
```

---

## Kosteninschatting per beurs

| Stap | Model | Acties | Geschatte kosten |
|------|-------|--------|-----------------|
| Scrape (stap 1) | Sonnet | 10-50 screenshots + extractions | €0.20-0.80 |
| Enrich (stap 2) | Sonnet | 2-5 acties × 20-80 bedrijven | €0.50-2.00 |
| **Totaal per beurs** | | | **€0.70-2.80** |

Ter vergelijking: 1-2 uur Filipijnse medewerker = ~€8-15.

---

## Wat we NIET bouwen (bewust lean)

- Geen login/authenticatie voor beveiligde exposantenlijsten
- Geen contactpersoon-zoeker (te onbetrouwbaar)
- Geen HubSpot integratie (handmatige Excel import is goed genoeg voor nu)
- Geen scheduling/cron (handmatig starten per beurs)
- Geen multi-beurs batch (één voor één is prima)
- Geen standgrootte-schatter op basis van plattegrond (te complex)
