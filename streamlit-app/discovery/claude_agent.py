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


class ClaudeAgent:
    """Claude Computer Use agent for trade fair discovery."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_iterations: int = 40,
        debug: bool = False,
        on_status: Optional[Callable[[str], None]] = None
    ):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.browser = BrowserController(1024, 768)
        self.max_iterations = max_iterations
        self.debug = debug
        self.on_status = on_status or (lambda x: None)

    def _log(self, message: str) -> None:
        """Log a message."""
        if self.debug:
            timestamp = time.strftime('%H:%M:%S')
            print(f"[{timestamp}] {message}")
        else:
            print(message)
        self.on_status(message)

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
            'emails': []  # Discovered email addresses
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

            # First word if it's a distinctive name (e.g., "PROVADA" -> "provada")
            non_numeric_words = [w for w in words if not w.isdigit()]
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
                # Also add to exhibitor_pages so agent sees them in the instructions
                if portal_url not in results['exhibitor_pages']:
                    results['exhibitor_pages'].insert(0, portal_url)  # Add at start for priority

            if verified_subdomains:
                self._log(f"  Found {len(verified_subdomains)} active exhibitor portal subdomains")

        # === WEB SEARCH FOR EXHIBITOR PORTALS ===
        # Search the web to find exhibitor manuals/portals that may not be linked from main site
        if fair_name:
            self._log(f"🔍 Searching web for exhibitor portals: {fair_name}...")
            web_search_results = await self._web_search_for_portals(fair_name)

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
            # German
            '/aussteller', '/de/aussteller', '/technik', '/de/technik',
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
                                'my.site.com',      # Salesforce community (e.g., gsma.my.site.com)
                                'force.com',        # Salesforce
                                'salesforce.com',   # Salesforce
                                'cvent.com',        # Cvent event platform
                                'eventbrite.',      # Eventbrite
                                'a]zinc.net',       # A2Z event platform
                                'expocad.',         # ExpoCad
                                'map-dynamics.',    # Map Dynamics
                                'n200.com',         # Nth Degree events
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

                    # Skip listing pages
                    lower_url = url.lower()
                    if '?pagenumber=' in lower_url or '?anno=' in lower_url or '?page=' in lower_url:
                        continue

                    await pre_scan_browser.goto(url)
                    await asyncio.sleep(0.5)
                    scanned_in_second_pass += 1

                    self._log(f"  ✓ Second-pass scan: {url}")

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

    async def _web_search_for_portals(self, fair_name: str) -> dict:
        """
        Search the web for exhibitor portals and event manuals.
        Uses DuckDuckGo HTML search (no API key required).

        Returns dict with 'pdf_links' and 'portal_urls'.
        """
        import urllib.request
        import urllib.parse
        import urllib.error

        found_pdfs = []
        found_portals = []

        # Clean fair name (remove year if present)
        clean_name = re.sub(r'\s*20\d{2}\s*', ' ', fair_name).strip()

        # Search queries to try
        search_queries = [
            f"{clean_name} exhibitor manual",
            f"{clean_name} online event manual",
            f"{clean_name} exhibitor welcome pack",
            f"{clean_name} stand build regulations",
        ]

        # Domains we're interested in (external portals)
        interesting_domains = [
            'my.site.com',      # Salesforce community
            'force.com',        # Salesforce
            'salesforce.com',   # Salesforce
            'cvent.com',        # Cvent
            'a2zinc.net',       # A2Z events
            'expocad.com',      # ExpoCad
            'smallworldlabs.com',  # Small World Labs (Seafood Expo)
            'event-assets.',    # GSMA event assets
            'gsma.com',         # GSMA directly
        ]

        for query in search_queries[:3]:  # Check 3 searches
            try:
                # Use DuckDuckGo HTML search
                encoded_query = urllib.parse.quote_plus(query)
                search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

                req = urllib.request.Request(
                    search_url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                )

                with urllib.request.urlopen(req, timeout=10) as response:
                    html = response.read().decode('utf-8', errors='ignore')

                # Extract URLs from DuckDuckGo results
                # DuckDuckGo uses uddg= parameter for actual URLs
                url_pattern = r'uddg=([^&"]+)'
                matches = re.findall(url_pattern, html)

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
                            'stand-build', 'welcome-pack', 'welcomepack'
                        ])

                        if not (is_interesting or has_keywords):
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

            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                self._log(f"    Web search error: {e}")
                continue
            except Exception as e:
                self._log(f"    Web search error: {e}")
                continue

        return {
            'pdf_links': found_pdfs[:5],
            'portal_urls': found_portals[:5]
        }

    async def run(self, input_data: TestCaseInput) -> DiscoveryOutput:
        """Run the discovery agent."""
        output = create_empty_output(input_data.fair_name)
        output.city = input_data.city
        output.country = input_data.country

        start_time = time.time()

        try:
            # PHASE 1: Pre-scan website for documents (HTML-based, fast)
            start_url = input_data.known_url or f"https://www.google.com/search?q={input_data.fair_name}+official+website"

            pre_scan_results = None
            pre_scan_info = ""

            if input_data.known_url:
                pre_scan_results = await self._pre_scan_website(input_data.known_url, input_data.fair_name)

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

            # PHASE 2: Launch browser for visual verification
            await self.browser.launch()
            self._log("Browser launched")

            await self.browser.goto(start_url)
            self._log(f"Navigated to: {start_url}")

            # Build initial message with pre-scan results
            user_message = f"""
Vind informatie voor de beurs: {input_data.fair_name}
{f'Stad: {input_data.city}' if input_data.city else ''}
{f'Land: {input_data.country}' if input_data.country else ''}
{f'Start URL: {input_data.known_url}' if input_data.known_url else ''}
{pre_scan_info}

{'BELANGRIJK: De pre-scan heeft al documenten gevonden! Gebruik goto_url om ze te valideren.' if pre_scan_results and pre_scan_results['pdf_links'] else 'Navigeer door de website en vind alle gevraagde documenten.'}
"""

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

            while not done and iteration < self.max_iterations:
                iteration += 1
                self._log(f"Iteration {iteration}/{self.max_iterations}")

                # Mid-point check - encourage deeper exploration
                if iteration == 20:
                    messages.append({
                        "role": "user",
                        "content": [{"type": "text", "text": """📊 TUSSENTIJDSE CHECK (iteratie 20/40):

Heb je AL deze secties al bezocht?
1. ✓ Exhibitor/For Exhibitors sectie
2. ✓ Downloads/Documents/Service Documentation
3. ✓ Technical regulations / Stand design provisions
4. ✓ Participate / How to exhibit sectie
5. ✓ Subdomeinen (exhibitors.xxx.com)

Als je NOG NIET alle documenten hebt gevonden:
- Zoek naar "Technical regulations" of "Provisions for stand design" links
- Klik op ALLE accordion/dropdown items (+ of ▼ icons)
- Scroll volledig door download pagina's
- Probeer alternatieve paden: /en/exhibitors, /services, /participate

Je hebt nog 20 acties - gebruik ze om DIEPER te zoeken!"""}],
                    })

                # Warn agent to wrap up when approaching limit
                if iteration == self.max_iterations - 5:
                    messages.append({
                        "role": "user",
                        "content": [{"type": "text", "text": """⚠️ Je hebt nog 5 acties over. Begin nu met je JSON samenvatting.

BELANGRIJK: Voeg voor elk document validation_notes toe die bewijzen dat het aan de criteria voldoet!
- Als een document NIET aan de criteria voldeed, zet url op null en leg uit waarom in validation
- Wees EERLIJK: alleen "VOLDOET" als het echt aan alle criteria voldoet
- Bij twijfel: "NIET GEVONDEN" is beter dan een verkeerd document accepteren"""}],
                    })

                # Call Claude with computer use
                response = self.client.beta.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
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

            output.debug.notes.append(f"Agent completed in {iteration} iterations")
            output.debug.notes.append(f"Auto-mapped {len(downloads)} downloaded files to output fields")
            output.debug.notes.append(f"Total time: {int(time.time() - start_time)}s")

            # Add discovered emails to output
            if pre_scan_results and pre_scan_results.get('emails'):
                for email_data in pre_scan_results['emails']:
                    output.contact_info.emails.append(ContactEmail(
                        email=email_data['email'],
                        context=email_data.get('context', ''),
                        source_url=email_data.get('source_url', '')
                    ))
                self._log(f"Added {len(pre_scan_results['emails'])} contact emails to output")

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

            result_text += "\n" + "=" * 60
            result_text += "\n💡 TIP: Gebruik goto_url om direct naar een PDF te navigeren!"

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
                build_up = schedule.get("build_up", [])
                if isinstance(build_up, list):
                    for entry in build_up:
                        output.schedule.build_up.append(ScheduleEntry(
                            date=entry.get("date"),
                            time=entry.get("time"),
                            description=entry.get("description", ""),
                            source_url=output.documents.exhibitor_manual_url or output.official_url or ""
                        ))

                tear_down = schedule.get("tear_down", [])
                if isinstance(tear_down, list):
                    for entry in tear_down:
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
