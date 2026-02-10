"""
Claude Computer Use Agent for Trade Fair Discovery
Python implementation using the Anthropic SDK.
"""

import asyncio
import json
import re
import socket
import time
from typing import Optional, List, Dict, Any, Callable
from urllib.parse import urlparse, urljoin

import anthropic

from .browser_controller import BrowserController, DownloadedFile
from .schemas import (
    DiscoveryOutput, TestCaseInput, create_empty_output,
    ScheduleEntry, ActionLogEntry, DownloadedFileInfo, output_to_dict,
    ContactEmail, ContactInfo
)
from .document_classifier import DocumentClassifier, ClassificationResult


SYSTEM_PROMPT = """Je bent een expert onderzoeksagent die exhibitor documenten vindt op beurs websites. Je doel is om 99% van de gevraagde informatie te vinden.

=== JOUW MISSIE ===
Vind ALLE documenten en informatie die standbouwers nodig hebben. Wees GRONDIG - de meeste beurzen HEBBEN deze documenten, je moet ze alleen VINDEN.

=== KRITIEKE ZOEKSTRATEGIE ===

**STAP 1: Identificeer de juiste secties (meerdere paden proberen!)**
Zoek naar ALLE van deze menu-items/links:
- "For Exhibitors" / "Exhibitors" / "Aussteller" / "Espositori" / "Participate" / "Partecipare"
- "Planning" / "Preparation" / "Services" / "Information"
- "Technical" / "Regulations" / "Guidelines" / "Rules"
- "Stand Design" / "Stand Construction" / "Booth" / "Standbau"
- "Downloads" / "Documents" / "Documentation" / "Downloadcenter"

**STAP 2: Zoek naar verborgen document-secties**
Veel websites verstoppen documenten achter:
- Accordion/dropdown secties (klik op + of ▼ icons)
- "Technical regulations" / "Regolamento tecnico" / "Technische Richtlinien"
- "Provisions for stand design" / "Stand fitting regulations"
- "Sustainable set-up" / "Green guidelines"
- Subsecties binnen "Participate" of "How to exhibit"

**STAP 3: Check ALLE PDF links op elke pagina**
Na elke navigatie krijg je PDF links. ANALYSEER ze op:
- Bestandsnamen met: "technical", "regulation", "provision", "manual", "guide", "plan", "richtlin"
- CMS-paden zoals: /sites/default/files/, /content/dam/, /documents/, /downloads/
- Jaarnummers in bestandsnaam (bijv. "2026", "Rev_02")

**STAP 4: Probeer alternatieve URL-patronen**
Als je de hoofdsite hebt gevonden, probeer ook:
- exhibitors.[domain] of aussteller.[domain]
- [domain]/en/exhibitors of [domain]/exhibitors
- [domain]/en/participate of [domain]/services

**STAP 5: VOLG EXTERNE LINKS NAAR EXHIBITOR PORTALS! (KRITIEK!)**
Veel beurzen hebben hun exhibitor documenten op EXTERNE platforms:
- "Online Event Manual" (OEM) - vaak op Salesforce (my.site.com)
- "Client Portal" of "Exhibitor Portal" - kunnen externe domeinen zijn
- Links naar "Stand Build Rules", "Technical Manual", "Event Manual"

⚠️ ALS JE LINKS ZIET NAAR:
- my.site.com, salesforce.com, force.com
- cvent.com, a2zinc.net, expocad
- Elke link met "event manual", "OEM", "exhibitor manual/guide"

→ VOLG DEZE LINKS MET goto_url! Ze bevatten vaak ALLE belangrijke documenten.
→ Probeer de pagina te openen - veel van deze pagina's zijn PUBLIEK TOEGANKELIJK (geen login nodig)
→ Negeer NIET links alleen omdat ze naar een ander domein gaan!

=== VALIDATIE CRITERIA ===

**1. Floor Plan / Hall Plan (Plattegrond)**
✅ MOET BEVATTEN: Visuele layout van hallen, standposities, halnummers, ingangen
❌ MAG NIET: Stadskaart, routebeschrijving, hotelkaart
🔍 Zoekwoorden: "Geländeplan", "Hallenplan", "Floor plan", "Site plan", "Hall overview", "Exhibition map"

**2. Exhibitor Manual / Handbook (Exposanten Handleiding)**
✅ MOET BEVATTEN: Regels/voorschriften, opbouw/afbouw procedures, deadlines, logistiek, do's & don'ts
❌ MAG NIET: "Why exhibit" brochure, prijslijsten, sales materiaal
🔍 Zoekwoorden: "Service Documentation", "Exhibitor Guide", "Ausstellerhandbuch", "Provisions for stand design", "Stand fitting"

**3. Technical Guidelines / Rules (Technische Richtlijnen)**
✅ MOET BEVATTEN: Bouwhoogte, elektra specs, vloerbelasting, brandveiligheid, constructie-eisen
❌ MAG NIET: Algemene huisregels, prijslijsten
🔍 Zoekwoorden: "Technical Guidelines", "Technische Richtlinien", "Technical Regulations", "Regolamento Tecnico", "Stand Construction"

**4. Build-up & Tear-down Schedule (Schema)**
✅ MOET BEVATTEN: CONCRETE datums (DD-MM-YYYY), tijden (HH:MM), opbouw én afbouw
❌ MAG NIET: Vage info, alleen beursdagen
🔍 Zoekwoorden: "Set-up and dismantling", "Aufbau und Abbau", "Montaggio e smontaggio", "Timeline"

**5. Exhibitor Directory (Exposantenlijst)**
✅ MOET BEVATTEN: Lijst met bedrijfsnamen, bij voorkeur met standnummers
❌ MAG NIET: Sponsorlijst, één bedrijfsprofiel
🔍 Vaak op: /exhibitors, /catalogue, /espositori, subdomein exhibitors.xxx.com

=== BELANGRIJK: DIEP ZOEKEN ===

Als je een "Participate" of "For Exhibitors" sectie vindt:
1. Scroll de HELE pagina af
2. Klik op ALLE accordion/dropdown items
3. Zoek naar "Technical regulations" of "Sustainable set-up" subsecties
4. Check voor kleine PDF/download icons naast tekst

Als je een downloadcenter vindt:
1. Scroll door ALLE documenten
2. Let op bestandsnamen - niet alleen titels
3. "Provisions", "Regulations", "Technical" zijn vaak de juiste documenten

=== KRITIEK: GEBRUIK DE PDF LINKS! ===

Na elke actie krijg je "📄 PDF LINKS OP DEZE PAGINA".
GEBRUIK DEZE URLS DIRECT - je hoeft NIET te klikken om ze te downloaden.

=== TOOLS ===

1. **computer** - voor screenshots en interactie
2. **goto_url** - DIRECT naar URL navigeren (gebruik voor subdomeinen, PDF links, en alternatieve paden)
3. **deep_scan** - GEBRUIK DIT! Scant de hele pagina, opent alle accordions/dropdowns, en toont ALLE PDF/document links. Gebruik dit op elke belangrijke pagina (Participate, For Exhibitors, Downloads, etc.)

⚠️ BELANGRIJK: Gebruik deep_scan op elke pagina waar je documenten verwacht! Het vindt verborgen links die je niet op de screenshot ziet.

=== SCHEDULE FORMAT ===

Voor build-up en tear-down, geef ALLE datums:
- Advanced set-up (vroege opbouw)
- Regular set-up (normale opbouw)
- Dismantling/Tear-down (afbouw)

Met: datum (YYYY-MM-DD), tijden (HH:MM-HH:MM), beschrijving

=== OUTPUT FORMAT ===

Geef je resultaten als JSON. BELANGRIJK:
- Gebruik de EXACTE URLs die je hebt gezien!
- Voeg validation_notes toe om te bewijzen dat elk document aan de criteria voldoet!

```json
{
  "floorplan_url": "https://exacte-url-die-je-zag.pdf",
  "floorplan_validation": "Bevat hallenplan met standposities en ingangen - VOLDOET",

  "exhibitor_manual_url": "https://exacte-url-die-je-zag.pdf",
  "exhibitor_manual_validation": "Bevat opbouw regels, deadlines en logistieke info - VOLDOET",

  "rules_url": "https://exacte-url-die-je-zag.pdf",
  "rules_validation": "Bevat elektra specs (16A/32A), bouwhoogte (4m max), brandveiligheid - VOLDOET",

  "exhibitor_directory_url": "https://exhibitors.beursnaam.de",
  "exhibitor_directory_validation": "Lijst met 500+ bedrijven, zoekfunctie aanwezig - VOLDOET",

  "downloads_page_url": "https://url-naar-downloadcenter",

  "schedule": {
    "build_up": [
      {"date": "2026-01-29", "time": "07:00-24:00", "description": "Advanced set-up"},
      {"date": "2026-01-31", "time": "07:00-24:00", "description": "Regular set-up"}
    ],
    "tear_down": [
      {"date": "2026-02-10", "time": "17:00-24:00", "description": "Afbouw"}
    ]
  },
  "schedule_validation": "Concrete datums gevonden: opbouw 29-31 jan, afbouw 10 feb met exacte tijden - VOLDOET",

  "notes": "Beschrijving van je zoekpad"
}
```

⚠️ KRITIEK:
- Gebruik null als je NIETS kunt vinden
- Gebruik null + "_validation": "NIET GEVONDEN: reden" als je wel iets vond maar het NIET aan criteria voldeed
- Voorbeeld: "exhibitor_manual_url": null, "exhibitor_manual_validation": "AFGEWEZEN: Gevonden doc was sales brochure, geen echte handleiding"

Accepteer NOOIT documenten die niet aan de criteria voldoen!"""


def build_focused_system_prompt(
    classification_result: Optional['ClassificationResult'] = None,
    missing_types: Optional[list] = None,
) -> str:
    """
    Build a dynamic, focused system prompt based on what's already found and what's missing.

    Instead of the full generic prompt, this creates a targeted prompt that:
    - Only includes validation criteria for MISSING document types
    - Adds specific search strategies based on what the classifier found
    - Reduces cognitive load on the agent by removing irrelevant sections
    """
    if not classification_result or not missing_types:
        return SYSTEM_PROMPT  # Fall back to generic prompt

    # Determine which document types still need to be found
    found_types = classification_result.found_types if classification_result else []

    # Base instructions (always included)
    prompt_parts = [
        """Je bent een expert onderzoeksagent die exhibitor documenten vindt op beurs websites.

=== JOUW MISSIE ===
Je zoekt SPECIFIEK naar de documenten die hieronder als MISSEND staan gemarkeerd.
De andere documenten zijn REEDS GEVONDEN en GEVALIDEERD - je hoeft die NIET meer te zoeken.

=== ZOEKSTRATEGIE ===

**STAP 1: Identificeer de juiste secties**
Zoek naar deze menu-items/links:
- "For Exhibitors" / "Exhibitors" / "Aussteller" / "Participate"
- "Planning" / "Preparation" / "Services" / "Information"
- "Downloads" / "Documents" / "Documentation" / "Downloadcenter"

**STAP 2: Zoek verborgen document-secties**
- Accordion/dropdown secties (klik op + of ▼ icons)
- Subsecties binnen "Participate" of "How to exhibit"

**STAP 3: Check PDF links op elke pagina**
- Bestandsnamen met relevante termen
- CMS-paden: /sites/default/files/, /content/dam/, /documents/
- Jaarnummers in bestandsnaam (2026)

**STAP 4: VOLG EXTERNE LINKS NAAR EXHIBITOR PORTALS!**
- "Online Event Manual" (OEM) - vaak op Salesforce (my.site.com)
- Links naar "Stand Build Rules", "Technical Manual", "Event Manual"
- VOLG deze links met goto_url!
"""
    ]

    # Add ONLY the validation criteria for MISSING types
    prompt_parts.append("\n=== VALIDATIE CRITERIA (alleen voor wat je zoekt) ===\n")

    criteria_map = {
        'floorplan': """**Floor Plan / Hall Plan (Plattegrond)**
✅ MOET BEVATTEN: Visuele layout van hallen, standposities, halnummers, ingangen
❌ MAG NIET: Stadskaart, routebeschrijving, hotelkaart
🔍 Zoekwoorden: "Geländeplan", "Hallenplan", "Floor plan", "Site plan", "Exhibition map"
""",
        'exhibitor_manual': """**Exhibitor Manual / Handbook (Exposanten Handleiding)**
✅ MOET BEVATTEN: Regels/voorschriften, opbouw/afbouw procedures, deadlines, logistiek, do's & don'ts
❌ MAG NIET: "Why exhibit" brochure, prijslijsten, sales materiaal
🔍 Zoekwoorden: "Service Documentation", "Exhibitor Guide", "Welcome Pack", "Provisions for stand design"
""",
        'rules': """**Technical Guidelines / Rules (Technische Richtlijnen)**
✅ MOET BEVATTEN: Bouwhoogte, elektra specs, vloerbelasting, brandveiligheid, constructie-eisen
❌ MAG NIET: Algemene huisregels, prijslijsten, VENUE-SPECIFIEKE regels (alleen beurs-specifiek!)
🔍 Zoekwoorden: "Technical Guidelines", "Technische Richtlinien", "Technical Regulations", "Stand Construction"
⚠️ BELANGRIJK: Zoek naar regels die SPECIFIEK voor deze beurs zijn, NIET generieke venue-regels!
""",
        'schedule': """**Build-up & Tear-down Schedule (Schema)**
✅ MOET BEVATTEN: CONCRETE datums (DD-MM-YYYY), tijden (HH:MM), opbouw én afbouw
❌ MAG NIET: Vage info, alleen beursdagen
🔍 Zoekwoorden: "Set-up and dismantling", "Aufbau und Abbau", "Timeline"
💡 TIP: Check of het Exhibitor Manual ook schema-informatie bevat!
""",
        'exhibitor_directory': """**Exhibitor Directory (Exposantenlijst)**
✅ MOET BEVATTEN: Lijst met bedrijfsnamen, bij voorkeur met standnummers
❌ MAG NIET: Sponsorlijst, één bedrijfsprofiel
🔍 Vaak op: /exhibitors, /catalogue, subdomein exhibitors.xxx.com
""",
    }

    for doc_type in missing_types:
        if doc_type in criteria_map:
            prompt_parts.append(criteria_map[doc_type])

    # Add search hints from classifier
    if classification_result.search_hints:
        prompt_parts.append("\n=== HINTS VAN PRE-SCAN ===\n")
        for hint in classification_result.search_hints:
            prompt_parts.append(f"💡 {hint}")

    if classification_result.extra_urls_to_scan:
        prompt_parts.append("\n📎 REFERENTIES UIT GEVONDEN DOCUMENTEN (bezoek deze!):")
        for url in classification_result.extra_urls_to_scan[:5]:
            prompt_parts.append(f"  → {url}")

    # Tools and output format
    prompt_parts.append("""
=== TOOLS ===

1. **computer** - voor screenshots en interactie
2. **goto_url** - DIRECT naar URL navigeren
3. **deep_scan** - Scant de hele pagina, opent alle accordions/dropdowns

=== OUTPUT FORMAT ===

Geef je resultaten als JSON met ALLEEN de missende documenten:

```json
{
  "floorplan_url": "https://exacte-url.pdf",
  "floorplan_validation": "Bevat hallenplan met standposities - VOLDOET",

  "notes": "Beschrijving van je zoekpad"
}
```

⚠️ KRITIEK:
- Gebruik null als je NIETS kunt vinden
- Gebruik null + "_validation": "NIET GEVONDEN: reden" als je het niet vond
- Accepteer NOOIT documenten die niet aan de criteria voldoen!
- NIET zoeken naar documenten die al gevonden zijn!""")

    return "\n".join(prompt_parts)


class ClaudeAgent:
    """Claude Computer Use agent for trade fair discovery."""

    # Discovery phases with typical durations (seconds) for progress estimation
    PHASES = [
        {"id": "url_lookup",    "label": "Website zoeken",           "pct_start": 0,  "pct_end": 10,  "est_secs": 10},
        {"id": "prescan",       "label": "Website scannen",          "pct_start": 10, "pct_end": 35,  "est_secs": 40},
        {"id": "portal_scan",   "label": "Portal detectie",          "pct_start": 35, "pct_end": 50,  "est_secs": 30},
        {"id": "classification","label": "Document classificatie",    "pct_start": 50, "pct_end": 65,  "est_secs": 25},
        {"id": "browser_agent", "label": "Browser verificatie",      "pct_start": 65, "pct_end": 90,  "est_secs": 90},
        {"id": "results",       "label": "Resultaten verwerken",     "pct_start": 90, "pct_end": 100, "est_secs": 5},
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_iterations: int = 40,
        debug: bool = False,
        on_status: Optional[Callable[[str], None]] = None,
        on_phase: Optional[Callable[[str], None]] = None
    ):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.browser = BrowserController(1024, 768)
        self.max_iterations = max_iterations
        self.debug = debug
        self.on_status = on_status or (lambda x: None)
        self.on_phase = on_phase or (lambda x: None)
        self._discovery_log: List[str] = []  # Detailed log for troubleshooting
        # Compact summary data collected during discovery for short shareable logs
        self._sd: Dict[str, Any] = {
            'prescan_pdfs': 0,
            'prescan_pages': 0,
            'prescan_emails': 0,
            'subdomains_checked': 0,
            'subdomains_found': [],
            'web_search_pdfs': 0,
            'web_search_portals': 0,
            'portal_probe_found': [],
            'portal_urls': [],
            'portals_scanned': [],  # [{url, sub_pages, page_types}]
            'classification': {},  # type -> {confidence, year, fair, url}
            'quality_gate': '',
            'quality_gate_passed': False,
            'skip_agent': False,
            'skip_agent_reason': '',
            'agent_iterations': 0,
            'warnings': [],
            'errors': [],
            # Site context for troubleshooting
            'key_pages_found': [],  # Important pages discovered on main site
            'pdf_types': {},  # type -> count (from prescan)
            'pdf_years': {},  # year -> count (from prescan)
            'has_login_portal': False,
            'site_features': [],  # Notable features: 'salesforce_oem', 'expocad', etc.
        }

    def _log(self, message: str) -> None:
        """Log a message and collect it for the discovery log."""
        timestamp = time.strftime('%H:%M:%S')
        if self.debug:
            print(f"[{timestamp}] {message}")
        else:
            print(message)
        self.on_status(message)
        self._discovery_log.append(f"[{timestamp}] {message}")

    async def _pre_scan_website(self, base_url: str, fair_name: str = "") -> Dict[str, Any]:
        """
        Pre-scan the website using Playwright to find documents.
        Uses a real browser with JavaScript execution to find dynamically loaded content.
        Also searches the web to discover exhibitor portals that may not be linked.
        This runs BEFORE the main Computer Use loop to find documents that might be hidden.
        """
        self._log("🔎 Pre-scanning website with Playwright (JavaScript enabled)...")

        results = {
            'pdf_links': [],
            'document_pages': [],
            'exhibitor_pages': [],
            'all_links': [],
            'emails': [],  # Discovered email addresses
            'exhibitor_portal_subdomains': []  # Verified exhibitor portal subdomains (e.g., exhibitors-seg.seafoodexpo.com)
        }

        parsed_base = urlparse(base_url)
        base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
        base_netloc = parsed_base.netloc

        # Extract fair-specific path (e.g., /en/eurocucina from the URL)
        fair_path = parsed_base.path.rstrip('/')
        fair_segments = [s for s in fair_path.split('/') if s]

        # URLs to try scanning
        urls_to_scan = [base_url]

        # === GENERATE INTELLIGENT SUBDOMAIN PATTERNS ===
        # Generate likely exhibitor portal subdomains based on fair name
        discovered_portals = []

        def generate_fair_abbreviation(name: str) -> List[str]:
            """Generate possible abbreviations from fair name."""
            abbreviations = []
            if not name:
                return abbreviations

            # Clean the name
            clean_name = name.lower().strip()
            words = clean_name.replace('-', ' ').replace('_', ' ').split()

            # Filter out common words (but keep 'expo' as it's often part of fair names like SEG)
            stop_words = {'the', 'of', 'and', 'for', 'in', 'at', 'de', 'der', 'die', 'das',
                         'il', 'la', 'le', 'del', 'della', 'di', 'fair', 'trade',
                         'show', 'exhibition', 'messe', 'fiera', 'salon', 'salone'}

            # Filter out years and numbers (e.g., "2026", "2025")
            significant_words = [w for w in words if w not in stop_words and not w.isdigit()]

            # Abbreviation from first letters (e.g., "Seafood Expo Global" -> "seg")
            if len(significant_words) >= 2:
                abbrev = ''.join(w[0] for w in significant_words if w)
                abbreviations.append(abbrev)

            # Short all-caps names are already abbreviations (e.g., "MWC", "ISE", "CES", "IBC")
            non_numeric_words = [w for w in words if not w.isdigit()]
            for w in non_numeric_words:
                if len(w) >= 2 and len(w) <= 5 and name.split()[0].isupper():
                    abbreviations.append(w)

            # First word if it's a distinctive name (e.g., "PROVADA" -> "provada")
            if non_numeric_words:
                first_word = non_numeric_words[0]
                if len(first_word) >= 4:
                    abbreviations.append(first_word)

            # Combined form for two-word names (e.g., "EuroCucina" -> "eurocucina")
            if len(non_numeric_words) == 1 and len(non_numeric_words[0]) >= 6:
                abbreviations.append(non_numeric_words[0])

            # === TRY COMMON VARIANTS ===
            # If fair name contains 'expo' but no location qualifier, try adding 'global'
            # Many fairs like "Seafood Expo" have portals at "exhibitors-seg.domain" (SEG = Seafood Expo Global)
            if 'expo' in words and 'global' not in words:
                variant_words = significant_words + ['global']
                if len(variant_words) >= 2:
                    abbrev_with_global = ''.join(w[0] for w in variant_words if w)
                    abbreviations.append(abbrev_with_global)

            return list(set(abbreviations))  # Remove duplicates

        abbreviations = generate_fair_abbreviation(fair_name)
        self._log(f"🔍 Generated fair abbreviations: {abbreviations}")

        # === DETECT RELATED DOMAINS ===
        # Many fairs have exhibitor portals on separate subdomains
        related_domains = []

        # Add discovered portals from web search
        related_domains.extend(discovered_portals)

        # Extract root domain (e.g., fieramilano.it from salonemilano.it)
        domain_parts = base_netloc.split('.')
        if len(domain_parts) >= 2:
            root_domain = '.'.join(domain_parts[-2:])  # e.g., fieramilano.it

            # Common exhibitor portal patterns
            exhibitor_subdomains = [
                f"exhibitors.{root_domain}",
                f"aussteller.{root_domain}",
                f"espositori.{root_domain}",
                f"expo.{root_domain}",
                f"services.{root_domain}",
            ]

            # === ADD FAIR-SPECIFIC SUBDOMAIN PATTERNS ===
            # Patterns like exhibitors-seg.seafoodexpo.com (abbreviation-based)
            current_year = '2026'
            previous_year = '2025'

            for abbrev in abbreviations:
                # Pattern: exhibitors-{abbrev}.domain (e.g., exhibitors-seg.seafoodexpo.com)
                exhibitor_subdomains.append(f"exhibitors-{abbrev}.{root_domain}")

                # Pattern: {abbrev}-exhibitors.domain
                exhibitor_subdomains.append(f"{abbrev}-exhibitors.{root_domain}")

                # Pattern: {abbrev}.domain (e.g., seg.seafoodexpo.com)
                exhibitor_subdomains.append(f"{abbrev}.{root_domain}")

                # Pattern: {abbrev}{year}.domain (e.g., seg2026.seafoodexpo.com)
                exhibitor_subdomains.append(f"{abbrev}{current_year}.{root_domain}")
                exhibitor_subdomains.append(f"{abbrev}{previous_year}.{root_domain}")

                # Pattern: portal-{abbrev}.domain
                exhibitor_subdomains.append(f"portal-{abbrev}.{root_domain}")

                # Pattern: {abbrev}-portal.domain
                exhibitor_subdomains.append(f"{abbrev}-portal.{root_domain}")

            # Special case: salonemilano.it -> fieramilano.it ecosystem
            if 'salonemilano' in base_netloc:
                exhibitor_subdomains.extend([
                    'exhibitors.fieramilano.it',
                    'www.fieramilano.it',
                ])

            # === VERIFY SUBDOMAINS EXIST ===
            # Quick HTTP HEAD check to see which subdomains respond
            # (DNS lookups aren't reliable - some sites use CDNs/proxies that don't resolve directly)
            import urllib.request
            import urllib.error
            verified_subdomains = []

            self._log(f"  Checking {len(exhibitor_subdomains)} potential exhibitor portal subdomains...")

            for subdomain in exhibitor_subdomains:
                try:
                    url = f"https://{subdomain}"
                    req = urllib.request.Request(url, method='HEAD')
                    req.add_header('User-Agent', 'Mozilla/5.0 (compatible; TradeFairBot/1.0)')
                    with urllib.request.urlopen(req, timeout=3) as response:
                        if response.status < 400:
                            verified_subdomains.append(subdomain)
                            self._log(f"    ✓ Found active portal: {subdomain}")
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout):
                    # Site doesn't exist or isn't accessible - skip
                    continue
                except Exception:
                    continue

            # Add verified subdomains to related domains AND exhibitor_pages
            # This ensures the agent is explicitly told to visit these portals
            for subdomain in verified_subdomains:
                portal_url = f"https://{subdomain}"
                related_domains.append(portal_url)
                results['exhibitor_portal_subdomains'].append(portal_url)
                # Also add to exhibitor_pages so agent sees them in the instructions
                if portal_url not in results['exhibitor_pages']:
                    results['exhibitor_pages'].insert(0, portal_url)  # Add at start for priority

            self._sd['subdomains_checked'] = len(exhibitor_subdomains)
            self._sd['subdomains_found'] = list(verified_subdomains)
            if verified_subdomains:
                self._log(f"  Found {len(verified_subdomains)} active exhibitor portal subdomains")

        # === WEB SEARCH FOR EXHIBITOR PORTALS ===
        # Search the web to find exhibitor manuals/portals that may not be linked from main site
        if fair_name:
            self._log(f"🔍 Searching web for exhibitor portals: {fair_name}...")
            web_search_results = await self._web_search_for_portals(fair_name)
            self._sd['web_search_pdfs'] = len(web_search_results.get('pdf_links', []))
            self._sd['web_search_portals'] = len(web_search_results.get('portal_urls', []))

            # Add found PDFs directly to pdf_links (these are high-value direct downloads)
            for pdf_url in web_search_results.get('pdf_links', []):
                existing_urls = [p['url'] if isinstance(p, dict) else p for p in results['pdf_links']]
                if pdf_url not in existing_urls:
                    # Determine type from URL
                    url_lower = pdf_url.lower()
                    if 'welcome' in url_lower or 'exhibitor' in url_lower or 'manual' in url_lower:
                        pdf_type = 'exhibitor_manual'
                    elif 'technical' in url_lower or 'regulation' in url_lower or 'guideline' in url_lower:
                        pdf_type = 'technical_guidelines'
                    elif 'floor' in url_lower or 'map' in url_lower or 'plan' in url_lower:
                        pdf_type = 'floorplan'
                    else:
                        pdf_type = 'unknown'

                    # Extract year from URL if present
                    year_match = re.search(r'20(2[4-9]|3[0-9])', pdf_url)
                    pdf_year = f"20{year_match.group(1)}" if year_match else None

                    # Add as dict format consistent with other pdf_links
                    results['pdf_links'].insert(0, {
                        'url': pdf_url,
                        'text': f"Web search: {pdf_url.split('/')[-1]}",
                        'type': pdf_type,
                        'year': pdf_year
                    })
                    self._log(f"    📥 Web search PDF ({pdf_type}): {pdf_url[:60]}...")

            # Add found portals to exhibitor_pages and urls_to_scan
            for portal_url in web_search_results.get('portal_urls', []):
                if portal_url not in results['exhibitor_pages']:
                    results['exhibitor_pages'].insert(0, portal_url)
                if portal_url not in urls_to_scan:
                    urls_to_scan.insert(1, portal_url)  # Add right after base URL
                    self._log(f"    🌐 Web search found portal: {portal_url}")

        # === PROBE COMMON PORTAL URL PATTERNS ===
        # Try known portal URL patterns based on the fair's domain/org name
        if fair_name:
            self._log(f"🔍 Probing common portal URL patterns...")
            probed_portals = await self._probe_portal_urls(base_url, fair_name)
            self._sd['portal_probe_found'] = list(probed_portals)
            for portal_url in probed_portals:
                if portal_url not in results['exhibitor_pages']:
                    results['exhibitor_pages'].insert(0, portal_url)
                if portal_url not in urls_to_scan:
                    urls_to_scan.insert(1, portal_url)

        # === PRIORITIZE DOCUMENT PAGES ===
        # These pages are most likely to have technical documents - scan them FIRST
        priority_document_paths = [
            # Technical document pages (HIGHEST PRIORITY - often have the PDFs we need)
            '/en/technical-regulations', '/technical-regulations',
            '/en/sustainable-set-up', '/sustainable-set-up',
            '/en/technical-guidelines', '/technical-guidelines',
            '/en/fiere-e-eventi/esporre',  # Italian fairs often use this
            '/regolamento-tecnico', '/it/regolamento-tecnico',
            '/technische-richtlinien', '/de/technische-richtlinien',
        ]

        # Add priority document pages FIRST (right after base URL)
        for path in priority_document_paths:
            urls_to_scan.append(f"{base_domain}{path}")

        # Add related domain root pages
        for domain in related_domains:
            urls_to_scan.append(domain)

        # Add common exhibitor/service page patterns (lower priority)
        generic_paths = [
            # English
            '/en/exhibitors', '/exhibitors', '/en/participate', '/participate',
            '/en/services', '/services', '/en/downloads', '/downloads',
            '/en/information', '/information', '/en/planning', '/planning',
            '/for-exhibitors', '/en/for-exhibitors',
            '/en/stand-construction', '/stand-construction',
            '/en/exhibitor-services', '/exhibitor-services',
            '/exhibitor-info', '/exhibitor-resources', '/exhibitor-guide',
            '/exhibitor-list', '/exhibitor-directory',
            '/venue-information', '/logistics',
            # German
            '/aussteller', '/de/aussteller', '/technik', '/de/technik',
            '/de/downloads', '/de/aussteller-services',
            # French
            '/fr/exposants', '/exposants', '/fr/participer', '/participer',
            '/fr/services', '/fr/telechargements',
            '/fr/reglement-technique',
            # Spanish
            '/es/expositores', '/expositores', '/es/participar', '/participar',
            '/es/servicios', '/es/descargas',
            # Dutch
            '/nl/exposanten', '/exposanten', '/nl/deelnemen', '/deelnemen',
            '/nl/diensten', '/nl/downloads',
            # Italian
            '/espositori', '/it/espositori', '/partecipare', '/it/partecipare',
        ]

        # Add fair-specific paths (e.g., /en/eurocucina/exhibitors)
        fair_specific_suffixes = [
            '/exhibitors', '/participate', '/services', '/downloads',
            '/information', '/planning', '/technical', '/regulations',
            '/stand-design', '/documents', '/for-exhibitors',
            '/technical-regulations', '/sustainable-set-up',
        ]

        # Add generic paths to base domain
        for path in generic_paths:
            urls_to_scan.append(f"{base_domain}{path}")

        # Add fair-specific paths (important for sites like salonemilano.it)
        if fair_path:
            for suffix in fair_specific_suffixes:
                urls_to_scan.append(f"{base_domain}{fair_path}{suffix}")

            # Also try parent paths with suffixes
            if len(fair_segments) >= 2:
                parent_path = '/' + '/'.join(fair_segments[:-1])
                for suffix in fair_specific_suffixes:
                    urls_to_scan.append(f"{base_domain}{parent_path}{suffix}")

        # Remove duplicates while preserving order
        seen = set()
        urls_to_scan = [x for x in urls_to_scan if not (x in seen or seen.add(x))]

        self._log(f"Pre-scan will check {len(urls_to_scan)} URLs (including {len(related_domains)} related domains)")

        # Keywords that indicate important document links
        doc_keywords = [
            'technical', 'regulation', 'provision', 'guideline', 'manual',
            'handbook', 'richtlin', 'regolamento', 'standbau', 'construction',
            'setup', 'dismant', 'aufbau', 'abbau', 'montaggio', 'allestimento',
            'floor', 'plan', 'hall', 'gelaende', 'exhibitor', 'aussteller',
        ]

        found_pages_to_scan = []  # Pages found that we should also scan

        # Create a lightweight browser for pre-scanning
        pre_scan_browser = BrowserController(800, 600)  # Smaller viewport for speed

        try:
            await pre_scan_browser.launch()
            self._log("Pre-scan browser launched")

            # First pass: scan initial URLs
            for url in urls_to_scan[:20]:  # Increased limit to ensure document pages are scanned
                try:
                    await pre_scan_browser.goto(url)
                    await asyncio.sleep(0.5)  # Let JavaScript execute

                    current_state = await pre_scan_browser.get_state()
                    self._log(f"  ✓ Scanning: {url}")

                    # Get all links (this expands accordions and extracts with JS)
                    relevant_links = await pre_scan_browser.get_relevant_links()

                    # Extract email addresses from this page
                    page_emails = await pre_scan_browser.extract_emails()
                    for email_info in page_emails:
                        # Avoid duplicates
                        if email_info.email not in [e['email'] for e in results['emails']]:
                            results['emails'].append({
                                'email': email_info.email,
                                'context': email_info.context,
                                'source_type': email_info.source_type,
                                'source_url': url
                            })
                            self._log(f"    📧 Found email: {email_info.email}")

                    # Extract external portal URLs from page HTML source
                    # This catches URLs hidden in JavaScript, data attributes, or dynamic content
                    portal_urls_from_html = await pre_scan_browser.extract_external_portal_urls()
                    for portal_info in portal_urls_from_html:
                        portal_url = portal_info['url']

                        # FileDownload URLs are PDFs, not exhibitor pages
                        if portal_info.get('is_file_download'):
                            if portal_url not in [p['url'] for p in results['pdf_links']]:
                                results['pdf_links'].append({
                                    'url': portal_url,
                                    'text': f"Portal file: {portal_url.split('file=')[-1][:20] if 'file=' in portal_url else ''}",
                                    'type': 'unknown',
                                    'year': None,
                                    'source_page': url
                                })
                                self._log(f"    📄 Portal file download: {portal_url[:70]}")
                        elif portal_url not in results['exhibitor_pages']:
                            results['exhibitor_pages'].insert(0, portal_url)
                            if portal_url not in [u for u in found_pages_to_scan]:
                                found_pages_to_scan.append(portal_url)
                            self._log(f"    🔗 Portal URL in HTML source: {portal_url[:70]}")

                    # Process PDF links
                    for link in relevant_links.get('pdf_links', []):
                        if link.url not in [p['url'] for p in results['pdf_links']]:
                            lower_url = link.url.lower()
                            lower_text = link.text.lower()

                            # Detect year from URL or text (prioritize current/future years)
                            doc_year = None
                            for year in ['2026', '2025', '2024', '2023', '2022']:
                                if year in link.url or year in link.text:
                                    doc_year = year
                                    break

                            # Determine document type from URL and text
                            doc_type = 'unknown'
                            if any(kw in lower_url or kw in lower_text for kw in ['technical', 'regulation', 'richtlin', 'regolamento', 'reg.', 'reg_', 'tecnic']):
                                doc_type = 'technical_guidelines'
                            elif any(kw in lower_url or kw in lower_text for kw in ['provision', 'stand', 'design', 'fitting', 'allestimento', 'smm_', 'manual', 'handbook', 'handbuch']):
                                doc_type = 'exhibitor_manual'
                            elif any(kw in lower_url or kw in lower_text for kw in ['floor', 'plan', 'hall', 'gelaende', 'site', 'map', 'layout']):
                                # Exclude documents that aren't actual floor plans
                                is_not_floorplan = any(excl in lower_url or excl in lower_text for excl in [
                                    'technical', 'data sheet', 'datasheet', 'evacuation', 'emergency',
                                    'safety', 'regulation', 'provision', 'guideline', 'specification',
                                    'spec', 'elettric', 'electric', 'water', 'gas', 'service'
                                ])
                                if not is_not_floorplan:
                                    doc_type = 'floorplan'
                            elif any(kw in lower_url or kw in lower_text for kw in ['schedule', 'timeline', 'aufbau', 'montaggio', 'calendar', 'abbau', 'dismant']):
                                doc_type = 'schedule'

                            results['pdf_links'].append({
                                'url': link.url,
                                'text': link.text,
                                'type': doc_type,
                                'year': doc_year,
                                'source_page': url
                            })
                            year_info = f" [{doc_year}]" if doc_year else ""
                            self._log(f"    📄 Found PDF{year_info}: {link.text[:40] or link.url[:60]}...")

                    # Process high-value document links (expand them!)
                    for link in relevant_links.get('high_value_links', []):
                        if link.url not in [p['url'] for p in results['pdf_links']]:
                            lower_url = link.url.lower()
                            lower_text = link.text.lower()

                            if '.pdf' in lower_url or 'download' in lower_url or '/files/' in lower_url:
                                # Detect year
                                doc_year = None
                                for year in ['2026', '2025', '2024', '2023', '2022']:
                                    if year in link.url or year in link.text:
                                        doc_year = year
                                        break

                                doc_type = 'unknown'
                                if any(kw in lower_url or kw in lower_text for kw in ['technical', 'regulation', 'richtlin', 'regolamento']):
                                    doc_type = 'technical_guidelines'
                                elif any(kw in lower_url or kw in lower_text for kw in ['provision', 'stand', 'design', 'manual', 'handbook']):
                                    doc_type = 'exhibitor_manual'

                                results['pdf_links'].append({
                                    'url': link.url,
                                    'text': link.text,
                                    'type': doc_type,
                                    'year': doc_year,
                                    'source_page': url
                                })
                                self._log(f"    ⭐ High-value doc: {link.text[:40]}...")

                    # === DISCOVER EXHIBITOR PORTAL SUBDOMAINS ===
                    # Look for links to external exhibitor portals (e.g., exhibitors-seg.seafoodexpo.com)
                    # Also detect external event management platforms (Salesforce, etc.)
                    for link in relevant_links.get('all_links', []):
                        try:
                            link_parsed = urlparse(link.url)
                            link_host = link_parsed.netloc.lower()

                            # Skip same domain
                            if link_host == base_netloc.lower():
                                continue

                            # Skip common non-portal external links
                            skip_domains = ['google.', 'facebook.', 'twitter.', 'linkedin.', 'youtube.',
                                          'instagram.', 'pinterest.', 'tiktok.', 'apple.com', 'play.google']
                            if any(skip in link_host for skip in skip_domains):
                                continue

                            link_text_lower = (link.text or '').lower()
                            link_url_lower = link.url.lower()

                            # Check if this looks like an exhibitor portal subdomain
                            exhibitor_portal_indicators = [
                                'exhibitor', 'aussteller', 'espositori', 'exposant',
                                'expo.', 'portal', 'services.', 'booth', 'stand'
                            ]

                            is_exhibitor_portal = any(ind in link_host for ind in exhibitor_portal_indicators)

                            # === NEW: Detect external event management platforms ===
                            # Salesforce community sites, event platforms, etc.
                            external_platform_indicators = [
                                'my.site.com',      # Salesforce community
                                'force.com',        # Salesforce
                                'salesforce.com',   # Salesforce
                                'cvent.com',        # Cvent event platform
                                'eventbrite.',      # Eventbrite
                                'a2zinc.net',       # A2Z event platform
                                'expocad.',         # ExpoCad
                                'expofp.',          # ExpoFP
                                'map-dynamics.',    # Map Dynamics
                                'n200.com',         # Nth Degree events
                                'mapyourshow.com',  # Map Your Show
                                'smallworldlabs.com', # Small World Labs
                                'swapcard.com',     # Swapcard
                                'grip.events',      # Grip
                                'ungerboeck',       # Ungerboeck
                            ]

                            is_external_platform = any(plat in link_host for plat in external_platform_indicators)

                            # === NEW: Keywords that indicate important exhibitor resources ===
                            # These links should ALWAYS be followed even if on external domains
                            high_value_keywords = [
                                'event manual', 'online event manual', 'oem',
                                'exhibitor manual', 'exhibitor handbook', 'exhibitor guide',
                                'stand build', 'stand construction', 'stand regulations',
                                'technical manual', 'technical guidelines', 'technical regulations',
                                'build-up', 'build up', 'dismant', 'tear-down', 'tear down',
                                'rules and regulations', 'exhibitor resource', 'exhibitor service',
                                'standbau', 'aufbau', 'abbau', 'montaggio', 'allestimento',
                            ]

                            text_has_high_value = any(kw in link_text_lower for kw in high_value_keywords)
                            url_has_high_value = any(kw.replace(' ', '') in link_url_lower.replace('-', '').replace('_', '')
                                                    for kw in high_value_keywords)

                            # Also check if link text suggests exhibitor portal
                            text_suggests_portal = any(kw in link_text_lower for kw in [
                                'exhibitor portal', 'exhibitor service', 'for exhibitors',
                                'booth', 'stand design', 'technical', 'regulations',
                                'client portal', 'participant portal', 'vendor portal'
                            ])

                            # Determine if we should follow this link
                            should_follow = (
                                is_exhibitor_portal or
                                is_external_platform or
                                text_has_high_value or
                                url_has_high_value or
                                text_suggests_portal
                            )

                            if should_follow:
                                # For high-value links, add the full URL (not just the domain)
                                if text_has_high_value or url_has_high_value:
                                    if link.url not in found_pages_to_scan:
                                        found_pages_to_scan.append(link.url)
                                        self._log(f"    📚 Found event manual/resource link: {link.text[:40] if link.text else link_host}...")
                                else:
                                    portal_url = f"{link_parsed.scheme}://{link_parsed.netloc}"
                                    if portal_url not in found_pages_to_scan:
                                        found_pages_to_scan.append(portal_url)
                                        self._log(f"    🌐 Discovered external portal: {link_host}")
                        except:
                            continue

                    # Collect document-related pages for second pass (including cross-domain)
                    # Check ALL links, not just exhibitor/download links
                    all_page_links = (
                        relevant_links.get('exhibitor_links', []) +
                        relevant_links.get('download_links', []) +
                        relevant_links.get('high_value_links', []) +
                        relevant_links.get('all_links', [])[:50]  # Sample of all links
                    )

                    # Remove duplicates
                    seen_urls = set()
                    unique_links = []
                    for link in all_page_links:
                        if link.url not in seen_urls:
                            seen_urls.add(link.url)
                            unique_links.append(link)

                    for link in unique_links:
                        lower_url = link.url.lower()
                        lower_text = link.text.lower() if link.text else ''

                        # Skip listing pages (exhibitor directories with pagination)
                        if '?pagenumber=' in lower_url or '?anno=' in lower_url or '?page=' in lower_url:
                            continue

                        # Skip already processed PDFs
                        if '.pdf' in lower_url:
                            continue

                        # Skip individual exhibitor company pages (e.g., /exhibitors/34391-gsma)
                        # These are company profiles, not document pages
                        if re.search(r'/exhibitors?/\d+-', lower_url):
                            continue

                        # Strip URL fragments for deduplication (e.g., /page#content vs /page)
                        defragged_url = link.url.split('#')[0]
                        if defragged_url != link.url:
                            # This URL has a fragment; skip if we already have the base URL
                            if defragged_url in seen_urls:
                                continue

                        # Skip noise: login, auth, password, dashboard, admin pages
                        noise_patterns = [
                            '#cookies', '#maincontent', '#content',
                            '/login', '/signin', '/sign-in', '/auth',
                            '/password', '/forgot-password', '/reset-password',
                            '/account-recovery', '/secur/',
                            '/dashboard', '/admin', '/api/',
                            '/search?', '/find?', '/query?',
                            '/confirmation', '/thank-you', '/success',
                            '/mymwc?', 'next=',
                            '/print/', '/share/',
                            '/404', '/error',
                            '/cart', '/checkout', '/payment',
                        ]
                        if any(pat in lower_url for pat in noise_patterns):
                            continue

                        # Check if URL OR TEXT contains document keywords
                        # This catches links like "Technical regulations" -> /en/technical-regulations
                        url_has_keyword = any(kw in lower_url for kw in doc_keywords)
                        text_has_keyword = any(kw in lower_text for kw in doc_keywords)

                        # Also check for specific page patterns that often have documents
                        is_document_page = any(pattern in lower_url for pattern in [
                            'technical-regulation', 'sustainable', 'stand-design',
                            'provision', 'guideline', 'regolamento', 'richtlin',
                            'exhibitor-service', 'download', 'document',
                            '/esporre', '/exhibit', '/partecipa',
                            'deadline', 'floorplan', 'floor-plan',
                            'general-regulation', 'voorschrift', 'standbouw',
                        ])

                        if url_has_keyword or text_has_keyword or is_document_page:
                            if link.url not in results['exhibitor_pages']:
                                results['exhibitor_pages'].append(link.url)

                                # Allow same domain or related exhibitor portals
                                # More permissive to catch event-specific portals like exhibitors-seg.seafoodexpo.com
                                link_host = urlparse(link.url).netloc.lower()
                                is_related_domain = (
                                    base_netloc in link.url or  # Same domain
                                    '/content/dam/' in link.url or  # CMS content
                                    any(pattern in link_host for pattern in [
                                        'exhibitor', 'aussteller', 'espositori', 'exposant',
                                        'portal', 'services', 'booth', 'stand'
                                    ]) or
                                    # Check if shares root domain
                                    (len(base_netloc.split('.')) >= 2 and
                                     '.'.join(base_netloc.split('.')[-2:]) in link_host)
                                )

                                if is_related_domain and link.url not in urls_to_scan:
                                    found_pages_to_scan.append(link.url)
                                    self._log(f"    🔗 Found document page: {link.text[:30] if link.text else link.url[:40]}...")

                except Exception as e:
                    # Silently skip failed URLs
                    continue

            # Second pass: scan discovered document pages (might contain hidden PDFs)
            scanned_in_second_pass = 0
            for url in found_pages_to_scan[:15]:  # Increased limit for cross-domain pages
                try:
                    # Skip already scanned URLs
                    if url in urls_to_scan[:20]:
                        continue

                    # Skip listing pages, individual company profiles, fragments, and login redirects
                    lower_url = url.lower()
                    if '?pagenumber=' in lower_url or '?anno=' in lower_url or '?page=' in lower_url:
                        continue
                    if re.search(r'/exhibitors?/\d+-', lower_url):
                        continue
                    if '#cookies' in lower_url or '#maincontent' in lower_url:
                        continue
                    if '/mymwc?' in lower_url or 'next=' in lower_url:
                        continue

                    await pre_scan_browser.goto(url)
                    await asyncio.sleep(0.5)
                    scanned_in_second_pass += 1

                    self._log(f"  ✓ Second-pass scan: {url}")

                    # Extract external portal URLs from page HTML (catches hidden portal links)
                    portal_urls_from_html = await pre_scan_browser.extract_external_portal_urls()
                    for portal_info in portal_urls_from_html:
                        portal_url = portal_info['url']

                        # FileDownload URLs are PDFs, not exhibitor pages
                        if portal_info.get('is_file_download'):
                            if portal_url not in [p['url'] for p in results['pdf_links']]:
                                results['pdf_links'].append({
                                    'url': portal_url,
                                    'text': f"Portal file: {portal_url.split('file=')[-1][:20] if 'file=' in portal_url else ''}",
                                    'type': 'unknown',
                                    'year': None,
                                    'source_page': url
                                })
                                self._log(f"    📄 Portal file download (2nd pass): {portal_url[:70]}")
                        elif portal_url not in results['exhibitor_pages']:
                            results['exhibitor_pages'].insert(0, portal_url)
                            self._log(f"    🔗 Portal URL in HTML source (2nd pass): {portal_url[:70]}")

                    relevant_links = await pre_scan_browser.get_relevant_links()

                    for link in relevant_links.get('pdf_links', []):
                        if link.url not in [p['url'] for p in results['pdf_links']]:
                            lower_url = link.url.lower()
                            lower_text = link.text.lower()

                            # Detect year
                            doc_year = None
                            for year in ['2026', '2025', '2024', '2023', '2022']:
                                if year in link.url or year in link.text:
                                    doc_year = year
                                    break

                            doc_type = 'unknown'
                            if any(kw in lower_url or kw in lower_text for kw in ['technical', 'regulation', 'richtlin', 'regolamento']):
                                doc_type = 'technical_guidelines'
                            elif any(kw in lower_url or kw in lower_text for kw in ['provision', 'stand', 'design', 'fitting', 'allestimento', 'manual', 'handbook']):
                                doc_type = 'exhibitor_manual'
                            elif any(kw in lower_url or kw in lower_text for kw in ['floor', 'plan', 'hall', 'gelaende']):
                                # Exclude documents that aren't actual floor plans
                                is_not_floorplan = any(excl in lower_url or excl in lower_text for excl in [
                                    'technical', 'data sheet', 'datasheet', 'evacuation', 'emergency',
                                    'safety', 'regulation', 'provision', 'guideline', 'specification',
                                    'spec', 'elettric', 'electric', 'water', 'gas', 'service'
                                ])
                                if not is_not_floorplan:
                                    doc_type = 'floorplan'
                            elif any(kw in lower_url or kw in lower_text for kw in ['schedule', 'timeline', 'aufbau', 'montaggio']):
                                doc_type = 'schedule'

                            results['pdf_links'].append({
                                'url': link.url,
                                'text': link.text,
                                'type': doc_type,
                                'year': doc_year,
                                'source_page': url
                            })
                            year_info = f" [{doc_year}]" if doc_year else ""
                            self._log(f"    📄 Found PDF{year_info} (2nd pass): {link.text[:40] or link.url[:60]}...")

                    # Also check high-value links in second pass
                    for link in relevant_links.get('high_value_links', []):
                        if link.url not in [p['url'] for p in results['pdf_links']]:
                            lower_url = link.url.lower()
                            if '.pdf' in lower_url or 'download' in lower_url or '/files/' in lower_url:
                                # Detect year
                                doc_year = None
                                for year in ['2026', '2025', '2024', '2023', '2022']:
                                    if year in link.url or year in link.text:
                                        doc_year = year
                                        break

                                results['pdf_links'].append({
                                    'url': link.url,
                                    'text': link.text,
                                    'type': 'unknown',
                                    'year': doc_year,
                                    'source_page': url
                                })
                                year_info = f" [{doc_year}]" if doc_year else ""
                                self._log(f"    ⭐ High-value{year_info} (2nd): {link.text[:40]}...")

                except Exception:
                    continue

        except Exception as e:
            self._log(f"Pre-scan error: {e}")
        finally:
            await pre_scan_browser.close()
            self._log("Pre-scan browser closed")

        self._log(f"🎯 Pre-scan complete: {len(results['pdf_links'])} PDFs, {len(results['exhibitor_pages'])} exhibitor pages")
        return results

    def _find_portal_urls(self, pre_scan_results: Dict, fair_name: str = "") -> List[str]:
        """
        Find external portal URLs from prescan results.
        These are URLs on external platforms (Salesforce, OEM portals, etc.)
        that likely contain exhibitor information as web pages.

        Filters out Salesforce infrastructure URLs and FileDownload links.
        Prefers /s/Home as entry point per portal.
        Sorts portals by relevance to fair name (matching abbreviations first).
        """
        from .browser_controller import BrowserController

        portal_indicators = [
            'my.site.com',         # Salesforce community
            'cvent.com',           # Cvent
            'a2zinc.net',          # A2Z
            'expocad.',            # ExpoCad
            'expofp.',             # ExpoFP
            'smallworldlabs.com',  # SWL
            'eventbrite.',         # Eventbrite
            'map-dynamics.',       # Map Dynamics
            'n200.com',            # Nth Degree
            'mapyourshow.com',     # Map Your Show
            'swapcard.com',        # Swapcard
            'grip.events',         # Grip
            'ungerboeck',          # Ungerboeck
        ]

        # Collect all candidate URLs per dedup key (host + path prefix)
        candidates_by_key = {}  # dedup_key -> list of URLs

        def _collect_url(page_url: str):
            if BrowserController._is_salesforce_infrastructure_url(page_url):
                return
            if BrowserController._is_salesforce_file_download(page_url):
                return
            host = urlparse(page_url).netloc.lower()
            if not any(ind in host for ind in portal_indicators):
                return
            path = urlparse(page_url).path.strip('/')
            path_prefix = path.split('/')[0] if path else ''
            dedup_key = f"{host}/{path_prefix}"
            if dedup_key not in candidates_by_key:
                candidates_by_key[dedup_key] = []
            if page_url not in candidates_by_key[dedup_key]:
                candidates_by_key[dedup_key].append(page_url)

        # Check exhibitor pages for portal domains
        for page_url in pre_scan_results.get('exhibitor_pages', []):
            _collect_url(page_url)

        # Also check web search results if stored
        for pdf in pre_scan_results.get('pdf_links', []):
            source = pdf.get('source_page', '')
            if source:
                _collect_url(source)

        # Include verified exhibitor portal subdomains (e.g., exhibitors-seg.seafoodexpo.com)
        # These were discovered during prescan via subdomain probing and are rich portals
        for portal_url in pre_scan_results.get('exhibitor_portal_subdomains', []):
            host = urlparse(portal_url).netloc.lower()
            dedup_key = f"{host}/"
            if dedup_key not in candidates_by_key:
                candidates_by_key[dedup_key] = [portal_url]

        # For each dedup key, pick the best entry point URL
        # Prefer /s/Home over any other page
        portal_urls = []
        for dedup_key, urls in candidates_by_key.items():
            best_url = urls[0]  # Default: first found
            for url in urls:
                parsed_path = urlparse(url).path.lower().rstrip('/')
                if parsed_path.endswith('/s/home'):
                    best_url = url
                    break
            portal_urls.append(best_url)

        # Sort portals by relevance to fair name
        # Portals whose path/host contains fair abbreviation come first
        if fair_name:
            clean_name = re.sub(r'\s*20\d{2}\s*', '', fair_name).strip().lower()
            name_parts = clean_name.replace(' ', '').replace('-', '')
            # Collect match terms: abbreviation letters + significant words
            match_terms = set()
            if name_parts:
                match_terms.add(name_parts)
            words = clean_name.split()
            stop_words = {'the', 'of', 'and', 'for', 'in', 'at', 'de', 'fair', 'trade',
                         'show', 'exhibition', 'messe'}
            for w in words:
                if w not in stop_words and not w.isdigit() and len(w) >= 2:
                    match_terms.add(w)

            def _relevance_score(url: str) -> int:
                """Higher = more relevant to fair. Sort descending."""
                lower_url = url.lower()
                host = urlparse(url).netloc.lower()
                path = urlparse(url).path.lower()
                score = 0
                for term in match_terms:
                    if term in host:
                        score += 10  # Strong: fair name in hostname
                    if term in path:
                        score += 5   # Good: fair name in path
                # OEM portals (e.g., mwcoem, provadaoem) typically contain the richest
                # content: rules, schedules, manuals. Prioritize them.
                if 'oem' in path:
                    score += 8
                # Salesforce community portals with /s/ paths are interactive portals
                if '/s/' in path and 'my.site.com' in host:
                    score += 3
                return score

            portal_urls.sort(key=_relevance_score, reverse=True)

        return portal_urls

    async def _deep_scan_portals(self, portal_urls: List[str], fair_name: str) -> List[Dict]:
        """
        Deep scan external portals (Salesforce, OEM, etc.) to extract page content.

        Many fairs host critical info (rules, schedule) on external portals as web pages,
        not PDFs. This method visits those portals, follows internal links, and extracts
        page content for classification.

        Returns list of {url, text_content, page_title, detected_type} dicts.
        """
        portal_pages = []

        if not portal_urls:
            return portal_pages

        self._log(f"🔍 Portal deep scan: scanning {len(portal_urls)} portal(s)...")

        # Keywords that indicate pages worth scanning inside a portal
        page_keywords = [
            # Rules / regulations
            'rule', 'regulation', 'guideline', 'technical', 'construction',
            'stand build', 'stand design', 'provision', 'requirement',
            'richtlijn', 'richtlinien', 'vorschrift', 'regolamento',
            # Schedule
            'schedule', 'build-up', 'buildup', 'build up', 'tear-down', 'teardown',
            'dismantl', 'move-in', 'move-out', 'set-up', 'setup', 'timeline',
            'deadline', 'access policy', 'timetable',
            'aufbau', 'abbau', 'montage', 'démontage', 'opbouw', 'afbouw',
            # Manual / guide
            'manual', 'handbook', 'guide', 'welcome', 'exhibitor info',
            'service', 'documentation', 'resource',
            # Floor plan
            'floor plan', 'floorplan', 'hall plan', 'map', 'layout', 'venue',
        ]

        scan_browser = BrowserController(800, 600)
        try:
            await scan_browser.launch()

            for portal_url in portal_urls[:5]:  # Max 5 portals (OEM portals need priority)
                try:
                    self._log(f"  🌐 Scanning portal: {portal_url}")
                    await scan_browser.goto(portal_url)
                    await asyncio.sleep(3)  # Wait longer for SPA to render (Salesforce etc.)

                    portal_domain = urlparse(portal_url).netloc

                    # Extract the main page content
                    main_text = await scan_browser.extract_page_text(max_chars=10000)
                    main_title = (await scan_browser.get_state()).title

                    # If page has very little content, wait longer (SPA may still be loading)
                    if not main_text or len(main_text) < 200:
                        self._log(f"    ⏳ Page still loading, waiting extra 3s...")
                        await asyncio.sleep(3)
                        main_text = await scan_browser.extract_page_text(max_chars=10000)
                        main_title = (await scan_browser.get_state()).title

                    if main_text and len(main_text) > 100:
                        # Detect type from URL/content instead of always assuming exhibitor_manual
                        home_type = self._detect_page_type(portal_url, main_title or '', main_text)
                        if home_type == 'unknown':
                            home_type = 'exhibitor_manual'  # Default for portal home pages
                        portal_pages.append({
                            'url': portal_url,
                            'text_content': main_text,
                            'page_title': main_title,
                            'detected_type': home_type,
                        })
                        self._log(f"    📝 Extracted portal home page: {len(main_text)} chars")

                    # Get all links from the portal
                    relevant_links = await scan_browser.get_relevant_links()
                    all_links = relevant_links.get('all_links', [])

                    # Also add PDF links found on the portal
                    for link in relevant_links.get('pdf_links', []):
                        portal_pages.append({
                            'url': link.url,
                            'text_content': None,  # PDF - will be downloaded by classifier
                            'page_title': link.text,
                            'detected_type': 'pdf',
                            'is_pdf': True,
                        })

                    # Follow internal links that match document keywords
                    visited = {portal_url}
                    sub_pages_scanned = 0

                    for link in all_links:
                        if sub_pages_scanned >= 8:  # Max 8 sub-pages per portal
                            break

                        link_lower = (link.text or '').lower() + ' ' + link.url.lower()
                        link_domain = urlparse(link.url).netloc

                        # Only follow links on the same portal domain
                        if link_domain != portal_domain:
                            continue

                        # Skip already visited
                        if link.url in visited:
                            continue

                        # Check if the link text/URL contains relevant keywords
                        has_keyword = any(kw in link_lower for kw in page_keywords)
                        if not has_keyword:
                            continue

                        visited.add(link.url)

                        try:
                            await scan_browser.goto(link.url)
                            await asyncio.sleep(2)  # Wait for SPA render (Salesforce needs time)
                            sub_pages_scanned += 1

                            page_text = await scan_browser.extract_page_text(max_chars=10000)
                            page_state = await scan_browser.get_state()

                            if not page_text or len(page_text) < 100:
                                continue

                            # Detect what type of content this page has
                            detected_type = self._detect_page_type(link.url, link.text, page_text)

                            portal_pages.append({
                                'url': link.url,
                                'text_content': page_text,
                                'page_title': page_state.title or link.text,
                                'detected_type': detected_type,
                            })
                            self._log(f"    📄 Portal sub-page [{detected_type}]: {link.text or link.url[:50]} ({len(page_text)} chars)")

                            # Also check for PDFs on this sub-page
                            sub_links = await scan_browser.get_relevant_links()
                            for pdf_link in sub_links.get('pdf_links', []):
                                if pdf_link.url not in visited:
                                    portal_pages.append({
                                        'url': pdf_link.url,
                                        'text_content': None,
                                        'page_title': pdf_link.text,
                                        'detected_type': 'pdf',
                                        'is_pdf': True,
                                    })

                        except Exception as e:
                            self._log(f"    ⚠️ Could not scan sub-page: {link.url[:50]}: {e}")
                            continue

                    # After regular link scanning, try common schedule sub-page URL patterns.
                    # Salesforce SPAs and other portals often have schedule pages that aren't
                    # discoverable through standard link extraction (dynamic navigation, tabs, etc.)
                    schedule_already_found = any(
                        p.get('detected_type') == 'schedule' and p.get('text_content')
                        for p in portal_pages
                    )
                    if not schedule_already_found and 'my.site.com' in portal_domain:
                        # Extract portal base path (e.g., /mwcoem/s from /mwcoem/s/Home)
                        parsed_portal = urlparse(portal_url)
                        path_parts = parsed_portal.path.strip('/').split('/')
                        # For Salesforce: /{community}/s/... pattern
                        portal_base = None
                        for i, part in enumerate(path_parts):
                            if part == 's' and i > 0:
                                portal_base = f"{parsed_portal.scheme}://{portal_domain}/{'/'.join(path_parts[:i+1])}"
                                break
                        if not portal_base:
                            portal_base = f"{parsed_portal.scheme}://{portal_domain}/{'/'.join(path_parts[:2])}" if len(path_parts) >= 2 else None

                        if portal_base:
                            schedule_slug_candidates = [
                                'build-up-dismantling-schedule',
                                'build-up-schedule',
                                'build-up-dismantling',
                                'schedule',
                                'deadline',
                                'deadlines',
                                'access-policy',
                                'event-schedule',
                                'timetable',
                                'set-up-dismantling',
                                'setup-dismantling',
                            ]
                            self._log(f"    🔎 Probing {len(schedule_slug_candidates)} schedule URL patterns on portal...")
                            for slug in schedule_slug_candidates:
                                candidate_url = f"{portal_base}/{slug}"
                                if candidate_url in visited:
                                    continue
                                visited.add(candidate_url)
                                try:
                                    await scan_browser.goto(candidate_url)
                                    await asyncio.sleep(2)
                                    page_text = await scan_browser.extract_page_text(max_chars=10000)
                                    page_state = await scan_browser.get_state()

                                    if not page_text or len(page_text) < 100:
                                        continue

                                    # Check if this isn't just the portal home (redirect on 404)
                                    if page_state.url and page_state.url.rstrip('/') == portal_url.rstrip('/'):
                                        continue

                                    detected_type = self._detect_page_type(candidate_url, slug, page_text)
                                    portal_pages.append({
                                        'url': candidate_url,
                                        'text_content': page_text,
                                        'page_title': page_state.title or slug,
                                        'detected_type': detected_type,
                                    })
                                    self._log(f"    📅 Found schedule page via URL probe: {candidate_url[:60]} ({len(page_text)} chars)")
                                    break  # Found a schedule page, stop probing
                                except Exception:
                                    continue

                    self._log(f"  ✅ Portal scan complete: {sub_pages_scanned} sub-pages, {len([p for p in portal_pages if p.get('text_content')])} pages with content")

                    # Track portal scan summary
                    page_types = [p.get('detected_type', '?') for p in portal_pages
                                  if p.get('text_content') and urlparse(p.get('url', '')).netloc == portal_domain]
                    self._sd['portals_scanned'].append({
                        'url': portal_url,
                        'sub_pages': sub_pages_scanned,
                        'page_types': page_types,
                    })

                except Exception as e:
                    self._log(f"  ⚠️ Portal scan error for {portal_url[:50]}: {e}")
                    self._sd['warnings'].append(f"Portal scan error: {portal_url[:40]}: {e}")
                    continue

        finally:
            await scan_browser.close()

        return portal_pages

    def _detect_page_type(self, url: str, link_text: str, page_text: str) -> str:
        """Detect the document type of a web page based on URL, title, and content.

        Uses two-phase detection:
        1. URL/title indicators (highest priority - most reliable)
        2. Content analysis (fallback for ambiguous pages)
        """
        url_title = f"{url} {link_text or ''}".lower()

        # === PHASE 1: URL and title based detection (reliable, no content ambiguity) ===

        # Rules from URL/title
        if any(kw in url_title for kw in [
            'design-regulation', 'design regulation', 'technical-regulation',
            'technical regulation', 'technical-guideline', 'technical guideline',
            'stand-build-rule', 'stand build rule', 'construction-rule',
            'reglement-technique', 'regolamento-tecnico', 'reglamento-tecnico',
            'technische-richtlijn', 'standbouwregels',
        ]):
            return 'rules'

        # Schedule from URL/title
        if any(kw in url_title for kw in [
            'event-schedule', 'event schedule', 'build-up-schedule',
            'dismantling-schedule', 'tear-down-schedule', 'move-in-schedule',
            'setup-schedule', '/deadline', 'access-policy', 'timetable',
            'aufbau-und-abbau', 'opbouw-en-afbouw',
        ]):
            return 'schedule'

        # Floorplan from URL/title
        if any(kw in url_title for kw in [
            'floorplan', 'floor-plan', 'floor plan', 'expo-floorplan',
            'hall-plan', 'hallenplan', 'plattegrond', 'expocad', 'expofp', 'mapyourshow',
            'planimetria',
        ]):
            return 'floorplan'

        # Exhibitor manual from URL/title (checked AFTER specific types)
        if any(kw in url_title for kw in [
            'event-information', 'event information', 'event-guideline',
            'event guideline', 'exhibitor-manual', 'exhibitor manual',
            'exhibitor-handbook', 'exhibitor handbook', 'exhibitor-guide',
            'exhibitor guide', 'welcome-pack', 'event-manual',
            'exhibitor-info', 'exhibitor info',
            'ausstellerhandbuch', 'manuel-exposant', 'manual-del-expositor',
        ]):
            return 'exhibitor_manual'

        # === PHASE 2: Content analysis (for pages with generic URL/title) ===
        combined = f"{url_title} {page_text[:1500]}".lower()

        if any(kw in combined for kw in [
            'stand build rule', 'construction rule', 'technical guideline',
            'technical regulation', 'stand design rule', 'design regulation',
            'design rule', 'height limit', 'technical specification',
            'fire safety', 'construction requirement',
            'technische richtlinie', 'standbauvorgabe', 'bauvorschrift',
            'reglement technique', 'règlement technique',
            'reglamento tecnico', 'regulación técnica',
            'regolamento tecnico',
            'technische richtlijn', 'standbouwregels',
        ]):
            return 'rules'

        if any(kw in combined for kw in [
            'event schedule', 'build-up schedule', 'build up schedule',
            'dismantling schedule', 'tear-down schedule', 'move-in schedule',
            'set-up schedule', 'build-up & dismantl', 'installation & dismantl',
            'setup and dismantle', 'setup & dismantle',
            'aufbau und abbau', 'aufbauzeiten', 'abbauzeiten',
            'calendrier de montage', 'montage et démontage',
            'calendario de montaje', 'montaje y desmontaje',
            'calendario allestimento', 'allestimento e smontaggio',
            'opbouw en afbouw', 'opbouwschema',
        ]):
            return 'schedule'

        if any(kw in combined for kw in [
            'floor plan', 'floorplan', 'hall plan', 'site map', 'venue map',
            'exhibition layout', 'expo floorplan',
            'hallenplan', 'plattegrond', 'expocad', 'expofp', 'mapyourshow',
            'plan du salon', 'plan des halls',
            'plano de la feria', 'plano del recinto',
            'pianta del salone', 'planimetria',
        ]):
            return 'floorplan'

        if any(kw in combined for kw in [
            'exhibitor manual', 'exhibitor handbook', 'exhibitor guide',
            'welcome pack', 'event manual', 'event information',
            'exhibitor info', 'service documentation', 'exhibitor resource',
            'ausstellerhandbuch', 'ausstellerinformation',
            'manuel exposant', 'guide exposant',
            'manual del expositor', 'guía del expositor',
            'manuale espositore', 'guida espositore',
            'handleiding exposant', 'exposanten handleiding',
        ]):
            return 'exhibitor_manual'

        return 'unknown'

    async def _scan_document_references(self, urls: List[str]) -> List[Dict]:
        """
        Scan URLs found as references in classified documents.
        Returns any PDFs found on those pages.
        """
        found_pdfs = []

        for url in urls[:5]:  # Limit to 5 references
            try:
                parsed = urlparse(url)
                url_lower = url.lower()

                # If it's directly a PDF, add it
                if url_lower.endswith('.pdf'):
                    doc_type = 'unknown'
                    if any(kw in url_lower for kw in ['technical', 'regulation', 'guideline', 'normativ']):
                        doc_type = 'technical_guidelines'
                    elif any(kw in url_lower for kw in ['manual', 'handbook', 'welcome', 'pack', 'guide']):
                        doc_type = 'exhibitor_manual'

                    # Detect year
                    year_match = re.search(r'20(2[4-9]|3[0-9])', url)
                    pdf_year = f"20{year_match.group(1)}" if year_match else None

                    found_pdfs.append({
                        'url': url,
                        'text': f"Document reference: {url.split('/')[-1]}",
                        'type': doc_type,
                        'year': pdf_year,
                        'source_page': 'cross-reference'
                    })
                    self._log(f"    📎 Direct PDF reference: {url[:60]}...")
                    continue

                # Otherwise try to scan the page for PDFs
                scan_browser = BrowserController(800, 600)
                try:
                    await scan_browser.launch()
                    await scan_browser.goto(url)
                    await asyncio.sleep(0.5)

                    relevant_links = await scan_browser.get_relevant_links()
                    for link in relevant_links.get('pdf_links', []):
                        link_lower = link.url.lower()
                        doc_type = 'unknown'
                        if any(kw in link_lower for kw in ['technical', 'regulation', 'guideline']):
                            doc_type = 'technical_guidelines'
                        elif any(kw in link_lower for kw in ['manual', 'handbook', 'welcome', 'pack']):
                            doc_type = 'exhibitor_manual'

                        year_match = re.search(r'20(2[4-9]|3[0-9])', link.url)
                        pdf_year = f"20{year_match.group(1)}" if year_match else None

                        found_pdfs.append({
                            'url': link.url,
                            'text': link.text,
                            'type': doc_type,
                            'year': pdf_year,
                            'source_page': url
                        })
                    self._log(f"    📎 Scanned reference page: {url[:60]} → {len(relevant_links.get('pdf_links', []))} PDFs")
                finally:
                    await scan_browser.close()

            except Exception as e:
                self._log(f"    ⚠️ Could not scan reference: {url[:40]}: {e}")
                continue

        return found_pdfs

    async def _web_search_for_portals(self, fair_name: str) -> dict:
        """
        Search the web for exhibitor portals and event manuals.
        Uses DuckDuckGo HTML search via Playwright browser (urllib is blocked
        in some production environments).

        Returns dict with 'pdf_links' and 'portal_urls'.
        """
        import urllib.parse

        found_pdfs = []
        found_portals = []

        # Clean fair name (remove year if present)
        clean_name = re.sub(r'\s*20\d{2}\s*', ' ', fair_name).strip()

        # Also try with year for more specific results
        year_match = re.search(r'20\d{2}', fair_name)
        year_str = year_match.group(0) if year_match else "2026"

        # Search queries to try - more diverse to catch portals
        search_queries = [
            f"{clean_name} {year_str} exhibitor manual PDF",
            f"{clean_name} online event manual OEM",
            f"{clean_name} {year_str} exhibitor portal",
            f"{clean_name} stand build rules regulations {year_str}",
            f"{clean_name} exhibitor welcome pack",
            f'"{clean_name}" site:my.site.com OR site:salesforce.com',
        ]

        # Domains we're interested in (external portals)
        interesting_domains = [
            'my.site.com',      # Salesforce community
            'force.com',        # Salesforce
            'salesforce.com',   # Salesforce
            'cvent.com',        # Cvent
            'a2zinc.net',       # A2Z events
            'expocad.com',      # ExpoCad
            'expofp.com',       # ExpoFP
            'smallworldlabs.com',  # Small World Labs
            'eventbrite.',      # Eventbrite
            'map-dynamics.',    # Map Dynamics
            'n200.com',         # Nth Degree
            'mapyourshow.com',  # Map Your Show
            'swapcard.com',     # Swapcard
            'grip.events',      # Grip
            'ungerboeck',       # Ungerboeck
            'dashboards.events',    # Exhibitor dashboards
            'onlineexhibitormanual.com',  # OEM platform
            'gevme.com',        # Gevme events
        ]

        # Also interested in any PDF that matches fair-related keywords
        fair_pdf_keywords = [
            'exhibitor', 'manual', 'welcome', 'technical', 'regulation',
            'guideline', 'stand-build', 'standbuild', 'floorplan', 'floor-plan',
            'getting-started', 'rules', 'schedule', 'event-info', 'handbook',
            'terms_and_conditions', 'terms-and-conditions',
        ]

        # Add fair name words as dynamic PDF keywords
        # e.g. "GreenTech Amsterdam" -> also match PDFs containing "greentech" or "amsterdam"
        name_words = clean_name.lower().split()
        stop_words = {'the', 'of', 'and', 'for', 'in', 'at', 'de', 'der', 'die', 'das',
                     'fair', 'trade', 'show', 'exhibition', 'expo', 'messe', 'fiera', 'salon'}
        for word in name_words:
            if word not in stop_words and len(word) >= 4:
                fair_pdf_keywords.append(word)

        # Launch a lightweight Playwright browser for searches with JS DISABLED.
        # DuckDuckGo's html.duckduckgo.com/html/ is a no-JS endpoint that returns
        # static HTML with result__a links. With JS enabled, DDG redirects to its
        # JS-rendered version which has completely different HTML structure.
        # We use direct Playwright API (not BrowserController) to set java_script_enabled=False.
        from playwright.async_api import async_playwright as _async_pw
        _pw = None
        _search_browser = None
        _search_page = None
        try:
            _pw = await _async_pw().start()
            _search_browser = await _pw.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            _search_context = await _search_browser.new_context(
                viewport={'width': 800, 'height': 600},
                java_script_enabled=False,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            )
            _search_page = await _search_context.new_page()
        except Exception as e:
            self._log(f"    ⚠️ Could not launch search browser: {e}")
            if _search_browser:
                await _search_browser.close()
            if _pw:
                await _pw.stop()
            return {'pdf_links': [], 'portal_urls': []}

        try:
            for qi, query in enumerate(search_queries[:4]):  # Check 4 searches
                try:
                    self._log(f"    🔍 Web search: '{query}'")
                    encoded_query = urllib.parse.quote_plus(query)
                    search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

                    try:
                        await _search_page.goto(search_url, wait_until='domcontentloaded', timeout=15000)
                        html = await _search_page.content()
                    except Exception as e:
                        self._log(f"    Web search error: {e}")
                        continue

                    if not html:
                        continue

                    # Extract URLs from DuckDuckGo results
                    # DDG's no-JS HTML endpoint returns results in <a class="result__a"> links.
                    # href format varies:
                    # - Direct URLs: href="https://example.com/..."
                    # - Redirect URLs: href="//duckduckgo.com/l/?uddg=https%3A%2F%2F..."
                    raw_hrefs = re.findall(r'class="result__a"[^>]*href="([^"]+)"', html)
                    if not raw_hrefs:
                        # Fallback: scan entire HTML for uddg= parameters
                        raw_hrefs = re.findall(r'uddg=([^&"]+)', html)
                    if not raw_hrefs:
                        # Second fallback: look for any <a> hrefs with uddg in them
                        raw_hrefs = re.findall(r'href="([^"]*uddg=[^"]*)"', html)

                    self._log(f"    DDG returned {len(raw_hrefs)} raw result links")

                    # Resolve each href to its actual URL
                    matches = []
                    for href in raw_hrefs:
                        uddg_match = re.search(r'uddg=([^&"]+)', href)
                        if uddg_match:
                            matches.append(urllib.parse.unquote(uddg_match.group(1)))
                        elif href.startswith('http'):
                            matches.append(href)

                    for match in matches:
                        try:
                            decoded_url = urllib.parse.unquote(match)
                            parsed = urlparse(decoded_url)
                            host = parsed.netloc.lower()
                            path_lower = parsed.path.lower()

                            # Skip non-interesting domains
                            is_interesting = any(domain in host for domain in interesting_domains)
                            has_keywords = any(kw in decoded_url.lower() for kw in [
                                'exhibitor', 'oem', 'event-manual', 'eventmanual',
                                'stand-build', 'welcome-pack', 'welcomepack',
                                'technical-regulation', 'technical-guideline',
                            ])
                            # Also catch any PDF with fair-related keywords
                            is_fair_pdf = (
                                path_lower.endswith('.pdf') and
                                any(kw in decoded_url.lower() for kw in fair_pdf_keywords)
                            )

                            if not (is_interesting or has_keywords or is_fair_pdf):
                                continue
                            if 'duckduckgo' in host:
                                continue

                            # Check if it's a PDF
                            if path_lower.endswith('.pdf'):
                                # Keep full URL for PDFs
                                if decoded_url not in found_pdfs:
                                    found_pdfs.append(decoded_url)
                                    self._log(f"    📄 Web search found PDF: {decoded_url[:80]}...")
                            else:
                                # For portals, clean the URL
                                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                                if clean_url not in found_portals:
                                    found_portals.append(clean_url)

                        except Exception:
                            continue

                except Exception as e:
                    self._log(f"    Web search error: {e}")
                    continue

                # Small delay between queries to avoid rate limiting
                if qi < 3:
                    await asyncio.sleep(1.5)
        finally:
            try:
                if _search_browser:
                    await _search_browser.close()
                if _pw:
                    await _pw.stop()
            except Exception:
                pass

        # Log search results summary
        if found_pdfs:
            for pdf in found_pdfs:
                self._log(f"    📄 Web search result PDF: {pdf[:70]}")
        if found_portals:
            for portal in found_portals:
                self._log(f"    🌐 Web search result portal: {portal[:70]}")
        if not found_pdfs and not found_portals:
            self._log(f"    ⚠️ Web search returned no useful results")

        return {
            'pdf_links': found_pdfs[:5],
            'portal_urls': found_portals[:5]
        }

    async def _probe_portal_urls(self, base_url: str, fair_name: str) -> List[str]:
        """
        Probe common external portal URL patterns.
        Tries to find exhibitor portals by checking if known URL patterns respond.
        Works generically for all fairs - uses the fair's domain and common platform patterns.
        """
        import urllib.request
        import urllib.error

        parsed = urlparse(base_url)
        domain = parsed.netloc.lower().replace('www.', '')
        domain_parts = domain.split('.')
        org_name = domain_parts[0] if domain_parts else ''

        # Clean fair name for URL patterns
        clean_name = re.sub(r'\s*20\d{2}\s*', '', fair_name).strip().lower()
        name_parts = clean_name.replace(' ', '').replace('-', '')

        # Generate candidate portal URLs based on common patterns
        candidates = []

        # Collect org name variants to try
        org_variants = set()
        if len(org_name) >= 2:
            org_variants.add(org_name)
        if len(name_parts) >= 2:
            org_variants.add(name_parts)

        # Also try individual significant words from the fair name
        # This catches cases like "Fruit Logistica" -> "fruitlogistica" and "logistica"
        name_words = re.sub(r'\s*20\d{2}\s*', '', fair_name).strip().lower().split()
        stop_words = {'the', 'of', 'and', 'for', 'in', 'at', 'de', 'der', 'die', 'das',
                     'fair', 'trade', 'show', 'exhibition', 'messe', 'fiera', 'salon', 'salone'}
        for word in name_words:
            if word not in stop_words and not word.isdigit() and len(word) >= 3:
                org_variants.add(word)

        # Salesforce community patterns for each org variant
        for org in org_variants:
            # Pattern: {org}.my.site.com/{org}oem/s/Home (most common for trade fairs)
            candidates.append(f"https://{org}.my.site.com/{org}oem/s/Home")
            candidates.append(f"https://{org}.my.site.com/s/Home")
            candidates.append(f"https://{org}.my.site.com/")

            # Cross-pattern: try fair name as community prefix on different org hosts
            # E.g., for MWC at mwcbarcelona.com: try {org}.my.site.com/{name}oem/s/Home
            for name_variant in org_variants:
                if name_variant != org:
                    candidates.append(f"https://{org}.my.site.com/{name_variant}oem/s/Home")

        # Deduplicate
        seen = set()
        unique_candidates = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique_candidates.append(c)

        # Probe each candidate
        found = []
        for url in unique_candidates[:10]:  # Max 10 probes
            try:
                req = urllib.request.Request(url, method='HEAD')
                req.add_header('User-Agent', 'Mozilla/5.0 (compatible; TradeFairBot/1.0)')
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status < 400:
                        found.append(url)
                        self._log(f"    ✅ Portal URL probe found: {url}")
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout):
                continue
            except Exception:
                continue

        return found

    def _generate_discovery_summary(
        self,
        output: DiscoveryOutput,
        input_data: TestCaseInput,
        start_time: float,
    ) -> List[str]:
        """Generate a compact discovery summary for easy sharing and troubleshooting.

        Contains all critical info from the full log in ~25-35 lines instead of 150+.
        """
        s = []
        elapsed = int(time.time() - start_time)
        domain = urlparse(input_data.known_url).netloc if input_data.known_url else '?'

        # Header
        s.append(f"=== DISCOVERY SUMMARY: {input_data.fair_name} ===")
        s.append(f"URL: {domain} | {input_data.city or '?'} | {elapsed}s")
        s.append("")

        # Site context
        sd = self._sd
        features = sd.get('site_features', [])
        key_pages = sd.get('key_pages_found', [])
        site_parts = []
        if features:
            site_parts.append('platforms: ' + ', '.join(features))
        if sd.get('has_login_portal'):
            site_parts.append('login portal')
        if key_pages:
            site_parts.append('key pages: ' + ', '.join(key_pages[:6]))
        if site_parts:
            s.append(f"SITE: {' | '.join(site_parts)}")
        # PDF breakdown
        if sd.get('pdf_types'):
            type_parts = [f"{v}x {k}" for k, v in sorted(sd['pdf_types'].items(), key=lambda x: -x[1])]
            year_parts = [f"{v}x {k}" for k, v in sorted(sd['pdf_years'].items(), key=lambda x: -x[1]) if k != 'geen']
            no_year = sd['pdf_years'].get('geen', 0)
            yr_str = ', '.join(year_parts)
            if no_year:
                yr_str += f", {no_year}x geen jaar" if yr_str else f"{no_year}x geen jaar"
            s.append(f"PDFs: {' | '.join(type_parts)}")
            s.append(f"  jaren: {yr_str}")
        s.append("")

        # Pre-scan
        s.append(f"PRE-SCAN: {sd['prescan_pdfs']} PDFs, {sd['prescan_pages']} pages, {sd['prescan_emails']} emails")
        if sd['subdomains_checked']:
            found_str = ', '.join(sd['subdomains_found']) if sd['subdomains_found'] else 'geen'
            s.append(f"  Subdomains: {len(sd['subdomains_found'])}/{sd['subdomains_checked']} actief ({found_str})")
        ws_parts = []
        if sd['web_search_pdfs']:
            ws_parts.append(f"{sd['web_search_pdfs']} PDFs")
        if sd['web_search_portals']:
            ws_parts.append(f"{sd['web_search_portals']} portals")
        s.append(f"  Web search: {', '.join(ws_parts) if ws_parts else 'geen resultaten'}")
        if sd['portal_probe_found']:
            s.append(f"  Portal probe: {', '.join(urlparse(u).netloc for u in sd['portal_probe_found'])}")

        # Portal scan
        if sd['portal_urls']:
            s.append("")
            s.append(f"PORTALS ({len(sd['portal_urls'])} gevonden, {len(sd['portals_scanned'])} gescand):")
            for ps in sd['portals_scanned']:
                url_short = urlparse(ps['url']).netloc + urlparse(ps['url']).path
                if len(url_short) > 55:
                    url_short = url_short[:55] + '...'
                types_str = ' '.join(ps['page_types']) if ps['page_types'] else 'home only'
                s.append(f"  {url_short} → {ps['sub_pages']} sub ({types_str})")
            # Show portals that weren't scanned
            scanned_urls = {ps['url'] for ps in sd['portals_scanned']}
            for purl in sd['portal_urls']:
                if purl not in scanned_urls:
                    url_short = urlparse(purl).netloc + urlparse(purl).path
                    if len(url_short) > 55:
                        url_short = url_short[:55] + '...'
                    s.append(f"  {url_short} → NIET GESCAND")

        # Classification
        s.append("")
        s.append("CLASSIFICATIE:")
        for dtype in ['floorplan', 'exhibitor_manual', 'rules', 'schedule', 'exhibitor_directory']:
            cls_info = sd['classification'].get(dtype)
            if cls_info:
                conf = cls_info['confidence'].upper()
                url_short = cls_info['url']
                # Shorten URL for display
                parsed_u = urlparse(url_short)
                url_display = parsed_u.netloc + parsed_u.path
                if len(url_display) > 60:
                    url_display = '...' + url_display[-57:]
                if dtype == 'exhibitor_directory':
                    s.append(f"  {'✓'} {dtype:<22} {conf:<8} | {url_display}")
                else:
                    yr = '✓' if cls_info.get('year') else '✗'
                    fr = '✓' if cls_info.get('fair') else '✗'
                    s.append(f"  {'✓'} {dtype:<22} {conf:<8} yr={yr} fair={fr} | {url_display}")
            else:
                s.append(f"  {'✗'} {dtype:<22} NIET GEVONDEN")

        # Quality gate
        s.append("")
        if sd['quality_gate']:
            s.append(f"QUALITY GATE: {sd['quality_gate']}")
        if sd['skip_agent']:
            s.append(f"  → Browser agent OVERGESLAGEN")
        elif sd['agent_iterations']:
            s.append(f"  → Browser agent: {sd['agent_iterations']} iteraties")

        # Schedule
        bu = len(output.schedule.build_up)
        td = len(output.schedule.tear_down)
        if bu or td:
            s.append(f"SCHEDULE: {bu} build-up + {td} tear-down entries")

        # Contacts
        n_emails = len(output.contact_info.emails)
        rec = output.contact_info.recommended_email
        if n_emails or rec:
            parts = [f"{n_emails} emails"]
            if rec:
                parts.append(f"aanbevolen: {rec}")
            s.append(f"CONTACTS: {', '.join(parts)}")

        # Final result
        s.append("")
        s.append("RESULTAAT:")

        def _url_short(url):
            if not url:
                return 'ONTBREEKT'
            p = urlparse(url)
            display = p.netloc + p.path
            return ('...' + display[-57:]) if len(display) > 60 else display

        s.append(f"  Floorplan:  {_url_short(output.documents.floorplan_url)}")
        s.append(f"  Manual:     {_url_short(output.documents.exhibitor_manual_url)}")
        s.append(f"  Rules:      {_url_short(output.documents.rules_url)}")
        s.append(f"  Schedule:   {f'{bu} opbouw + {td} afbouw' if (bu or td) else _url_short(output.documents.schedule_page_url)}")
        s.append(f"  Directory:  {_url_short(output.documents.exhibitor_directory_url)}")

        # Warnings
        if sd['warnings'] or sd['errors']:
            s.append("")
            s.append("WAARSCHUWINGEN:")
            for w in sd['warnings']:
                s.append(f"  ⚠ {w}")
            for e in sd['errors']:
                s.append(f"  ✗ {e}")

        return s

    async def run(self, input_data: TestCaseInput) -> DiscoveryOutput:
        """Run the discovery agent."""
        output = create_empty_output(input_data.fair_name)
        output.city = input_data.city
        output.country = input_data.country
        self._discovery_log = []  # Reset log for each run
        self._sd = {k: ([] if isinstance(v, list) else ({} if isinstance(v, dict) else type(v)()))
                    for k, v in self._sd.items()}  # Reset summary data

        start_time = time.time()

        try:
            # Validate: known_url is required for discovery
            if not input_data.known_url:
                self._log("❌ Geen website URL opgegeven voor deze beurs.")
                self._log("   Discovery kan niet worden uitgevoerd zonder een bekende website URL.")
                self._log("   Voeg een website URL toe aan de beurs en probeer opnieuw.")
                output.debug.notes.append("Geen known_url opgegeven - discovery afgebroken")
                output.debug.discovery_log = list(self._discovery_log)
                return output

            # PHASE 1: Pre-scan website for documents (HTML-based, fast)
            self.on_phase("prescan")
            self._log("=" * 60)
            self._log("FASE 1: PRE-SCAN WEBSITE")
            self._log("=" * 60)
            start_url = input_data.known_url
            self._log(f"Start URL: {start_url}")
            self._log(f"Beurs: {input_data.fair_name} | Stad: {input_data.city} | Land: {input_data.country}")

            pre_scan_results = None
            pre_scan_info = ""
            classification_result = None
            skip_browser_agent = False

            pre_scan_results = await self._pre_scan_website(input_data.known_url, input_data.fair_name)
            self._sd['prescan_pdfs'] = len(pre_scan_results.get('pdf_links', []))
            self._sd['prescan_pages'] = len(pre_scan_results.get('exhibitor_pages', []))
            self._sd['prescan_emails'] = len(pre_scan_results.get('emails', []))
            self._log(f"Pre-scan resultaat: {self._sd['prescan_pdfs']} PDFs, "
                     f"{self._sd['prescan_pages']} exhibitor pagina's, "
                     f"{self._sd['prescan_emails']} emails")
            # Log all found PDFs
            for pdf in pre_scan_results.get('pdf_links', []):
                self._log(f"  PDF [{pdf.get('type', '?')}] [{pdf.get('year', '?')}]: {pdf.get('url', '?')[:80]}")
            # Log all exhibitor pages
            for page in pre_scan_results.get('exhibitor_pages', []):
                self._log(f"  Exhibitor pagina: {page[:80]}")

            # Collect site-context for compact summary
            for pdf in pre_scan_results.get('pdf_links', []):
                ptype = pdf.get('type', 'unknown')
                self._sd['pdf_types'][ptype] = self._sd['pdf_types'].get(ptype, 0) + 1
                pyear = pdf.get('year') or 'geen'
                self._sd['pdf_years'][pyear] = self._sd['pdf_years'].get(pyear, 0) + 1
            # Detect key pages and site features from exhibitor pages
            base_domain = urlparse(input_data.known_url).netloc if input_data.known_url else ''
            for page in pre_scan_results.get('exhibitor_pages', []):
                page_lower = page.lower()
                page_host = urlparse(page).netloc
                # Track important pages on the main site
                if page_host == base_domain or page_host == 'www.' + base_domain:
                    path = urlparse(page).path
                    if any(kw in page_lower for kw in ['exhibitor', 'resource', 'download', 'document', 'participate']):
                        label = path.strip('/').split('/')[-1] if path.strip('/') else path
                        if label and label not in [p for p in self._sd['key_pages_found']]:
                            self._sd['key_pages_found'].append(label)
                # Detect site features
                if 'my.site.com' in page_host and 'oem' in page_lower:
                    if 'salesforce_oem' not in self._sd['site_features']:
                        self._sd['site_features'].append('salesforce_oem')
                if 'expocad.com' in page_host:
                    if 'expocad' not in self._sd['site_features']:
                        self._sd['site_features'].append('expocad')
                if 'expofp.' in page_host:
                    if 'expofp' not in self._sd['site_features']:
                        self._sd['site_features'].append('expofp')
                if any(kw in page_lower for kw in ['login', 'signin', 'mymwc']):
                    self._sd['has_login_portal'] = True

            # PHASE 1.25: Deep scan external portals (Salesforce, OEM, etc.)
            # These portals have web page content (not PDFs) with rules, schedules, etc.
            self._log("")
            self._log("=" * 60)
            self.on_phase("portal_scan")
            self._log("FASE 1.25: PORTAL DETECTIE & DEEP SCAN")
            self._log("=" * 60)
            portal_pages = []
            portal_urls = self._find_portal_urls(pre_scan_results, fair_name=input_data.fair_name)
            self._sd['portal_urls'] = list(portal_urls)
            self._log(f"Gevonden portal URLs: {len(portal_urls)}")
            for purl in portal_urls:
                self._log(f"  Portal: {purl}")
            if portal_urls:
                portal_pages = await self._deep_scan_portals(portal_urls, input_data.fair_name)
                self._log(f"Portal deep scan resultaat: {len(portal_pages)} pagina's gevonden")
                for pp in portal_pages:
                    content_len = len(pp.get('text_content', '') or '')
                    self._log(f"  [{pp.get('detected_type', '?')}] {pp.get('url', '?')[:70]} ({content_len} chars)")

                # Add any PDFs found on portal pages to our PDF list
                for page in portal_pages:
                    if page.get('is_pdf'):
                        pre_scan_results['pdf_links'].append({
                            'url': page['url'],
                            'text': page.get('page_title', ''),
                            'type': page.get('detected_type', 'unknown'),
                            'year': None,
                            'source_page': 'portal'
                        })
            else:
                self._log("⚠️ Geen portal URLs gevonden in pre-scan resultaten")

            # PHASE 1.5: Classify found documents with LLM (STRICT validation)
            self._log("")
            self._log("=" * 60)
            self.on_phase("classification")
            self._log("FASE 1.5: DOCUMENT CLASSIFICATIE (LLM)")
            self._log("=" * 60)
            if pre_scan_results['pdf_links'] or portal_pages:
                self._log("📋 Starting STRICT document classification with LLM...")
                classifier = DocumentClassifier(self.client, self._log)

                classification_result = await classifier.classify_documents(
                    pdf_links=pre_scan_results['pdf_links'],
                    fair_name=input_data.fair_name,
                    target_year="2026",
                    exhibitor_pages=pre_scan_results.get('exhibitor_pages', []),
                    portal_pages=[p for p in portal_pages if p.get('text_content')],
                )

                # Log and track classification results
                self._log(f"Classificatie resultaat:")
                self._log(f"  Gevonden types: {classification_result.found_types}")
                self._log(f"  Missende types: {classification_result.missing_types}")
                for dtype in ['floorplan', 'exhibitor_manual', 'rules', 'schedule']:
                    cls = getattr(classification_result, dtype, None)
                    if cls:
                        self._log(f"  {dtype}: {cls.confidence} | year={cls.year_verified} | fair={cls.fair_verified} | url={cls.url[:70]}")
                        self._sd['classification'][dtype] = {
                            'confidence': cls.confidence,
                            'year': cls.year_verified,
                            'fair': cls.fair_verified,
                            'url': cls.url,
                        }
                    else:
                        self._log(f"  {dtype}: NIET GEVONDEN")
                if classification_result.exhibitor_directory:
                    self._log(f"  exhibitor_directory: {classification_result.exhibitor_directory[:70]}")
                    self._sd['classification']['exhibitor_directory'] = {
                        'confidence': 'strong', 'url': classification_result.exhibitor_directory
                    }
                if classification_result.extra_urls_to_scan:
                    self._log(f"  Extra URLs te scannen: {classification_result.extra_urls_to_scan}")

                # QUALITY GATE: Only skip agent when classifier says it's safe
                # This requires 3+ documents with STRONG confidence (year+fair verified)
                # ALSO: never skip if the schedule is completely missing — the browser
                # agent is often needed to find schedule pages on OEM portals (Salesforce
                # SPAs with dynamic navigation that the prescan's link extraction can miss)
                schedule_found = classification_result.schedule and classification_result.schedule.confidence in ['strong', 'partial']
                if classification_result.skip_agent_safe and schedule_found:
                    self._log(f"🎉 KWALITEITSCHECK GESLAAGD: {classification_result.skip_agent_reason}")
                    self._log("   Browser agent wordt overgeslagen - documenten zijn gevalideerd.")
                    skip_browser_agent = True
                    self._sd['quality_gate'] = f"PASSED ({classification_result.skip_agent_reason})"
                    self._sd['quality_gate_passed'] = True
                    self._sd['skip_agent'] = True
                    self._sd['skip_agent_reason'] = 'Alle docs + schema gevonden'
                elif classification_result.skip_agent_safe and not schedule_found:
                    self._log(f"⚠️ KWALITEITSCHECK: {classification_result.skip_agent_reason}")
                    self._log("   Maar schema ontbreekt — browser agent draait om schema te zoeken.")
                    self._sd['quality_gate'] = f"PASSED maar schema mist"
                    self._sd['quality_gate_passed'] = True
                    self._sd['skip_agent_reason'] = 'Schema ontbreekt → agent draait'
                else:
                    self._log(f"⚠️ KWALITEITSCHECK: {classification_result.skip_agent_reason}")
                    self._log("   Browser agent draait voor extra validatie.")
                    self._sd['quality_gate'] = f"FAILED ({classification_result.skip_agent_reason})"
                    self._sd['skip_agent_reason'] = 'Te weinig STRONG docs → agent draait'

                # PHASE 1.75: Secondary prescan for document references found in classified PDFs
                self._log("")
                self._log("=" * 60)
                self._log("FASE 1.75: SECONDARY PRESCAN (document referenties)")
                self._log("=" * 60)
                if classification_result.extra_urls_to_scan and not skip_browser_agent:
                    self._log(f"🔄 Secondary prescan: checking {len(classification_result.extra_urls_to_scan)} document references...")
                    extra_pdfs = await self._scan_document_references(
                        classification_result.extra_urls_to_scan
                    )
                    if extra_pdfs:
                        # Add to prescan results and re-classify
                        pre_scan_results['pdf_links'].extend(extra_pdfs)
                        self._log(f"  Found {len(extra_pdfs)} additional PDFs from document references")
                        # Re-run classification with new PDFs
                        classification_result = await classifier.classify_documents(
                            pdf_links=pre_scan_results['pdf_links'],
                            fair_name=input_data.fair_name,
                            target_year="2026",
                            exhibitor_pages=pre_scan_results.get('exhibitor_pages', []),
                            portal_pages=[p for p in portal_pages if p.get('text_content')],
                        )
                        schedule_found_2 = classification_result.schedule and classification_result.schedule.confidence in ['strong', 'partial']
                        if classification_result.skip_agent_safe and schedule_found_2:
                            self._log(f"🎉 KWALITEITSCHECK NA SECONDARY SCAN GESLAAGD!")
                            skip_browser_agent = True
                        elif classification_result.skip_agent_safe and not schedule_found_2:
                            self._log(f"⚠️ Secondary scan: kwaliteitscheck OK maar schema ontbreekt nog — agent draait")

            # Format pre-scan results for the agent
            if pre_scan_results['pdf_links']:
                pre_scan_info += "\n\n🎯 PRE-SCAN RESULTATEN - DOCUMENTEN GEVONDEN VOORAF:\n"
                pre_scan_info += "=" * 60 + "\n"

                # Sort PDFs by year (2026 first, then 2025, etc.) and by type
                def sort_key(pdf):
                    year = pdf.get('year', '0000')
                    if year is None:
                        year = '0000'
                    # Sort descending by year (2026 > 2025 > ...)
                    return (-int(year) if year.isdigit() else 0, pdf['type'])

                sorted_pdfs = sorted(pre_scan_results['pdf_links'], key=sort_key)

                # Group by type, but prioritize 2026 documents
                by_type = {}
                for pdf in sorted_pdfs:
                    doc_type = pdf['type']
                    if doc_type not in by_type:
                        by_type[doc_type] = []
                    by_type[doc_type].append(pdf)

                type_labels = {
                    'technical_guidelines': '📋 TECHNISCHE RICHTLIJNEN',
                    'exhibitor_manual': '📖 EXPOSANTEN HANDLEIDING',
                    'floorplan': '🗺️ PLATTEGROND',
                    'schedule': '📅 SCHEMA',
                    'unknown': '📄 OVERIGE DOCUMENTEN'
                }

                # Show important types first, then unknown
                type_order = ['technical_guidelines', 'exhibitor_manual', 'floorplan', 'schedule', 'unknown']

                for doc_type in type_order:
                    if doc_type not in by_type:
                        continue
                    pdfs = by_type[doc_type]
                    pre_scan_info += f"\n{type_labels.get(doc_type, doc_type)}:\n"
                    for pdf in pdfs[:8]:  # Increased limit per category
                        year_tag = f" [📅 {pdf.get('year')}]" if pdf.get('year') else ""
                        # Highlight 2026 documents
                        if pdf.get('year') == '2026':
                            pre_scan_info += f"  🌟 {pdf['url']}{year_tag} ← GEBRUIK DIT!\n"
                        else:
                            pre_scan_info += f"  ⭐ {pdf['url']}{year_tag}\n"

                pre_scan_info += "\n" + "=" * 60
                pre_scan_info += "\n💡 BELANGRIJK: Gebruik de 2026 documenten (🌟) - dit zijn de meest recente!\n"
                pre_scan_info += "💡 GEBRUIK goto_url om documenten direct te openen en valideren!\n"

            if pre_scan_results['exhibitor_pages']:
                pre_scan_info += "\n\n📍 GEVONDEN EXHIBITOR PAGINA'S OM TE BEZOEKEN:\n"
                for page in pre_scan_results['exhibitor_pages'][:10]:
                    # Highlight exhibitor portals (external subdomains)
                    if 'exhibitor' in page.lower() and page not in input_data.known_url:
                        pre_scan_info += f"  🌟 EXHIBITOR PORTAL: {page}\n"
                    else:
                        pre_scan_info += f"  • {page}\n"
                pre_scan_info += "\n⚠️ BELANGRIJK: Bezoek EERST de exhibitor portal(s) hierboven - daar staan vaak de beste documenten!"

            # EARLY RETURN: If classification found enough documents, skip browser agent
            if skip_browser_agent and classification_result:
                self.on_phase("results")
                self._log("🚀 Building output from pre-scan classification (skipping browser agent)...")
                output = self._build_output_from_classification(
                    classification_result, output, input_data, pre_scan_results, start_time
                )
                # Attach discovery log
                self._log("")
                self._log("=" * 60)
                self._log("RESULTAAT: Browser agent overgeslagen (voldoende documenten gevonden)")
                self._log("=" * 60)
                self._log(f"Floorplan: {output.documents.floorplan_url or 'NIET GEVONDEN'}")
                self._log(f"Exhibitor Manual: {output.documents.exhibitor_manual_url or 'NIET GEVONDEN'}")
                self._log(f"Rules: {output.documents.rules_url or 'NIET GEVONDEN'}")
                self._log(f"Exhibitor Directory: {output.documents.exhibitor_directory_url or 'NIET GEVONDEN'}")
                self._log(f"Schedule: {len(output.schedule.build_up)} opbouw + {len(output.schedule.tear_down)} afbouw entries")
                self._log(f"Totale tijd: {int(time.time() - start_time)}s")
                output.debug.discovery_log = list(self._discovery_log)
                output.debug.discovery_summary = self._generate_discovery_summary(output, input_data, start_time)
                return output

            # PHASE 2: Launch browser for visual verification
            self._log("")
            self._log("=" * 60)
            self.on_phase("browser_agent")
            self._log("FASE 2: BROWSER AGENT (Computer Use)")
            self._log("=" * 60)
            await self.browser.launch()
            self._log("Browser launched")

            await self.browser.goto(start_url)
            self._log(f"Navigated to: {start_url}")

            # Build dynamic system prompt based on what's found/missing
            use_focused_prompt = False
            active_system_prompt = SYSTEM_PROMPT

            if classification_result and classification_result.found_types:
                missing_types = classification_result.missing_types
                focused_prompt = build_focused_system_prompt(
                    classification_result=classification_result,
                    missing_types=missing_types,
                )
                active_system_prompt = focused_prompt
                use_focused_prompt = True
                self._log(f"🎯 Dynamische prompt: gefocust op {len(missing_types)} missende documenten")

            # Build initial message with pre-scan results and classification status
            classification_info = ""
            if classification_result and classification_result.found_types:
                classification_info = "\n\n" + "=" * 60 + "\n"
                classification_info += "🎯 PRE-SCAN CLASSIFICATIE RESULTATEN:\n"
                classification_info += "=" * 60 + "\n"
                classification_info += classification_result.get_found_prompt_section()
                classification_info += "\n\n"
                classification_info += classification_result.get_missing_prompt_section()
                classification_info += "\n" + "=" * 60

            user_message = f"""
Vind informatie voor de beurs: {input_data.fair_name}
{f'Stad: {input_data.city}' if input_data.city else ''}
{f'Land: {input_data.country}' if input_data.country else ''}
{f'Start URL: {input_data.known_url}' if input_data.known_url else ''}
{classification_info}
{pre_scan_info}

{'BELANGRIJK: Focus ALLEEN op de missende documenten! De andere zijn al gevalideerd.' if classification_result and classification_result.missing_types else ''}
{'BELANGRIJK: De pre-scan heeft al documenten gevonden! Gebruik goto_url om ze te valideren.' if pre_scan_results and pre_scan_results['pdf_links'] and not classification_result else 'Navigeer door de website en vind alle gevraagde documenten.'}
"""

            # Smart iteration limits based on how many documents are missing
            if classification_result:
                n_missing = len(classification_result.missing_types)
                if n_missing <= 1:
                    effective_max_iterations = 10
                elif n_missing <= 2:
                    effective_max_iterations = 15
                elif n_missing <= 3:
                    effective_max_iterations = 20
                else:
                    effective_max_iterations = 25  # Reduced from 40
                self._log(f"📉 Iteratie-limiet: {effective_max_iterations} (voor {n_missing} missende documenten)")
            else:
                effective_max_iterations = self.max_iterations

            # Get initial screenshot
            screenshot = await self.browser.screenshot()
            browser_state = await self.browser.get_state()

            # Start conversation with Claude
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_message},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot.base64,
                            },
                        },
                        {"type": "text", "text": f"Huidige pagina: {browser_state.url}\nTitel: {browser_state.title}"},
                    ],
                },
            ]

            # Agent loop
            iteration = 0
            done = False
            final_result = None

            while not done and iteration < effective_max_iterations:
                iteration += 1
                self._log(f"Iteration {iteration}/{effective_max_iterations}")

                # Dynamic mid-point check - at ~60% of iterations
                midpoint = max(5, effective_max_iterations * 3 // 5)
                remaining_at_mid = effective_max_iterations - midpoint
                if iteration == midpoint:
                    mid_msg = f"📊 TUSSENTIJDSE CHECK (iteratie {midpoint}/{effective_max_iterations}):\n\n"
                    if use_focused_prompt and classification_result:
                        missing_str = ", ".join(classification_result.missing_types)
                        mid_msg += f"Je zoekt nog naar: {missing_str}\n\n"
                        mid_msg += "Heb je al geprobeerd:\n"
                        mid_msg += "1. Downloads/Documents/Downloadcenter pagina\n"
                        mid_msg += "2. Externe exhibitor portals (my.site.com, OEM)\n"
                        mid_msg += "3. Alle accordion/dropdown items geopend\n"
                        mid_msg += "4. deep_scan gebruikt op relevante pagina's\n"
                    else:
                        mid_msg += "Heb je AL deze secties bezocht?\n"
                        mid_msg += "1. Exhibitor/For Exhibitors sectie\n"
                        mid_msg += "2. Downloads/Documents/Service Documentation\n"
                        mid_msg += "3. Participate / How to exhibit sectie\n"
                        mid_msg += "4. Subdomeinen (exhibitors.xxx.com)\n"
                    mid_msg += f"\nJe hebt nog {remaining_at_mid} acties - gebruik ze gericht!"
                    messages.append({
                        "role": "user",
                        "content": [{"type": "text", "text": mid_msg}],
                    })

                # Warn agent to wrap up when approaching limit
                if iteration == effective_max_iterations - 3:
                    messages.append({
                        "role": "user",
                        "content": [{"type": "text", "text": """⚠️ Je hebt nog 3 acties over. Begin nu met je JSON samenvatting.

BELANGRIJK: Voeg voor elk document validation_notes toe die bewijzen dat het aan de criteria voldoet!
- Als een document NIET aan de criteria voldeed, zet url op null en leg uit waarom in validation
- Wees EERLIJK: alleen "VOLDOET" als het echt aan alle criteria voldoet
- Bij twijfel: "NIET GEVONDEN" is beter dan een verkeerd document accepteren"""}],
                    })

                # Call Claude with computer use (dynamic prompt when classification available)
                response = self.client.beta.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=active_system_prompt,
                    betas=["computer-use-2025-01-24"],
                    tools=[
                        {
                            "type": "computer_20250124",
                            "name": "computer",
                            "display_width_px": screenshot.width,
                            "display_height_px": screenshot.height,
                            "display_number": 1,
                        },
                        {
                            "name": "goto_url",
                            "description": "Navigate directly to a URL. Use this to visit PDF links you see in the extracted links, or to check exhibitor directory subdomains like exhibitors.bauma.de",
                            "input_schema": {
                                "type": "object",
                                "properties": {
                                    "url": {
                                        "type": "string",
                                        "description": "The full URL to navigate to",
                                    },
                                },
                                "required": ["url"],
                            },
                        },
                        {
                            "name": "deep_scan",
                            "description": "Perform a deep scan of the current page to find ALL document links. This expands all accordions, dropdowns, and hidden sections, then extracts every PDF and document link. Use this when you suspect there are hidden documents on the page.",
                            "input_schema": {
                                "type": "object",
                                "properties": {},
                                "required": [],
                            },
                        },
                    ],
                    messages=messages,
                )

                # Process response
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                # Check for text output (final result)
                for block in assistant_content:
                    if block.type == "text":
                        self._log(f"Claude: {block.text[:200]}...")

                        # Check if this contains the final JSON result
                        if '"floorplan_url"' in block.text or '"exhibitor_manual_url"' in block.text:
                            final_result = block.text

                # Check for tool use
                tool_use_blocks = [b for b in assistant_content if b.type == "tool_use"]

                if len(tool_use_blocks) == 0:
                    done = True
                    break

                # Execute tool calls
                tool_results = []

                for tool_use in tool_use_blocks:
                    if tool_use.name == "computer":
                        result = await self._execute_computer_action(tool_use.input)

                        # Extract links after every action
                        link_info = await self._extract_and_format_links()

                        # Add link info to result
                        if link_info:
                            result.append({"type": "text", "text": link_info})

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": result,
                        })

                    elif tool_use.name == "goto_url":
                        url = tool_use.input.get("url", "")
                        result = await self._execute_goto_url(url)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": result,
                        })

                    elif tool_use.name == "deep_scan":
                        result = await self._execute_deep_scan()
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": result,
                        })

                # Add tool results to messages
                messages.append({"role": "user", "content": tool_results})

                # Log action
                elapsed_ms = int((time.time() - start_time) * 1000)
                output.debug.action_log.append(ActionLogEntry(
                    step="action",
                    input=f"Iteration {iteration}",
                    output=f"{len(tool_use_blocks)} actions executed",
                    ms=elapsed_ms
                ))

                # Check stop condition
                if response.stop_reason == "end_turn" and len(tool_use_blocks) == 0:
                    done = True

            # Parse final result
            if final_result:
                self._parse_result(final_result, output)

            # Set official URL
            state = await self.browser.get_state()
            if input_data.known_url:
                output.official_url = input_data.known_url
                output.official_domain = urlparse(input_data.known_url).netloc
            else:
                output.official_url = state.url
                output.official_domain = urlparse(state.url).netloc

            # Record visited URLs
            output.debug.visited_urls.append(state.url)

            # Record downloaded files and auto-map to output fields
            downloads = self.browser.get_downloaded_files()
            for download in downloads:
                output.debug.downloaded_files.append(DownloadedFileInfo(
                    url=download.original_url,
                    path=download.local_path,
                    content_type='application/pdf' if download.filename.endswith('.pdf') else None,
                    bytes=None
                ))

                # Auto-map downloads to document fields based on filename
                self._auto_map_download(download, output)

            # Merge classification results with agent results (classification as fallback)
            if classification_result:
                # Only use classification result if agent didn't find it
                if not output.documents.floorplan_url and classification_result.floorplan:
                    if classification_result.floorplan.confidence in ['strong', 'partial']:
                        output.documents.floorplan_url = classification_result.floorplan.url
                        output.quality.floorplan = classification_result.floorplan.confidence
                        output.primary_reasoning.floorplan = f"PRE-SCAN: {classification_result.floorplan.reason}"

                if not output.documents.exhibitor_manual_url and classification_result.exhibitor_manual:
                    if classification_result.exhibitor_manual.confidence in ['strong', 'partial']:
                        output.documents.exhibitor_manual_url = classification_result.exhibitor_manual.url
                        output.quality.exhibitor_manual = classification_result.exhibitor_manual.confidence
                        output.primary_reasoning.exhibitor_manual = f"PRE-SCAN: {classification_result.exhibitor_manual.reason}"

                if not output.documents.rules_url and classification_result.rules:
                    if classification_result.rules.confidence in ['strong', 'partial']:
                        output.documents.rules_url = classification_result.rules.url
                        output.quality.rules = classification_result.rules.confidence
                        output.primary_reasoning.rules = f"PRE-SCAN: {classification_result.rules.reason}"

                if not output.documents.exhibitor_directory_url and classification_result.exhibitor_directory:
                    output.documents.exhibitor_directory_url = classification_result.exhibitor_directory
                    output.quality.exhibitor_directory = "strong"
                    output.primary_reasoning.exhibitor_directory = "PRE-SCAN: Exhibitor directory page"

                # Merge schedule page URL from classification
                if not output.documents.schedule_page_url and classification_result.schedule:
                    if classification_result.schedule.confidence in ['strong', 'partial']:
                        output.documents.schedule_page_url = classification_result.schedule.url
                        output.quality.schedule = classification_result.schedule.confidence
                        output.primary_reasoning.schedule = f"PRE-SCAN: {classification_result.schedule.reason}"

                # Merge extracted schedule entries from classification
                if classification_result.aggregated_schedule:
                    seen_build_up = {(e.date, e.time) for e in output.schedule.build_up}
                    for entry in classification_result.aggregated_schedule.build_up:
                        if entry.get('date'):
                            dedup_key = (entry.get('date'), entry.get('time', ''))
                            if dedup_key not in seen_build_up:
                                seen_build_up.add(dedup_key)
                                output.schedule.build_up.append(ScheduleEntry(
                                    date=entry.get('date'),
                                    time=entry.get('time', ''),
                                    description=entry.get('description', 'Build-up'),
                                    source_url=classification_result.aggregated_schedule.source_url or output.documents.schedule_page_url or ''
                                ))
                    seen_tear_down = {(e.date, e.time) for e in output.schedule.tear_down}
                    for entry in classification_result.aggregated_schedule.tear_down:
                        if entry.get('date'):
                            dedup_key = (entry.get('date'), entry.get('time', ''))
                            if dedup_key not in seen_tear_down:
                                seen_tear_down.add(dedup_key)
                                output.schedule.tear_down.append(ScheduleEntry(
                                    date=entry.get('date'),
                                    time=entry.get('time', ''),
                                    description=entry.get('description', 'Tear-down'),
                                    source_url=classification_result.aggregated_schedule.source_url or output.documents.schedule_page_url or ''
                                ))
                    if output.schedule.build_up or output.schedule.tear_down:
                        if not output.quality.schedule or output.quality.schedule != 'strong':
                            output.quality.schedule = "strong"
                        self._log(f"📅 Merged schedule from classification: {len(output.schedule.build_up)} build-up, {len(output.schedule.tear_down)} tear-down")

            output.debug.notes.append(f"Agent completed in {iteration} iterations")
            output.debug.notes.append(f"Auto-mapped {len(downloads)} downloaded files to output fields")
            output.debug.notes.append(f"Total time: {int(time.time() - start_time)}s")

            # Attach the full discovery log for troubleshooting
            self._log("")
            self._log("=" * 60)
            self.on_phase("results")
            self._log("FASE 3: RESULTAAT SAMENVATTING")
            self._log("=" * 60)
            self._log(f"Floorplan: {output.documents.floorplan_url or 'NIET GEVONDEN'}")
            self._log(f"Exhibitor Manual: {output.documents.exhibitor_manual_url or 'NIET GEVONDEN'}")
            self._log(f"Rules: {output.documents.rules_url or 'NIET GEVONDEN'}")
            self._log(f"Exhibitor Directory: {output.documents.exhibitor_directory_url or 'NIET GEVONDEN'}")
            self._log(f"Schedule: {len(output.schedule.build_up)} opbouw + {len(output.schedule.tear_down)} afbouw entries")
            self._sd['agent_iterations'] = iteration
            self._log(f"Totale tijd: {int(time.time() - start_time)}s | Iteraties: {iteration}")
            output.debug.discovery_log = list(self._discovery_log)
            output.debug.discovery_summary = self._generate_discovery_summary(output, input_data, start_time)

            # Add discovered emails to output (with deduplication)
            if pre_scan_results and pre_scan_results.get('emails'):
                existing_emails = {e.email for e in output.contact_info.emails}
                added = 0
                for email_data in pre_scan_results['emails']:
                    if email_data['email'] not in existing_emails:
                        existing_emails.add(email_data['email'])
                        output.contact_info.emails.append(ContactEmail(
                            email=email_data['email'],
                            context=email_data.get('context', ''),
                            source_url=email_data.get('source_url', '')
                        ))
                        added += 1
                self._log(f"Added {added} contact emails to output")

            # Select recommended email for fair organization
            self._select_recommended_email(output)

            # Generate email draft if documents are missing
            output.email_draft_if_missing = self._generate_email_draft(output, input_data)

        except Exception as e:
            error_msg = str(e)
            output.debug.notes.append(f"Error: {error_msg}")
            self._log(f"Error: {error_msg}")
            raise

        finally:
            await self.browser.close()

        return output

    async def _extract_and_format_links(self) -> str:
        """Extract and format relevant links from current page."""
        try:
            relevant_links = await self.browser.get_relevant_links()
            link_info = ""

            # Show high-value links first (technical regulations, provisions, etc.)
            if relevant_links.get('high_value_links'):
                link_info += "\n\n⭐ BELANGRIJKE DOCUMENTEN GEVONDEN:\n"
                for link in relevant_links['high_value_links'][:10]:
                    link_info += f"• ⭐ {link.text or 'Document'}: {link.url}\n"

            if relevant_links['pdf_links']:
                link_info += "\n\n📄 PDF LINKS OP DEZE PAGINA:\n"
                for link in relevant_links['pdf_links'][:20]:
                    link_info += f"• {link.text or 'PDF'}: {link.url}\n"

            if relevant_links['exhibitor_links']:
                link_info += "\n\n🔗 RELEVANTE LINKS:\n"
                for link in relevant_links['exhibitor_links'][:15]:
                    link_info += f"• {link.text}: {link.url}\n"

            # Show download links if different from PDFs
            pdf_urls = {l.url for l in relevant_links['pdf_links']}
            download_only = [l for l in relevant_links['download_links'] if l.url not in pdf_urls]
            if download_only:
                link_info += "\n\n📥 DOWNLOAD LINKS:\n"
                for link in download_only[:10]:
                    link_info += f"• {link.text}: {link.url}\n"

            return link_info
        except:
            return ""

    async def _execute_deep_scan(self) -> List[Dict[str, Any]]:
        """Execute deep scan to find all document links on the current page."""
        self._log("Performing deep scan for documents...")

        try:
            # Get all links (accordion expansion happens automatically)
            relevant_links = await self.browser.get_relevant_links()
            state = await self.browser.get_state()

            result_text = f"🔍 DEEP SCAN RESULTATEN voor {state.url}\n"
            result_text += "=" * 60 + "\n\n"

            # External portal URLs (CRITICAL - these often have the most important docs!)
            portal_urls = await self.browser.extract_external_portal_urls()
            if portal_urls:
                result_text += "🌐🌐🌐 EXTERNE PORTAL LINKS GEVONDEN:\n"
                for portal in portal_urls:
                    result_text += f"  🌐 {portal['url']}\n"
                result_text += "\n⚠️ BELANGRIJK: Bezoek deze portals met goto_url! Ze bevatten vaak exhibitor manuals, rules en schedules!\n\n"

            # High-value documents first
            if relevant_links.get('high_value_links'):
                result_text += "⭐⭐⭐ BELANGRIJKE DOCUMENTEN (technical/regulations/provisions):\n"
                for link in relevant_links['high_value_links']:
                    result_text += f"  ⭐ {link.text[:80]}\n     URL: {link.url}\n\n"
            else:
                result_text += "⚠️ Geen high-value documenten gevonden op deze pagina.\n\n"

            # All PDFs
            if relevant_links['pdf_links']:
                result_text += f"\n📄 ALLE PDF LINKS ({len(relevant_links['pdf_links'])} gevonden):\n"
                for link in relevant_links['pdf_links'][:30]:
                    result_text += f"  • {link.text[:60] or 'PDF'}\n    URL: {link.url}\n"
            else:
                result_text += "\n📄 Geen PDF links gevonden.\n"

            # CMS/Download links
            if relevant_links['download_links']:
                result_text += f"\n📥 DOWNLOAD/CMS LINKS ({len(relevant_links['download_links'])} gevonden):\n"
                seen_urls = set()
                for link in relevant_links['download_links'][:20]:
                    if link.url not in seen_urls:
                        seen_urls.add(link.url)
                        result_text += f"  • {link.text[:60]}\n    URL: {link.url}\n"

            # External links (non-portal) that may be interesting
            all_links = relevant_links.get('all_links', [])
            external_links = []
            current_domain = urlparse(state.url).netloc
            for link in all_links:
                try:
                    link_host = urlparse(link.url).netloc
                    if link_host and link_host != current_domain:
                        external_links.append(link)
                except:
                    pass
            if external_links:
                result_text += f"\n🔗 EXTERNE LINKS ({len(external_links)} gevonden):\n"
                for link in external_links[:15]:
                    result_text += f"  • {link.text[:50] or 'Link'}\n    URL: {link.url}\n"

            result_text += "\n" + "=" * 60
            result_text += "\n💡 TIP: Gebruik goto_url om direct naar een PDF of portal te navigeren!"

            return [{"type": "text", "text": result_text}]

        except Exception as e:
            self._log(f"Deep scan error: {e}")
            return [{"type": "text", "text": f"Deep scan error: {e}"}]

    async def _execute_goto_url(self, url: str) -> List[Dict[str, Any]]:
        """Execute goto_url tool."""
        self._log(f"Navigating to: {url}")

        try:
            await self.browser.goto(url)
            await asyncio.sleep(1)

            screenshot = await self.browser.screenshot()
            state = await self.browser.get_state()
            link_info = await self._extract_and_format_links()

            return [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot.base64,
                    },
                },
                {
                    "type": "text",
                    "text": f"Navigated to: {state.url}\nTitle: {state.title}{link_info}",
                },
            ]
        except Exception as e:
            self._log(f"Navigation error: {e}")
            return [{"type": "text", "text": f"Error navigating to {url}: {e}"}]

    async def _execute_computer_action(self, input_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a computer action."""
        action = input_data.get("action", "")
        self._log(f"Action: {action}")

        try:
            if action == "screenshot":
                pass  # Just take screenshot

            elif action == "mouse_move":
                coord = input_data.get("coordinate", [0, 0])
                await self.browser.move_mouse(coord[0], coord[1])

            elif action == "left_click":
                coord = input_data.get("coordinate")
                if coord:
                    await self.browser.click(coord[0], coord[1])

            elif action == "left_click_drag":
                start = input_data.get("start_coordinate", [0, 0])
                end = input_data.get("end_coordinate", [0, 0])
                await self.browser.drag(start[0], start[1], end[0], end[1])

            elif action == "right_click":
                coord = input_data.get("coordinate")
                if coord:
                    await self.browser.right_click(coord[0], coord[1])

            elif action == "double_click":
                coord = input_data.get("coordinate")
                if coord:
                    await self.browser.double_click(coord[0], coord[1])

            elif action == "type":
                text = input_data.get("text", "")
                await self.browser.type_text(text)

            elif action == "key":
                key = input_data.get("key", "")
                if "+" in key:
                    parts = key.split("+")
                    await self.browser.hotkey(*parts)
                else:
                    await self.browser.press_key(key)

            elif action == "scroll":
                coord = input_data.get("coordinate", [0, 0])
                direction = input_data.get("scroll_direction", "down")
                delta_y = 300 if direction == "down" else (-300 if direction == "up" else 0)
                delta_x = 300 if direction == "right" else (-300 if direction == "left" else 0)
                await self.browser.scroll(coord[0], coord[1], delta_x, delta_y)

            else:
                self._log(f"Unknown action: {action}")

            # Wait for page to update
            await asyncio.sleep(0.5)

            # Take new screenshot
            screenshot = await self.browser.screenshot()
            state = await self.browser.get_state()

            return [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot.base64,
                    },
                },
                {
                    "type": "text",
                    "text": f"URL: {state.url}\nTitle: {state.title}",
                },
            ]

        except Exception as e:
            self._log(f"Action error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]

    def _auto_map_download(self, download: DownloadedFile, output: DiscoveryOutput) -> None:
        """Auto-map downloaded file to output fields based on filename."""
        filename = download.filename.lower()
        url = download.original_url
        url_lower = url.lower()

        # Floor plan / Hall plan / Geländeplan / Site plan
        is_floorplan = (
            'gelände' in filename or 'gelande' in filename or
            'floor' in filename or 'hall' in filename or
            'site' in filename or 'hallen' in filename or
            ('plan' in filename and 'richtlin' not in filename and 'techni' not in filename) or
            'map' in filename or 'overview' in filename or
            'gelaende' in url_lower or 'floorplan' in url_lower or
            'hallenplan' in url_lower or 'siteplan' in url_lower
        ) and 'richtlin' not in filename and 'techni' not in filename and 'guideline' not in filename

        if is_floorplan and not output.documents.floorplan_url:
            output.documents.floorplan_url = url
            output.quality.floorplan = 'strong'
            output.primary_reasoning.floorplan = f"Auto-detected from download: {download.filename}"

        # Technical Guidelines / Richtlinien / Regulations
        is_rules = (
            'richtlin' in filename or 'guideline' in filename or
            'techni' in filename or 'regulation' in filename or
            'vorschrift' in filename or 'regel' in filename or
            'construction' in filename or 'standbau' in filename or
            'richtlin' in url_lower or 'guideline' in url_lower or
            'technical' in url_lower
        )

        if is_rules and not output.documents.rules_url:
            output.documents.rules_url = url
            output.quality.rules = 'strong'
            output.primary_reasoning.rules = f"Auto-detected from download: {download.filename}"

        # Exhibitor Manual / Service Documentation / Verkehrsleitfaden / Handbuch
        is_manual = (
            'manual' in filename or 'handbook' in filename or
            'handbuch' in filename or 'service' in filename or
            'leitfaden' in filename or 'verkehr' in filename or
            'aussteller' in filename or 'exhibitor' in filename or
            'guide' in filename or 'documentation' in filename or
            'manual' in url_lower or 'handbook' in url_lower or
            'service-doc' in url_lower or 'leitfaden' in url_lower
        ) and not is_rules

        if is_manual and not output.documents.exhibitor_manual_url:
            output.documents.exhibitor_manual_url = url
            output.quality.exhibitor_manual = 'strong'
            output.primary_reasoning.exhibitor_manual = f"Auto-detected from download: {download.filename}"

        # Schedule / Timeline / Zeitplan
        is_schedule = (
            'zeitplan' in filename or 'timeline' in filename or
            'schedule' in filename or 'aufbau' in filename or
            'abbau' in filename or 'termine' in filename or
            'dismantl' in filename or 'set-up' in filename or
            'schedule' in url_lower or 'timeline' in url_lower
        )

        if is_schedule and not output.documents.schedule_page_url:
            output.documents.schedule_page_url = url

    def _parse_result(self, text: str, output: DiscoveryOutput) -> None:
        """Parse the final JSON result from Claude."""
        # Try to extract JSON from the text
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if not json_match:
            json_match = re.search(r'\{[\s\S]*"floorplan_url"[\s\S]*\}', text)

        if not json_match:
            output.debug.notes.append("Could not parse final JSON result")
            return

        try:
            json_str = json_match.group(1) if json_match.lastindex else json_match.group(0)
            result = json.loads(json_str)

            # Helper to check if validation indicates document was rejected
            def is_validated(validation_text: str) -> bool:
                if not validation_text:
                    return True  # No validation = assume valid (backward compat)
                validation_lower = validation_text.lower()
                rejected_keywords = ['afgewezen', 'niet gevonden', 'rejected', 'not found', 'voldoet niet', 'does not meet']
                return not any(kw in validation_lower for kw in rejected_keywords)

            # Map to output structure with validation checks
            floorplan_validation = result.get("floorplan_validation", "")
            if result.get("floorplan_url") and is_validated(floorplan_validation):
                output.documents.floorplan_url = result["floorplan_url"]
                output.quality.floorplan = "strong"
                output.primary_reasoning.floorplan = floorplan_validation or "Found by Claude agent"
            elif floorplan_validation:
                output.primary_reasoning.floorplan = floorplan_validation

            exhibitor_manual_validation = result.get("exhibitor_manual_validation", "")
            if result.get("exhibitor_manual_url") and is_validated(exhibitor_manual_validation):
                output.documents.exhibitor_manual_url = result["exhibitor_manual_url"]
                output.quality.exhibitor_manual = "strong"
                output.primary_reasoning.exhibitor_manual = exhibitor_manual_validation or "Found by Claude agent"
            elif exhibitor_manual_validation:
                output.primary_reasoning.exhibitor_manual = exhibitor_manual_validation

            rules_validation = result.get("rules_validation", "")
            if result.get("rules_url") and is_validated(rules_validation):
                output.documents.rules_url = result["rules_url"]
                output.quality.rules = "strong"
                output.primary_reasoning.rules = rules_validation or "Found by Claude agent"
            elif rules_validation:
                output.primary_reasoning.rules = rules_validation

            exhibitor_directory_validation = result.get("exhibitor_directory_validation", "")
            if result.get("exhibitor_directory_url") and is_validated(exhibitor_directory_validation):
                output.documents.exhibitor_directory_url = result["exhibitor_directory_url"]
                output.quality.exhibitor_directory = "strong"
                output.primary_reasoning.exhibitor_directory = exhibitor_directory_validation or "Found by Claude agent"
            elif exhibitor_directory_validation:
                output.primary_reasoning.exhibitor_directory = exhibitor_directory_validation

            if result.get("downloads_page_url"):
                output.documents.downloads_overview_url = result["downloads_page_url"]

            # Parse schedule with validation
            schedule = result.get("schedule", {})
            schedule_validation = result.get("schedule_validation", "")

            if schedule and is_validated(schedule_validation):
                # Deduplicate schedule entries (same pattern as classification merge)
                seen_build_up = {(e.date, e.time) for e in output.schedule.build_up}
                seen_tear_down = {(e.date, e.time) for e in output.schedule.tear_down}

                build_up = schedule.get("build_up", [])
                if isinstance(build_up, list):
                    for entry in build_up:
                        dedup_key = (entry.get("date"), entry.get("time", ""))
                        if dedup_key not in seen_build_up:
                            seen_build_up.add(dedup_key)
                            output.schedule.build_up.append(ScheduleEntry(
                                date=entry.get("date"),
                                time=entry.get("time"),
                                description=entry.get("description", ""),
                                source_url=output.documents.exhibitor_manual_url or output.official_url or ""
                            ))

                tear_down = schedule.get("tear_down", [])
                if isinstance(tear_down, list):
                    for entry in tear_down:
                        dedup_key = (entry.get("date"), entry.get("time", ""))
                        if dedup_key not in seen_tear_down:
                            seen_tear_down.add(dedup_key)
                            output.schedule.tear_down.append(ScheduleEntry(
                                date=entry.get("date"),
                                time=entry.get("time"),
                                description=entry.get("description", ""),
                                source_url=output.documents.exhibitor_manual_url or output.official_url or ""
                            ))

                if output.schedule.build_up or output.schedule.tear_down:
                    output.quality.schedule = "strong"
                    output.primary_reasoning.schedule = schedule_validation or f"Found {len(output.schedule.build_up)} build-up and {len(output.schedule.tear_down)} tear-down entries"
            elif schedule_validation:
                output.primary_reasoning.schedule = schedule_validation

            if result.get("notes"):
                output.debug.notes.append(f"Agent notes: {result['notes']}")

        except json.JSONDecodeError as e:
            output.debug.notes.append(f"JSON parse error: {e}")

    def _select_recommended_email(self, output: DiscoveryOutput) -> None:
        """
        Rank all discovered emails and pick the best one for contacting the fair organization.
        Sets output.contact_info.recommended_email and recommended_email_reason.
        """
        if not output.contact_info.emails:
            return

        official_domain = output.official_domain or ''
        fair_name_lower = (output.fair_name or '').lower()

        # Prefixes that strongly suggest a fair-organization contact
        org_prefixes = [
            'info', 'contact', 'exhibitor', 'exposant', 'aussteller',
            'expo', 'fair', 'messe', 'salon', 'beurs', 'stand',
            'technical', 'service', 'logistics', 'operations',
        ]

        # Prefixes to penalise — unlikely to be the right contact
        bad_prefixes = [
            'noreply', 'no-reply', 'newsletter', 'marketing', 'hr',
            'jobs', 'career', 'webmaster', 'privacy', 'press',
            'media', 'sales', 'recruitment', 'billing', 'invoice',
            'support',  # often generic IT support, not fair org
        ]

        best_score = -999
        best_email = None
        best_reason_parts = []

        for ce in output.contact_info.emails:
            email = ce.email.lower().strip()
            local_part = email.split('@')[0] if '@' in email else ''
            domain = email.split('@')[1] if '@' in email else ''
            context_lower = (ce.context or '').lower()
            source_url = (ce.source_url or '').lower()

            score = 0
            reasons = []

            # 1. Domain matches the fair's official website → strong signal
            if official_domain and official_domain in domain:
                score += 30
                reasons.append("domein komt overeen met beurswebsite")

            # 2. Good prefix
            for prefix in org_prefixes:
                if local_part.startswith(prefix) or local_part == prefix:
                    score += 20
                    reasons.append(f"adresprefix '{local_part}' duidt op organisatie")
                    break

            # 3. Bad prefix
            for prefix in bad_prefixes:
                if local_part.startswith(prefix):
                    score -= 40
                    reasons.append(f"adresprefix '{local_part}' is waarschijnlijk niet relevant")
                    break

            # 4. Context mentions exhibitor / stand / logistics / technical
            exhibitor_keywords = [
                'exhibitor', 'exposant', 'aussteller', 'stand',
                'technical', 'logistics', 'service', 'bouw', 'construction',
            ]
            for kw in exhibitor_keywords:
                if kw in context_lower:
                    score += 10
                    reasons.append(f"context bevat '{kw}'")
                    break

            # 5. Source type bonus — mailto links are intentional
            if ce.context and ce.context in ('mailto',):
                score += 5
            # Source from contact page
            source_type = getattr(ce, 'source_type', '') or ''
            if 'contact' in source_url or 'contact' in source_type:
                score += 5
                reasons.append("gevonden op contactpagina")

            # 6. Extracted from PDF (exhibitor manual) → good signal
            if 'pdf' in context_lower or 'extracted from pdf' in context_lower:
                score += 8
                reasons.append("gevonden in PDF document")

            # 7. Penalise generic image/icon filenames accidentally captured
            if any(x in email for x in ['.png', '.jpg', '.gif', '.svg']):
                score -= 100

            if score > best_score:
                best_score = score
                best_email = ce.email
                best_reason_parts = reasons

        if best_email and best_score > 0:
            reason = '; '.join(best_reason_parts) if best_reason_parts else 'best beschikbare match'
            output.contact_info.recommended_email = best_email
            output.contact_info.recommended_email_reason = reason
            self._log(f"⭐ Aanbevolen email: {best_email} (score {best_score}: {reason})")
        elif best_email:
            # All scored ≤ 0 — still pick the best but flag uncertainty
            output.contact_info.recommended_email = best_email
            output.contact_info.recommended_email_reason = "geen sterke indicatie — controleer handmatig"
            self._log(f"⚠️ Aanbevolen email (lage zekerheid): {best_email}")

    def _generate_email_draft(self, output: DiscoveryOutput, input_data: TestCaseInput) -> Optional[str]:
        """
        Generate an email draft requesting missing documents.
        Returns None if all documents are found.
        """
        # Determine what's missing
        missing_items = []
        missing_items_en = []

        if output.quality.floorplan == "missing":
            missing_items.append("plattegrond/hallenplan")
            missing_items_en.append("floor plan / hall plan")

        if output.quality.exhibitor_manual == "missing":
            missing_items.append("exposanten handleiding/manual")
            missing_items_en.append("exhibitor manual / handbook")

        if output.quality.rules == "missing":
            missing_items.append("technische richtlijnen/voorschriften")
            missing_items_en.append("technical guidelines / regulations")

        if output.quality.schedule == "missing":
            missing_items.append("opbouw- en afbouwschema met tijden")
            missing_items_en.append("build-up and tear-down schedule with times")

        # If nothing is missing, no need for an email
        if not missing_items:
            return None

        fair_name = input_data.fair_name
        city = input_data.city or ""
        client_name = input_data.client_name or ""

        # Build client context for the email
        if client_name:
            dutch_client_context = f"Wij zijn de standbouwer voor {client_name} en bereiden ons voor op {fair_name}{f' in {city}' if city else ''}."
            english_client_context = f"We are the stand construction company for {client_name}, preparing for {fair_name}{f' in {city}' if city else ''}."
        else:
            dutch_client_context = f"Wij zijn een standbouwbedrijf en bereiden ons voor op {fair_name}{f' in {city}' if city else ''}."
            english_client_context = f"We are a stand construction company preparing for {fair_name}{f' in {city}' if city else ''}."

        # Generate Dutch version
        dutch_email = f"""Onderwerp: Informatieverzoek standbouw {fair_name}{f' - {client_name}' if client_name else ''}

Geachte heer/mevrouw,

{dutch_client_context}

Voor de voorbereiding van de standbouw hebben wij de volgende documenten/informatie nodig die wij niet op uw website hebben kunnen vinden:

{chr(10).join(f'• {item}' for item in missing_items)}

Zou u ons deze informatie kunnen toesturen of kunnen aangeven waar wij deze kunnen vinden?

Bij voorbaat dank voor uw medewerking.

Met vriendelijke groet,

[Uw naam]
[Bedrijfsnaam]
[Contactgegevens]"""

        # Generate English version
        english_email = f"""Subject: Information request for stand construction at {fair_name}{f' - {client_name}' if client_name else ''}

Dear Sir/Madam,

{english_client_context}

For the preparation of the stand construction, we require the following documents/information which we could not find on your website:

{chr(10).join(f'• {item}' for item in missing_items_en)}

Could you please send us this information or indicate where we can find it?

Thank you in advance for your cooperation.

Kind regards,

[Your name]
[Company name]
[Contact details]"""

        # Return both versions
        return f"""=== CONCEPT EMAIL (NEDERLANDS) ===

{dutch_email}

=== DRAFT EMAIL (ENGLISH) ===

{english_email}"""

    def _build_output_from_classification(
        self,
        classification: ClassificationResult,
        output: DiscoveryOutput,
        input_data: TestCaseInput,
        pre_scan_results: dict,
        start_time: float
    ) -> DiscoveryOutput:
        """
        Build output directly from classification results (no browser agent needed).
        This is used when the prescan + classification found all required documents
        with STRONG confidence (year verified, fair verified).
        """
        # Set official URL/domain
        if input_data.known_url:
            output.official_url = input_data.known_url
            output.official_domain = urlparse(input_data.known_url).netloc

        # Map classified documents to output (ONLY strong confidence counts)
        if classification.floorplan and classification.floorplan.confidence == 'strong':
            output.documents.floorplan_url = classification.floorplan.url
            output.quality.floorplan = "strong"
            output.primary_reasoning.floorplan = f"PRE-SCAN GEVALIDEERD: {classification.floorplan.reason} (jaar: {classification.floorplan.year_verified}, beurs: {classification.floorplan.fair_verified})"

        if classification.exhibitor_manual and classification.exhibitor_manual.confidence == 'strong':
            output.documents.exhibitor_manual_url = classification.exhibitor_manual.url
            output.quality.exhibitor_manual = "strong"
            output.primary_reasoning.exhibitor_manual = f"PRE-SCAN GEVALIDEERD: {classification.exhibitor_manual.reason} (jaar: {classification.exhibitor_manual.year_verified}, beurs: {classification.exhibitor_manual.fair_verified})"

        if classification.rules and classification.rules.confidence == 'strong':
            output.documents.rules_url = classification.rules.url
            output.quality.rules = "strong"
            output.primary_reasoning.rules = f"PRE-SCAN GEVALIDEERD: {classification.rules.reason} (jaar: {classification.rules.year_verified}, beurs: {classification.rules.fair_verified})"

        if classification.schedule and classification.schedule.confidence in ['strong', 'partial']:
            output.documents.schedule_page_url = classification.schedule.url
            output.quality.schedule = classification.schedule.confidence
            output.primary_reasoning.schedule = f"PRE-SCAN GEVALIDEERD: {classification.schedule.reason}"

        if classification.exhibitor_directory:
            output.documents.exhibitor_directory_url = classification.exhibitor_directory
            output.quality.exhibitor_directory = "strong"
            output.primary_reasoning.exhibitor_directory = "PRE-SCAN: Exhibitor directory page gevonden"

        # Add any downloads page from pre-scan
        if pre_scan_results.get('exhibitor_pages'):
            for page in pre_scan_results['exhibitor_pages']:
                page_lower = page.lower()
                if any(kw in page_lower for kw in ['download', 'document', 'resource']):
                    output.documents.downloads_overview_url = page
                    break

        # Add extracted schedules from PDFs (with deduplication by date+time)
        if classification.aggregated_schedule:
            seen_build_up = {(e.date, e.time) for e in output.schedule.build_up}
            for entry in classification.aggregated_schedule.build_up:
                if entry.get('date'):
                    dedup_key = (entry.get('date'), entry.get('time', ''))
                    if dedup_key not in seen_build_up:
                        seen_build_up.add(dedup_key)
                        output.schedule.build_up.append(ScheduleEntry(
                            date=entry.get('date'),
                            time=entry.get('time', ''),
                            description=entry.get('description', 'Build-up'),
                            source_url=classification.aggregated_schedule.source_url or output.documents.exhibitor_manual_url or ''
                        ))
            seen_tear_down = {(e.date, e.time) for e in output.schedule.tear_down}
            for entry in classification.aggregated_schedule.tear_down:
                if entry.get('date'):
                    dedup_key = (entry.get('date'), entry.get('time', ''))
                    if dedup_key not in seen_tear_down:
                        seen_tear_down.add(dedup_key)
                        output.schedule.tear_down.append(ScheduleEntry(
                            date=entry.get('date'),
                            time=entry.get('time', ''),
                            description=entry.get('description', 'Tear-down'),
                            source_url=classification.aggregated_schedule.source_url or output.documents.exhibitor_manual_url or ''
                        ))
            if output.schedule.build_up or output.schedule.tear_down:
                output.quality.schedule = "strong"
                output.primary_reasoning.schedule = f"PRE-SCAN: Schema geëxtraheerd uit PDF ({len(output.schedule.build_up)} opbouw, {len(output.schedule.tear_down)} afbouw entries)"
                self._log(f"📅 Added schedule from PDF: {len(output.schedule.build_up)} build-up, {len(output.schedule.tear_down)} tear-down")

        # Add extracted contacts from PDFs
        if classification.aggregated_contacts:
            for email in classification.aggregated_contacts.emails:
                if email and '@' in email:
                    output.contact_info.emails.append(ContactEmail(
                        email=email,
                        context=f"Extracted from PDF by LLM",
                        source_url=classification.aggregated_contacts.source_url or ''
                    ))
            if classification.aggregated_contacts.organization:
                output.contact_info.organization_name = classification.aggregated_contacts.organization
            self._log(f"📧 Added contacts from PDF: {len(classification.aggregated_contacts.emails)} emails")

        # Also add emails from pre-scan (webpage mailto links)
        if pre_scan_results.get('emails'):
            for email_data in pre_scan_results['emails']:
                # Avoid duplicates
                existing_emails = [e.email for e in output.contact_info.emails]
                if email_data['email'] not in existing_emails:
                    output.contact_info.emails.append(ContactEmail(
                        email=email_data['email'],
                        context=email_data.get('context', ''),
                        source_url=email_data.get('source_url', '')
                    ))
            self._log(f"Added {len(pre_scan_results['emails'])} contact emails from webpage")

        # Select recommended email for fair organization
        self._select_recommended_email(output)

        # Generate email draft if anything is still missing
        output.email_draft_if_missing = self._generate_email_draft(output, input_data)

        # Record debug info
        elapsed_time = int(time.time() - start_time)
        strong_count = sum([
            1 if classification.floorplan and classification.floorplan.confidence == 'strong' else 0,
            1 if classification.exhibitor_manual and classification.exhibitor_manual.confidence == 'strong' else 0,
            1 if classification.rules and classification.rules.confidence == 'strong' else 0,
            1 if classification.schedule and classification.schedule.confidence == 'strong' else 0,
            1 if classification.exhibitor_directory else 0,
        ])

        output.debug.notes.append("🚀 SNELLE MODUS: Documenten gevonden via pre-scan + LLM classificatie")
        output.debug.notes.append(f"KWALITEITSCHECK: {strong_count}/5 documenten met STRONG confidence")
        output.debug.notes.append(f"Browser agent overgeslagen - alle kritieke documenten gevalideerd")
        output.debug.notes.append(f"Totale tijd: {elapsed_time}s (vs ~5-7 minuten met browser agent)")

        if classification.missing_types:
            output.debug.notes.append(f"Niet gevonden (niet kritiek): {', '.join(classification.missing_types)}")

        self._log(f"✅ Output gebouwd uit pre-scan classificatie in {elapsed_time}s")

        return output


async def run_discovery(
    fair_name: str,
    known_url: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    client_name: Optional[str] = None,
    api_key: Optional[str] = None,
    on_status: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
    """
    Run a discovery and return the result as a dictionary.

    This is the main entry point for the Streamlit app.

    Args:
        fair_name: Name of the trade fair
        known_url: Known URL of the fair website
        city: City where the fair takes place
        country: Country where the fair takes place
        client_name: Name of the client we're building a stand for (used in email draft)
        api_key: Anthropic API key
        on_status: Callback function for status updates
    """
    input_data = TestCaseInput(
        fair_name=fair_name,
        known_url=known_url,
        city=city,
        country=country,
        client_name=client_name
    )

    agent = ClaudeAgent(
        api_key=api_key,
        max_iterations=40,
        debug=True,
        on_status=on_status
    )

    output = await agent.run(input_data)
    return output_to_dict(output)
