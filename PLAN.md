# Plan: Exhibitor Scraper Module

## Analyse bestaande code

### Per bestand: Herbruikbaar / Inspiratie / Niet relevant

| Bestand | Classificatie | Toelichting |
|---------|--------------|-------------|
| `streamlit-app/discovery/browser_controller.py` | **Herbruikbaar** | Generieke Playwright-wrapper. Alle browser-acties (click, type, scroll, navigate, screenshot), link-extractie, accordion-expansie, email-extractie. Kan direct geïmporteerd worden vanuit `discovery/` — geen copy nodig. |
| `streamlit-app/discovery/claude_agent.py` | **Inspiratie** | Agent-loop pattern (messages → tool_use → tool_result → herhaal), rate-limit retry, screenshot+links feedback, midpoint-warnings. De logica zelf is discovery-specifiek (document classificatie, PDF-analyse, subdomain-probing). We schrijven een nieuwe agent met dezelfde patronen maar andere tools en prompts. |
| `streamlit-app/discovery/schemas.py` | **Inspiratie** | Dataclass-patronen, `output_to_dict()` serialisatie, `ActionLogEntry`, `DebugInfo`. We maken nieuwe dataclasses voor exposanten maar hergebruiken het patroon. |
| `streamlit-app/discovery/document_classifier.py` | **Niet relevant** | PDF-classificatie en document-validatie. Heeft niets te maken met exposantenlijsten scrapen. |
| `streamlit-app/discovery/document_types.py` | **Niet relevant** | Keyword-registry voor floorplans/manuals/rules. Niet van toepassing. |
| `streamlit-app/data_manager.py` | **Inspiratie** | Thread-safe JSON persistence met `fcntl` + `threading.Lock`, atomic read-modify-write. We maken een eigen `exhibitor_data_manager.py` met hetzelfde patroon maar andere datastructuur. |
| `streamlit-app/job_manager.py` | **Herbruikbaar** | Background-job runner met status tracking. Kan direct hergebruikt worden als we een generieke job-interface maken, OF we importeren het bestaande patroon. |
| `streamlit-app/config.py` | **Herbruikbaar** | Alle branding (kleuren, CSS, fonts), status-badges, chip-HTML. Direct importeerbaar. |
| `streamlit-app/app.py` | **Inspiratie** | Dashboard-layout, sidebar-navigatie, metrics-weergave. We voegen navigatie toe naar de nieuwe pagina's. |
| `streamlit-app/pages/1_Discovery.py` | **Inspiratie** | Form-patterns, progress-tracking, job-status-weergave. We bouwen soortgelijke pagina's met eigen formulieren. |
| `streamlit-app/pages/2_Fair_Details.py` | **Inspiratie** | Tabs, data-cards, copy-buttons. UI-patronen die we hergebruiken. |
| `streamlit-app/pages/3_Email_Generator.py` | **Niet relevant** | Email-generatie voor ontbrekende documenten. |
| `src/` (TypeScript) | **Niet relevant** | TypeScript agent — we bouwen in Python. Patronen (state machine, scoring) zijn leerzaam maar de code zelf is niet bruikbaar. |
| `cli/` | **Niet relevant** | TypeScript CLI wrappers. |

---

## Module-structuur

```
streamlit-app/
├── exhibitor_scraper/                 # NIEUWE MODULE
│   ├── __init__.py
│   ├── schemas.py                     # Pydantic/dataclass modellen
│   ├── scraper_agent.py               # Claude agent voor Stap 1 (beurspagina scrapen)
│   ├── enrichment_agent.py            # Claude agent voor Stap 2 (bedrijfsgegevens verrijken)
│   ├── filters.py                     # Automatische filtering (land, standgrootte)
│   ├── excel_export.py                # Excel-export in het juiste format
│   └── data_manager.py               # Persistentie voor exposantendata (JSON)
├── pages/
│   ├── 4_Exhibitor_Scraper.py         # Nieuwe pagina: scrapen + voortgang
│   └── 5_Exhibitor_Review.py          # Nieuwe pagina: review + export
```

### Gedeelde imports vanuit bestaande code:
- `from discovery.browser_controller import BrowserController, ScreenshotResult`
- `from config import CIALONA_ORANGE, CIALONA_NAVY, CUSTOM_CSS, ...`
- `from job_manager import JobManager` (of vergelijkbaar patroon)

---

## Bestand-voor-bestand ontwerp

### 1. `exhibitor_scraper/schemas.py`

Dataclasses voor het hele proces:

```python
@dataclass
class Exhibitor:
    company_name: str
    country: Optional[str] = None
    stand_number: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    stand_size: Optional[str] = None        # Exact m² als getal, of categorie-label
    stand_size_numeric: Optional[float] = None  # Geparsed m² (None als onbekend)
    notes: str = ""

    # Status velden
    filter_status: str = "pending"          # "approved", "rejected", "manual_check"
    enrichment_status: str = "pending"      # "pending", "enriched", "failed"

@dataclass
class ScrapeJob:
    fair_name: str
    fair_url: str                           # URL van de exposantenlijst-pagina
    country_filter: List[str]               # Bijv. ["NL", "BE"]
    min_stand_size_m2: Optional[float]      # Bijv. 40.0
    status: str = "pending"                 # "scraping", "scraped", "reviewing", "enriching", "done"
    exhibitors_raw: List[Exhibitor] = field(default_factory=list)
    exhibitors_filtered: List[Exhibitor] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    scrape_log: List[str] = field(default_factory=list)

@dataclass
class ActionLogEntry:
    action: str
    detail: str
    timestamp: str
```

### 2. `exhibitor_scraper/scraper_agent.py` — Stap 1: Beurspagina scrapen

De kern van de module. Een Claude-agent die:
- De `BrowserController` uit `discovery/` hergebruikt
- De exposantenlijst-pagina bezoekt
- De paginastructuur begrijpt (GEEN hardcoded selectors)
- Alle exposanten uitleest inclusief paginering

**Agent-architectuur:**
- Model: `claude-sonnet-4-20250514`
- Tools die de agent krijgt:
  1. `computer` (Computer Use) — screenshot, click, scroll, type, key
  2. `goto_url` — directe navigatie
  3. `report_exhibitors` — gestructureerde output van gevonden exposanten (batch per pagina)
- Systeem-prompt: instrueert de agent om:
  - De pagina te analyseren (structuur herkennen)
  - Alle exposanten te extraheren per pagina
  - Paginering af te handelen (next-button, A-Z tabs, load-more, scroll)
  - Per exposant alle beschikbare velden te rapporteren
  - Te stoppen na alle pagina's OF na 50 acties (hard limit)
- Agent-loop: zelfde patroon als `claude_agent.py` (messages → API call → tool_use → execute → append result → herhaal)
- Rate-limit retry met exponential backoff (overgenomen patroon)

**report_exhibitors tool:**
```python
{
    "name": "report_exhibitors",
    "description": "Report a batch of exhibitors found on the current page",
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
            },
            "page_info": {"type": "string"},
            "has_more_pages": {"type": "boolean"}
        },
        "required": ["exhibitors"]
    }
}
```

### 3. `exhibitor_scraper/filters.py` — Automatische filtering

Simpele, deterministische filtering:
- `filter_by_country(exhibitors, allowed_countries)` — matcht op country-veld (case-insensitive, met aliassen: "Netherlands" → "NL", "België" → "BE", etc.)
- `filter_by_stand_size(exhibitors, min_m2)` — probeert `stand_size` te parsen naar m². Markeert als "manual_check" als niet parseerbaar.
- `apply_filters(exhibitors, country_filter, min_m2)` → geeft 3 lijsten terug: approved, rejected, manual_check

### 4. `exhibitor_scraper/enrichment_agent.py` — Stap 2: Verrijking

Een tweede, aparte Claude-agent die per bedrijf ontbrekende gegevens opzoekt:
- Model: `claude-sonnet-4-20250514`
- Tools:
  1. `computer` (Computer Use)
  2. `goto_url`
  3. `google_search` — Google-zoekopdracht via browser navigatie naar google.com
  4. `update_exhibitor` — gestructureerde update van een exposant
- Werkt per batch: krijgt lijst van exposanten met ontbrekende velden
- Per exposant:
  - Website ontbreekt → Google "{company_name}" → neem eerste relevante resultaat
  - Telefoon/email ontbreekt → bezoek website → zoek contactpagina/footer
- Hard limit: max 5 pagina-acties per exposant (voorkom runaway)
- GEEN contactpersonen zoeken (expliciet uitgesloten)

### 5. `exhibitor_scraper/excel_export.py` — Excel export

Gebruikt `openpyxl` (of `xlsxwriter`):
- `export_to_excel(scrape_jobs: List[ScrapeJob], filepath)`
- Per beurs een tab (worksheet) met sheet-naam = beursnaam (max 31 chars)
- Kolommen: Company Name | Website | Country | Phone | Email | Stand No. | Number m² | Notes
- Header-styling: Cialona navy achtergrond, witte tekst
- Auto-column-width

### 6. `exhibitor_scraper/data_manager.py` — Persistentie

Zelfde patroon als bestaande `data_manager.py`:
- `SCRAPE_JOBS_FILE = DATA_DIR / "scrape_jobs.json"`
- Thread-safe met `threading.Lock()` + `fcntl.flock()`
- CRUD: `save_job()`, `get_job()`, `list_jobs()`, `delete_job()`, `update_exhibitors()`
- Atomic read-modify-write

### 7. `pages/4_Exhibitor_Scraper.py` — Streamlit UI: Scrapen

Layout:
- Header: "Beurslijst Scrapen"
- Formulier:
  - Beursnaam (text input, verplicht)
  - URL exposantenlijst (text input, verplicht)
  - Landfilter (multiselect: NL, BE, DE, FR, UK, US, etc.)
  - Minimale standgrootte m² (number input, default 40)
- Start-knop → start achtergrondtaak (scraper_agent)
- Voortgangs-weergave:
  - Status-badge (scraping / filtering / done)
  - Live log (collapsible)
  - Teller: "X exposanten gevonden, Y pagina's gescraped"
- Resultaat-tabel (st.dataframe) na afronding
  - Kolommen: Company Name, Country, Stand No., Website, Stand Size, Status
  - Kleurcodering: approved (groen), manual_check (oranje), rejected (grijs)
- Knop: "Ga naar Review →"

### 8. `pages/5_Exhibitor_Review.py` — Streamlit UI: Review + Export

Layout:
- Header: "Beurslijst Review"
- Beursselector (dropdown van alle gescrapete beurzen)
- Tabs: "Goedgekeurd" | "Handmatig checken" | "Afgewezen" | "Alle"
- Bewerkbare tabel:
  - Per exposant: alle velden bewerkbaar
  - Stand-grootte: invulveld voor onbekende waardes
  - Checkbox: goedkeuren/afwijzen per exposant
  - Bulk-acties: "Alle goedkeuren", "Selectie verwijderen"
- Verrijking-sectie:
  - Knop: "Start verrijking voor goedgekeurde exposanten"
  - Voortgang per exposant
  - Resultaat-update in tabel
- Export-sectie:
  - Knop: "Export naar Excel"
  - Download-link voor Excel-bestand
  - Optie: meerdere beurzen in één Excel (multi-tab)

---

## Bouwvolgorde

### Fase 1: Fundament (schemas + data + filters)
1. `exhibitor_scraper/__init__.py`
2. `exhibitor_scraper/schemas.py`
3. `exhibitor_scraper/data_manager.py`
4. `exhibitor_scraper/filters.py`
5. `exhibitor_scraper/excel_export.py`

### Fase 2: Scraper Agent (Stap 1)
6. `exhibitor_scraper/scraper_agent.py`

### Fase 3: UI - Scrapen
7. `pages/4_Exhibitor_Scraper.py`
8. Navigatie toevoegen in `app.py` (link naar nieuwe pagina in sidebar)

**Eerste testbare milestone: na Fase 3**
→ Je kunt een beurs-URL invoeren, de agent scraped de exposantenlijst, filtert automatisch, en toont het resultaat in de Streamlit UI.

### Fase 4: Review UI
9. `pages/5_Exhibitor_Review.py`

### Fase 5: Enrichment Agent (Stap 2)
10. `exhibitor_scraper/enrichment_agent.py`
11. Verrijking-knoppen integreren in Review-pagina

### Fase 6: Excel Export
12. Export-functionaliteit koppelen aan Review-pagina
13. `openpyxl` toevoegen aan `requirements.txt`

---

## Dependencies toe te voegen

In `streamlit-app/requirements.txt`:
```
openpyxl    # Excel export
```
(Anthropic, playwright, en overige deps zijn al geïnstalleerd)

---

## Kosteninschatting per run

- **Stap 1 (scrapen):** ~€0.20-0.80 per beurs (afhankelijk van aantal pagina's/exposanten)
  - Claude Sonnet: ~$3/M input, ~$15/M output tokens
  - Screenshots (base64 PNG) zijn de grootste kostenfactor
  - 50 acties × ~2000 tokens per screenshot = ~100K tokens ≈ $0.30 input
  - Agent output: ~20K tokens ≈ $0.30
- **Stap 2 (verrijking):** ~€0.10-0.50 per batch van 20-80 bedrijven
  - Max 5 acties × 80 bedrijven = 400 acties, maar veel minder in praktijk
  - Meeste bedrijven hebben website al → alleen telefoon/email opzoeken

---

## Wat dit plan NIET bevat (bewust)

- Geen integratie met de bestaande Discovery-agent
- Geen contactpersonen zoeken (te onbetrouwbaar)
- Geen HubSpot-integratie (dat is een aparte stap na Excel-export)
- Geen automatische beurs-selectie (de gebruiker levert de URL)
- Geen OCR of afbeelding-analyse
- Geen proxy-rotatie of anti-bot bypasses
