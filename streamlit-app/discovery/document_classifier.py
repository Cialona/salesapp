"""
Document Classifier Module

Uses a fast LLM (Haiku) to classify and validate PDFs found during prescan.
This allows us to skip the expensive browser agent when documents are already found.

QUALITY ASSURANCE:
- Only accepts "strong" confidence for skipping browser agent
- Requires year match (2026) in document content
- Requires fair name or venue name match
- Extracts additional info (schedules, emails) from validated documents
- Cross-references documents to find info across document types
- Generates search strategies for missing documents
"""

import re
import io
import json
import asyncio
import tempfile
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse
import urllib.request
import urllib.error

# Central document type registry — single source of truth
from discovery.document_types import (
    DOCUMENT_TYPES,
    get_known_floorplan_providers,
    get_content_keywords,
    get_title_keywords,
    get_scoring_keywords,
    get_type_search_hints,
    get_llm_classification_prompt,
)

# Try to import PDF library
try:
    import pypdf
    PDF_SUPPORT = True
except ImportError:
    try:
        import PyPDF2 as pypdf
        PDF_SUPPORT = True
    except ImportError:
        PDF_SUPPORT = False


@dataclass
class ExtractedSchedule:
    """Schedule info extracted from a document."""
    build_up: List[Dict] = field(default_factory=list)  # [{date, time, description}]
    tear_down: List[Dict] = field(default_factory=list)
    source_url: str = ""


@dataclass
class ExtractedContact:
    """Contact info extracted from a document."""
    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    organization: Optional[str] = None
    source_url: str = ""


@dataclass
class DocumentClassification:
    """Classification result for a single document."""
    url: str
    document_type: str  # floorplan, exhibitor_manual, rules, schedule, unknown
    confidence: str  # strong, partial, weak, none
    year: Optional[str] = None
    title: Optional[str] = None
    reason: str = ""
    is_validated: bool = False
    text_excerpt: str = ""

    # Quality checks (all must pass for "strong" confidence)
    year_verified: bool = False  # Document contains target year
    fair_verified: bool = False  # Document mentions fair/venue name
    content_verified: bool = False  # Document has meaningful content

    # Extracted additional info
    extracted_schedule: Optional[ExtractedSchedule] = None
    extracted_contacts: Optional[ExtractedContact] = None

    # Cross-reference info extracted from document
    venue_name: Optional[str] = None  # Venue name mentioned in document
    document_references: List[str] = field(default_factory=list)  # URLs/references to other docs
    also_contains: List[str] = field(default_factory=list)  # Other doc types found in this doc


@dataclass
class ClassificationResult:
    """Overall classification results for all document types."""
    floorplan: Optional[DocumentClassification] = None
    exhibitor_manual: Optional[DocumentClassification] = None
    rules: Optional[DocumentClassification] = None
    schedule: Optional[DocumentClassification] = None
    exhibitor_directory: Optional[str] = None  # URL only, no PDF validation needed

    # Summary
    all_found: bool = False
    missing_types: List[str] = field(default_factory=list)
    found_types: List[str] = field(default_factory=list)

    # Quality gate: can we safely skip the browser agent?
    skip_agent_safe: bool = False
    skip_agent_reason: str = ""

    # Aggregated extracted info from all documents
    aggregated_schedule: Optional[ExtractedSchedule] = None
    aggregated_contacts: Optional[ExtractedContact] = None

    # Cross-reference results
    detected_venue: Optional[str] = None  # Venue name detected from documents
    search_hints: List[str] = field(default_factory=list)  # Specific search hints for missing docs
    extra_urls_to_scan: List[str] = field(default_factory=list)  # URLs found in documents to scan

    def get_missing_prompt_section(self) -> str:
        """Generate prompt section describing what's missing with specific search hints."""
        if not self.missing_types:
            return ""

        type_descriptions = {
            'floorplan': 'Plattegrond/floorplan van de beurshallen',
            'exhibitor_manual': 'Exposanten handleiding/manual met standbouw regels',
            'rules': 'Technische richtlijnen/regulations voor standbouw (BEURS-SPECIFIEK, niet van de venue!)',
            'schedule': 'Opbouw/afbouw schema met datums en tijden',
        }

        # Search hints from central document_types registry
        type_search_hints = {
            doc_type: get_type_search_hints(doc_type)
            for doc_type in DOCUMENT_TYPES
        }

        lines = ["NOG TE VINDEN (focus hierop):"]
        for doc_type in self.missing_types:
            desc = type_descriptions.get(doc_type, doc_type)
            lines.append(f"  ✗ {doc_type}: {desc}")
            hints = type_search_hints.get(doc_type, [])
            for hint in hints:
                lines.append(f"    → {hint}")

        # Add document references as extra hints
        if self.extra_urls_to_scan:
            lines.append("\n  📎 REFERENTIES GEVONDEN IN ANDERE DOCUMENTEN:")
            for url in self.extra_urls_to_scan[:5]:
                lines.append(f"    → Bekijk: {url}")

        return "\n".join(lines)

    def get_found_prompt_section(self) -> str:
        """Generate prompt section describing what's already found."""
        if not self.found_types:
            return ""

        lines = ["REEDS GEVONDEN (niet meer zoeken):"]

        # Only show documents with STRONG confidence as truly found
        if self.floorplan and self.floorplan.confidence == 'strong':
            lines.append(f"  ✓ floorplan: {self.floorplan.url}")
        if self.exhibitor_manual and self.exhibitor_manual.confidence == 'strong':
            lines.append(f"  ✓ exhibitor_manual: {self.exhibitor_manual.url}")
        if self.rules and self.rules.confidence == 'strong':
            lines.append(f"  ✓ rules: {self.rules.url}")
        if self.schedule and self.schedule.confidence == 'strong':
            lines.append(f"  ✓ schedule: {self.schedule.url}")
        if self.exhibitor_directory:
            lines.append(f"  ✓ exhibitor_directory: {self.exhibitor_directory}")

        return "\n".join(lines)


class DocumentClassifier:
    """Classifies and validates documents found during prescan."""

    def __init__(self, anthropic_client, log_callback=None):
        self.client = anthropic_client
        self.log = log_callback or print

    async def classify_documents(
        self,
        pdf_links: List[Dict],
        fair_name: str,
        target_year: str = "2026",
        exhibitor_pages: List[str] = None,
        portal_pages: List[Dict] = None,
        fair_url: str = "",
        city: str = "",
    ) -> ClassificationResult:
        """
        Classify all found PDFs and portal pages, determine what's found vs missing.

        QUALITY REQUIREMENTS for skipping browser agent:
        - Document must have "strong" confidence
        - Document must contain the target year (2026)
        - Document must mention the fair or venue name
        - PDF must have extractable content (not empty/corrupt)

        portal_pages: List of {url, text_content, page_title, detected_type} from portal scan
        """
        result = ClassificationResult()

        self.log(f"📋 Classifying {len(pdf_links)} documents for {fair_name}...")

        # Extract fair name variations for matching
        fair_name_lower = fair_name.lower()
        fair_keywords = self._extract_fair_keywords(fair_name)
        self.log(f"  Fair keywords for matching: {fair_keywords}")

        # Build edition exclusion keywords to filter wrong editions of same fair
        # E.g., Greentech Amsterdam should not match "greentech-americas" or "greentech-asia"
        edition_exclusions = self._build_edition_exclusions(fair_name, city)
        if edition_exclusions:
            self.log(f"  Edition exclusions: {edition_exclusions}")

        # First pass: LLM-based batch classification
        # Instead of brittle keyword matching, send all PDF URLs to Haiku in one call.
        # Haiku understands context (e.g., "btb_en.pdf" = Betriebstechnische Bestimmungen = rules)
        # and can classify in any language (DE, NL, FR, IT, ES, EN).
        candidates = await self._llm_batch_classify_pdfs(pdf_links, fair_name, target_year)

        # Second pass: Validate best candidates with LLM (STRICT validation)
        for doc_type, pdfs in candidates.items():
            if not pdfs:
                continue

            # Sort by year (prefer target year) and take top candidates
            def sort_by_relevance(pdf):
                year = pdf.get('year') if isinstance(pdf, dict) else None
                if year == target_year:
                    return 0
                elif year and year > target_year:
                    return 1
                elif year:
                    return 2
                return 3

            sorted_pdfs = sorted(pdfs, key=sort_by_relevance)

            # Validate top candidate(s) with STRICT criteria
            for pdf in sorted_pdfs[:3]:  # Check top 3 candidates
                url = pdf.get('url', '') if isinstance(pdf, dict) else pdf
                classification = await self._validate_pdf_strict(
                    url, doc_type, fair_name, fair_keywords, target_year,
                    city=city, edition_exclusions=edition_exclusions,
                )

                if classification.confidence == 'strong':
                    setattr(result, doc_type, classification)
                    self.log(f"  ✓ {doc_type}: STRONG ✓year={classification.year_verified} ✓fair={classification.fair_verified}")
                    self.log(f"    URL: {url[:70]}...")
                    break
                elif classification.confidence == 'partial' and not getattr(result, doc_type):
                    # Store partial as fallback, but keep looking for strong
                    setattr(result, doc_type, classification)
                    self.log(f"  ~ {doc_type}: partial (year={classification.year_verified}, fair={classification.fair_verified})")

            if not getattr(result, doc_type):
                self.log(f"  ✗ {doc_type}: geen valide document gevonden")

        # PORTAL PAGES PHASE: Classify web page content from external portals
        # This fills gaps that PDFs can't fill (e.g., Salesforce OEM portals)
        if portal_pages:
            self.log(f"🌐 Classifying {len(portal_pages)} portal pages...")
            await self._classify_portal_pages(
                portal_pages, result, fair_name, fair_keywords, target_year,
                city=city, edition_exclusions=edition_exclusions,
            )

        # CROSS-REFERENCE PHASE: Use already-validated docs to fill gaps
        # If an exhibitor manual also contains rules/schedule, use it for those types too
        self.log("🔄 Cross-referencing validated documents...")
        for doc_type in ['exhibitor_manual', 'rules', 'schedule', 'floorplan']:
            classification = getattr(result, doc_type)
            if not classification or not classification.also_contains:
                continue

            for also_type in classification.also_contains:
                # Only fill gaps — cross-references should NOT override dedicated pages
                existing = getattr(result, also_type, None)
                if not existing:
                    # Cross-referenced entries use 'partial' confidence (indirect source)
                    # This ensures dedicated portal sub-pages can still override them
                    cross_ref = DocumentClassification(
                        url=classification.url,
                        document_type=also_type,
                        confidence='partial',
                        year=classification.year,
                        title=f"{classification.title} (bevat ook {also_type})" if classification.title else None,
                        reason=f"Cross-reference: gevonden in {doc_type} document",
                        is_validated=classification.is_validated,
                        text_excerpt=classification.text_excerpt,
                        year_verified=classification.year_verified,
                        fair_verified=classification.fair_verified,
                        content_verified=classification.content_verified,
                        extracted_schedule=classification.extracted_schedule,
                        extracted_contacts=classification.extracted_contacts,
                    )
                    setattr(result, also_type, cross_ref)
                    self.log(f"  🔄 Cross-ref: {doc_type} document bevat ook {also_type} info (partial) → {classification.url[:60]}...")

        # Collect document references for secondary scan
        all_references = []
        for doc_type in ['exhibitor_manual', 'rules', 'schedule', 'floorplan']:
            classification = getattr(result, doc_type)
            if classification and classification.document_references:
                for ref in classification.document_references:
                    if ref and ref.startswith('http') and ref not in all_references:
                        all_references.append(ref)
                        self.log(f"  📎 Document reference found: {ref[:60]}...")
        result.extra_urls_to_scan = all_references

        # Check for exhibitor directory (URL-based, no PDF validation)
        # Use scoring to prefer actual directory/list pages over resource pages
        if exhibitor_pages:
            best_directory = None
            best_score = -1

            # Extract fair's base domain for cross-fair prevention
            fair_base_domain = ''
            if fair_url:
                try:
                    fair_base_domain = urlparse(fair_url).netloc.lower().replace('www.', '')
                except Exception:
                    pass

            for page in exhibitor_pages:
                page_lower = page.lower()
                parsed_page = urlparse(page_lower)
                page_host = parsed_page.netloc.replace('www.', '')
                page_path = parsed_page.path.rstrip('/')
                score = 0

                # Strong directory indicators (high score)
                if page_path.endswith('/exhibitors') or page_path.endswith('/exhibitor-list') or page_path.endswith('/exhibitor-lists'):
                    score += 10  # Exact exhibitor directory path
                if any(kw in page_path for kw in ['directory', 'catalogue', 'catalog', '/exhibitors']):
                    score += 5
                if any(kw in page_path for kw in ['exhibitor-list', 'exhibitor list', '/companies', '/espositori', '/aussteller']):
                    score += 5
                if any(kw in page_path for kw in ['/list', 'exposant']):
                    score += 3

                # Weak indicators (these might be resource pages, not directories)
                if 'exhibitor' in page_path and score == 0:
                    score += 1

                # Penalty for non-directory pages
                if any(kw in page_path for kw in ['resource', 'service', 'download', 'manual', 'guide', 'technical',
                                                    'checklist', 'register', 'login', 'dashboard', 'faq',
                                                    'shipping', 'marketing', 'contact', 'order', 'profile']):
                    score -= 3

                # DOMAIN MATCHING: prevent cross-fair contamination
                # Bonus for URLs on the same domain as the fair's website
                if fair_base_domain and fair_base_domain in page_host:
                    score += 8  # Strong bonus for same domain
                elif fair_base_domain:
                    # Check if ANY fair name keyword appears in the hostname
                    # e.g., "mwcbarcelona" in URL when fair is "MWC 2026"
                    host_has_fair_keyword = any(kw in page_host for kw in fair_keywords if len(kw) >= 4)
                    if not host_has_fair_keyword:
                        # Different domain without fair name → likely cross-fair contamination
                        score -= 6

                # EDITION MATCHING: penalise wrong-edition paths
                # E.g., /americas/exhibitors when looking for Amsterdam edition
                if edition_exclusions:
                    for excl in edition_exclusions:
                        if excl in page_path:
                            score -= 15  # Heavy penalty for wrong edition
                            break

                if score > best_score:
                    best_score = score
                    best_directory = page

            if best_directory and best_score > 0:
                result.exhibitor_directory = best_directory
                self.log(f"  ✓ exhibitor_directory (score={best_score}): {best_directory[:60]}...")

        # Calculate summary with STRICT quality gate
        all_types = ['floorplan', 'exhibitor_manual', 'rules', 'schedule']
        strong_count = 0

        for doc_type in all_types:
            classification = getattr(result, doc_type)
            if classification:
                if classification.confidence == 'strong':
                    result.found_types.append(doc_type)
                    strong_count += 1
                elif classification.confidence == 'partial':
                    # Partial goes to found_types but doesn't count for skip_agent_safe
                    result.found_types.append(doc_type)
                else:
                    result.missing_types.append(doc_type)
            else:
                result.missing_types.append(doc_type)

        # Add exhibitor_directory to found if present
        if result.exhibitor_directory:
            result.found_types.append('exhibitor_directory')
        else:
            result.missing_types.append('exhibitor_directory')

        result.all_found = len(result.missing_types) == 0

        # QUALITY GATE: Only skip agent when we have HIGH confidence
        # Require at least 3 documents with STRONG confidence
        if strong_count >= 3:
            result.skip_agent_safe = True
            result.skip_agent_reason = f"{strong_count} documenten met STRONG confidence gevonden"
        else:
            result.skip_agent_safe = False
            result.skip_agent_reason = f"Slechts {strong_count} documenten met STRONG confidence (minimum 3 vereist)"

        self.log(f"📊 Classificatie: {strong_count} STRONG, {len(result.found_types)} totaal gevonden")
        self.log(f"   Skip agent safe: {result.skip_agent_safe} - {result.skip_agent_reason}")

        # Aggregate extracted info from all classified documents
        await self._aggregate_extracted_info(result)

        return result

    def _extract_fair_keywords(self, fair_name: str) -> List[str]:
        """Extract keywords from fair name for matching in documents."""
        keywords = []

        # Clean and split
        clean_name = re.sub(r'20\d{2}', '', fair_name).strip()
        words = clean_name.lower().split()

        # Add full name
        keywords.append(clean_name.lower())

        # Add individual significant words (>2 chars)
        for word in words:
            if len(word) > 2 and word not in ['the', 'and', 'for', 'van', 'het', 'een']:
                keywords.append(word)

        # Add common abbreviations/variations
        if 'mwc' in clean_name.lower():
            keywords.extend(['mwc', 'mobile world congress', 'gsma'])
        if 'barcelona' in clean_name.lower():
            keywords.extend(['barcelona', 'fira', 'gran via'])

        return list(set(keywords))

    def _build_edition_exclusions(self, fair_name: str, city: str) -> List[str]:
        """Build list of URL path/filename fragments that indicate a wrong edition.

        Multi-edition fairs (Greentech, Seafood Expo, etc.) share one domain but
        have separate paths for each geographic edition.  When we know the target
        city we can exclude the other editions so documents from e.g. the Americas
        edition are not matched when looking for the Amsterdam edition.
        """
        # Map of known multi-edition fairs → {city_lower: [other_edition_slugs]}
        # Only needed for fairs whose website mixes editions under one domain.
        _EDITION_MAP = {
            'greentech': {
                'amsterdam': ['americas', 'asia'],
                'americas': ['amsterdam', 'asia'],
                'asia': ['amsterdam', 'americas'],
            },
            'seafood': {
                'barcelona': ['asia', 'north-america', 'northamerica'],
                'boston': ['asia', 'global'],
                'asia': ['global', 'north-america', 'northamerica'],
            },
            'ism': {
                'cologne': ['japan', 'india'],
                'köln': ['japan', 'india'],
                'keulen': ['japan', 'india'],
            },
        }

        fair_lower = fair_name.lower()
        city_lower = (city or '').lower().strip()
        if not city_lower:
            return []

        for fair_key, editions in _EDITION_MAP.items():
            if fair_key in fair_lower:
                exclusions = editions.get(city_lower, [])
                if exclusions:
                    return [f'/{e}' for e in exclusions] + [f'-{e}' for e in exclusions]
        return []

    async def _classify_portal_pages(
        self,
        portal_pages: List[Dict],
        result: 'ClassificationResult',
        fair_name: str,
        fair_keywords: List[str],
        target_year: str,
        city: str = "",
        edition_exclusions: List[str] = None,
    ) -> None:
        """
        Classify web page content from external portals.

        Portal pages are web pages (not PDFs) that contain exhibitor information.
        E.g., Salesforce OEM portals with stand build rules, schedules, etc.
        """
        # Map detected_type to our doc types
        type_mapping = {
            'rules': 'rules',
            'schedule': 'schedule',
            'floorplan': 'floorplan',
            'exhibitor_manual': 'exhibitor_manual',
            'unknown': None,  # Will try to detect
        }

        for page in portal_pages:
            text_content = page.get('text_content')
            page_url = page.get('url', '')

            # Skip PDFs (handled separately) and pages without content
            if page.get('is_pdf'):
                continue

            detected_type = page.get('detected_type', 'unknown')
            mapped_type = type_mapping.get(detected_type)

            # For floorplans, trust the detected_type even with minimal text —
            # interactive floor plans (Salesforce portals, JS-rendered maps)
            # have very little extractable text but ARE real floorplans.
            is_floorplan = (mapped_type == 'floorplan')
            if not text_content or (len(text_content) < 100 and not is_floorplan):
                continue

            # If type is unknown, try to detect from content
            if not mapped_type:
                mapped_type = self._detect_content_type(page_url, text_content)

            if not mapped_type:
                continue

            # Known floorplan providers: auto-classify as STRONG without LLM
            # These are definitively floorplans regardless of text content
            known_floorplan_providers = get_known_floorplan_providers()
            # Also auto-accept floorplans on portal domains (Salesforce, etc.)
            # when detected by portal scan — interactive maps have minimal text
            portal_domains = ['my.site.com', 'force.com', 'cvent.com', 'swapcard.com']
            is_portal_floorplan = (
                mapped_type == 'floorplan'
                and len(text_content or '') < 200
                and any(pd in page_url.lower() for pd in portal_domains)
            )
            # Auto-accept docs confirmed by site navigation (fair's own menu labelled it)
            # e.g., Greentech "Floor plan" → rai-productie.rai.nl
            is_nav_confirmed = page.get('nav_confirmed', False)
            # Auto-accept fair-domain floorplans whose URL matches a known floorplan
            # URL pattern (e.g., /show-layout, /floorplan, /maps, /hall-plan).
            # Interactive maps / image-based floorplans have minimal extractable text,
            # so LLM validation often fails. The URL pattern is a strong enough signal.
            floorplan_url_patterns = DOCUMENT_TYPES['floorplan'].get('url_patterns', [])
            is_url_pattern_floorplan = (
                mapped_type == 'floorplan'
                and any(pat in page_url.lower() for pat in floorplan_url_patterns)
            )
            if mapped_type == 'floorplan' and (
                any(fp in page_url.lower() for fp in known_floorplan_providers)
                or is_portal_floorplan
                or is_nav_confirmed
                or is_url_pattern_floorplan
            ):
                if is_nav_confirmed:
                    reason = 'Navigation-confirmed floorplan'
                elif is_url_pattern_floorplan:
                    reason = 'URL-pattern floorplan (e.g., /show-layout, /floorplan)'
                else:
                    reason = 'Known floorplan provider (interactive)'
                classification = DocumentClassification(
                    url=page_url,
                    document_type='floorplan',
                    confidence='strong',
                    title=page.get('page_title', 'Interactive Floorplan'),
                    reason=reason,
                    is_validated=True,
                    year_verified=True,
                    fair_verified=True,
                    content_verified=True,
                    text_excerpt=text_content[:1000],
                )
                existing = getattr(result, 'floorplan', None)
                if not existing or existing.confidence != 'strong':
                    setattr(result, 'floorplan', classification)
                    self.log(f"  ✓ {reason}: {page_url[:70]}...")
                continue

            # Nav-confirmed non-floorplan: auto-classify as STRONG
            # Fair's own navigation labelled this link (e.g., "Schedule", "Rules")
            if is_nav_confirmed and mapped_type in ('schedule', 'rules', 'exhibitor_manual', 'exhibitor_directory'):
                classification = DocumentClassification(
                    url=page_url,
                    document_type=mapped_type,
                    confidence='strong',
                    title=page.get('page_title', mapped_type),
                    reason=f'Navigation-confirmed {mapped_type}',
                    is_validated=True,
                    year_verified=True,
                    fair_verified=True,
                    content_verified=True,
                    text_excerpt=text_content[:1000],
                )
                existing = getattr(result, mapped_type, None)
                if not existing or existing.confidence != 'strong':
                    setattr(result, mapped_type, classification)
                    self.log(f"  ✓ Navigation-confirmed {mapped_type}: {page_url[:70]}...")
                continue

            # Validate the page content with LLM (same as PDF but no download needed)
            # Note: we always validate portal pages even if a STRONG classification exists,
            # because dedicated portal sub-pages (e.g., "Build up & Dismantling Schedule")
            # have richer content than PDF keyword matches or cross-references
            classification = await self._validate_page_content(
                page_url, text_content, mapped_type,
                fair_name, fair_keywords, target_year,
                page_title=page.get('page_title', ''),
                city=city,
            )

            existing = getattr(result, mapped_type, None)
            if classification.confidence == 'strong':
                should_replace = True
                if existing and existing.confidence == 'strong':
                    # Both STRONG: compare by URL/title relevance, then text length
                    new_score = self._type_relevance_score(mapped_type, page_url, page.get('page_title', ''))
                    old_score = self._type_relevance_score(mapped_type, existing.url or '', existing.title or '')
                    new_text_len = len(classification.text_excerpt or '')
                    old_text_len = len(existing.text_excerpt or '')

                    if new_score > old_score:
                        should_replace = True
                        self.log(f"  ⬆ Portal page [{mapped_type}]: overrides (better title match: {new_score} vs {old_score})")
                    elif new_score == old_score and new_text_len > old_text_len:
                        should_replace = True
                        self.log(f"  ⬆ Portal page [{mapped_type}]: overrides (more content: {new_text_len} vs {old_text_len} chars)")
                    else:
                        should_replace = False
                        self.log(f"  ≡ Portal page [{mapped_type}]: kept existing (better match)")

                if should_replace:
                    setattr(result, mapped_type, classification)
                    self.log(f"  ✓ Portal page [{mapped_type}]: STRONG ✓year={classification.year_verified} ✓fair={classification.fair_verified}")
                    self.log(f"    URL: {page_url[:70]}...")
            elif classification.confidence == 'partial' and not existing:
                setattr(result, mapped_type, classification)
                self.log(f"  ~ Portal page [{mapped_type}]: partial")
            elif mapped_type == 'schedule' and classification.confidence in ('none', 'weak'):
                # Fallback for portal schedule pages: interactive portals (Salesforce, Cvent)
                # often have schedule data in dynamically rendered tables that extract poorly.
                # The page was already detected as schedule by _detect_page_type (via URL or
                # content keywords). If the URL/title also matches schedule patterns, or if
                # the original detected_type was explicitly 'schedule', assign PARTIAL so the
                # page is eligible for LLM re-validation with portal context.
                schedule_url_slugs = [
                    'schedule', 'build-up', 'tear-down', 'dismantling', 'move-in',
                    'move-out', 'deadlines', 'key-dates', 'timetable', 'set-up',
                    'logistics', 'important-dates', 'access-policy', 'event-schedule',
                ]
                url_lower = page_url.lower()
                page_title_lower = (page.get('page_title') or '').lower()
                url_or_title = f"{url_lower} {page_title_lower}"
                has_schedule_url = any(slug in url_or_title for slug in schedule_url_slugs)
                was_detected_as_schedule = (detected_type == 'schedule')
                if has_schedule_url or was_detected_as_schedule:
                    original_conf = classification.confidence
                    classification.confidence = 'partial'
                    fallback_reason = 'URL-pattern' if has_schedule_url else 'detected_type'
                    classification.reason = (classification.reason or '') + f' [portal schedule fallback: {fallback_reason}]'
                    if not existing:
                        setattr(result, mapped_type, classification)
                        self.log(f"  ~ Portal schedule [{mapped_type}]: PARTIAL ({fallback_reason} fallback, LLM was {original_conf})")

        # Post-process: LLM-validated promotion of weak/partial portal pages.
        # If a page is from the same portal as a STRONG-classified document, we
        # re-validate with extra context (the portal is confirmed for this fair).
        verified_portal_bases: Dict[str, str] = {}  # base → verified doc_type
        for doc_type in ['exhibitor_manual', 'rules', 'schedule', 'floorplan']:
            cls = getattr(result, doc_type, None)
            if cls and cls.confidence == 'strong' and cls.year_verified and cls.url:
                base = self._get_portal_base(cls.url)
                verified_portal_bases[base] = doc_type

        if verified_portal_bases:
            # Build URL → full text content lookup from portal_pages
            page_text_map: Dict[str, str] = {}
            for page in portal_pages:
                if page.get('text_content') and page.get('url'):
                    page_text_map[page['url']] = page['text_content']

            for doc_type in ['exhibitor_manual', 'rules', 'schedule', 'floorplan']:
                cls = getattr(result, doc_type, None)
                if cls and cls.confidence in ('partial', 'weak') and cls.url:
                    base = self._get_portal_base(cls.url)
                    if base in verified_portal_bases:
                        verified_by = verified_portal_bases[base]
                        full_text = page_text_map.get(cls.url, cls.text_excerpt or '')
                        if full_text:
                            self.log(f"  🔄 Re-validating [{doc_type}] with portal context (verified via {verified_by})...")
                            new_cls = await self._revalidate_with_portal_context(
                                url=cls.url,
                                text_content=full_text,
                                expected_type=doc_type,
                                fair_name=fair_name,
                                target_year=target_year,
                                verified_by_type=verified_by,
                                portal_base=base,
                                city=city,
                            )
                            if new_cls and new_cls.confidence == 'strong':
                                setattr(result, doc_type, new_cls)
                                self.log(f"  ⬆ Promoted [{doc_type}] to STRONG (LLM confirmed, portal: {base})")
                            else:
                                self.log(f"  ✗ [{doc_type}] NOT promoted (LLM rejected: {new_cls.reason if new_cls else 'error'})")

        # For portal home pages: if we have a portal URL but haven't assigned exhibitor_manual,
        # check if the portal home page qualifies as exhibitor manual
        if not result.exhibitor_manual:
            for page in portal_pages:
                if page.get('detected_type') == 'exhibitor_manual' and page.get('text_content'):
                    # Portal home page as exhibitor manual (common pattern for OEM portals)
                    classification = await self._validate_page_content(
                        page['url'], page['text_content'], 'exhibitor_manual',
                        fair_name, fair_keywords, target_year,
                        page_title=page.get('page_title', '')
                    )
                    if classification.confidence in ['strong', 'partial']:
                        result.exhibitor_manual = classification
                        self.log(f"  ✓ Portal home as exhibitor_manual: {classification.confidence}")
                        break

    @staticmethod
    def _get_portal_base(url: str) -> str:
        """Extract portal base for grouping pages from the same portal.

        For shared-host platforms (my.site.com, force.com, cvent.com), uses
        host + first path segment to distinguish different portals on the same
        host (e.g., gsma.my.site.com/mwcoem vs gsma.my.site.com/4yfnoem).

        For dedicated portal domains (e.g., exhibitors-seg.seafoodexpo.com),
        uses just the host since all pages belong to the same portal.
        """
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        shared_hosts = ['my.site.com', 'force.com', 'cvent.com', 'swapcard.com']
        is_shared = any(sh in parsed.netloc for sh in shared_hosts)
        if is_shared and path_parts and path_parts[0]:
            return f"{parsed.netloc}/{path_parts[0]}"
        return parsed.netloc

    def _type_relevance_score(self, doc_type: str, url: str, title: str) -> int:
        """Score how well a URL/title matches a document type. Higher = better match.
        Uses scoring_keywords from central document_types registry.
        """
        combined = f"{url} {title}".lower()
        score = 0

        scoring = get_scoring_keywords(doc_type)
        if any(kw in combined for kw in scoring.get('strong', [])):
            score += 10
        if any(kw in combined for kw in scoring.get('medium', [])):
            score += 5
        if any(kw in combined for kw in scoring.get('penalties', [])):
            score -= 5

        return score

    def _detect_content_type(self, url: str, text: str) -> Optional[str]:
        """Detect document type from page URL and content.
        Uses content_keywords from central document_types registry.
        """
        combined = f"{url} {text[:1500]}".lower()

        # Check each document type's content keywords (from central registry)
        for doc_type in ['rules', 'schedule', 'floorplan']:
            if any(kw in combined for kw in get_content_keywords(doc_type)):
                return doc_type

        return None

    async def _validate_page_content(
        self,
        url: str,
        text_content: str,
        expected_type: str,
        fair_name: str,
        fair_keywords: List[str],
        target_year: str,
        page_title: str = "",
        city: str = "",
    ) -> DocumentClassification:
        """
        Validate a web page's content (same logic as _validate_pdf_strict but no PDF download).
        Used for portal pages, Salesforce sites, etc.
        """
        classification = DocumentClassification(
            url=url,
            document_type=expected_type,
            confidence='none'
        )

        try:
            if not text_content or len(text_content) < 100:
                classification.reason = "Pagina bevat te weinig tekst"
                return classification

            classification.content_verified = True
            classification.text_excerpt = text_content[:1000]

            # Check for year
            text_lower = text_content.lower()
            year_patterns = [target_year, target_year[2:]]
            classification.year_verified = any(yp in text_content for yp in year_patterns)

            # Check for fair name
            classification.fair_verified = any(kw in text_lower for kw in fair_keywords)

            # Use LLM for detailed validation (reuse same method as PDFs)
            validation_result = await self._llm_validate_and_extract(
                text_content[:10000],
                expected_type,
                fair_name,
                target_year,
                url,
                city=city,
            )

            classification.title = validation_result.get('title') or page_title
            classification.year = validation_result.get('detected_year')
            classification.reason = validation_result.get('reason', '')

            # Extract schedule
            if validation_result.get('schedule_found'):
                classification.extracted_schedule = ExtractedSchedule(
                    build_up=validation_result.get('build_up', []),
                    tear_down=validation_result.get('tear_down', []),
                    source_url=url
                )

            # Extract contacts
            if validation_result.get('emails') or validation_result.get('phones'):
                classification.extracted_contacts = ExtractedContact(
                    emails=validation_result.get('emails', []),
                    phones=validation_result.get('phones', []),
                    organization=validation_result.get('organization'),
                    source_url=url
                )

            # Cross-reference info
            classification.document_references = validation_result.get('document_references', [])
            classification.also_contains = validation_result.get('also_contains_types', [])

            # Confidence assignment (same logic as PDF)
            is_correct_type = validation_result.get('is_correct_type', False)
            is_correct_fair = validation_result.get('is_correct_fair', False) or classification.fair_verified
            is_correct_year = validation_result.get('is_correct_year', False) or classification.year_verified
            is_useful = validation_result.get('is_useful', False)

            classification.year_verified = is_correct_year
            classification.fair_verified = is_correct_fair

            if is_correct_type and is_correct_fair and is_correct_year and is_useful:
                classification.confidence = 'strong'
                classification.is_validated = True
            elif is_correct_type and (is_correct_fair or is_correct_year) and is_useful:
                classification.confidence = 'partial'
                classification.is_validated = True
            elif is_correct_type:
                classification.confidence = 'weak'
            else:
                classification.confidence = 'none'

        except Exception as e:
            classification.reason = f"Portal page validatie fout: {str(e)}"
            classification.confidence = 'none'

        return classification

    async def _revalidate_with_portal_context(
        self,
        url: str,
        text_content: str,
        expected_type: str,
        fair_name: str,
        target_year: str,
        verified_by_type: str,
        portal_base: str,
        city: str = "",
    ) -> Optional[DocumentClassification]:
        """
        Re-validate a weak/partial portal page using LLM with extra portal context.

        The key insight: if another page from the same portal has been confirmed as
        STRONG for this fair+year, then this page is also from the same fair.
        The LLM only needs to confirm the document TYPE is correct and content is useful.
        """
        type_def = DOCUMENT_TYPES.get(expected_type, {})
        expected_desc = type_def.get('llm_description', expected_type)

        city_info = f" in {city}" if city else ""

        prompt = f"""Je hervalideert een portal-pagina met extra context.

CONTEXT: Deze pagina komt van het exhibitor portal "{portal_base}".
Een andere pagina van HETZELFDE portal is al bevestigd als STRONG voor {fair_name}{city_info} ({target_year}).
Dat betekent dat dit portal specifiek is voor {fair_name} {target_year}.
De vraag is ALLEEN: bevat deze pagina nuttige {expected_type} ({expected_desc}) informatie?

DOCUMENT URL: {url}
VERWACHT TYPE: {expected_type} - {expected_desc}

PAGINA TEKST:
---
{text_content[:8000]}
---

Beantwoord in JSON formaat:
{{
  "is_correct_type": true/false,
  "is_useful": true/false,
  "reason": "korte uitleg waarom wel/niet",

  "schedule_found": true/false,
  "build_up": [
    {{"date": "2026-03-01", "time": "08:00-20:00", "description": "..."}}
  ],
  "tear_down": [
    {{"date": "2026-03-05", "time": "18:00-22:00", "description": "..."}}
  ],

  "emails": ["email@example.com"],
  "phones": ["+31 123 456 789"],
  "organization": "naam van de organisatie"
}}

BELANGRIJK:
- "is_correct_type" = ALLEEN true als dit ECHT {expected_type} content bevat
- "is_useful" = true als het nuttige, concrete info bevat (niet alleen een menu of linklijst)
- Je hoeft NIET te checken of het de juiste beurs/jaar is — dat is al bevestigd via het portal
- Extraheer WEL schedule datums, emails en telefoons als die er staan

Antwoord ALLEEN met valide JSON."""

        try:
            import random as _rnd
            response = None
            for _api_attempt in range(4):
                try:
                    response = self.client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=2000,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    break
                except Exception as rate_err:
                    if 'rate_limit' in str(rate_err).lower() or '429' in str(rate_err):
                        wait = (2 ** _api_attempt) * 3 + _rnd.uniform(0, 2)
                        self.log(f"    ⏳ API rate limit (poging {_api_attempt + 1}/4), wacht {wait:.0f}s...")
                        await asyncio.sleep(wait)
                        if _api_attempt == 3:
                            raise
                    else:
                        raise

            if response is None:
                return None

            response_text = response.content[0].text.strip()
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            validation = json.loads(response_text)

            is_correct_type = validation.get('is_correct_type', False)
            is_useful = validation.get('is_useful', False)

            if not (is_correct_type and is_useful):
                cls = DocumentClassification(
                    url=url,
                    document_type=expected_type,
                    confidence='none',
                    reason=validation.get('reason', 'LLM rejected'),
                )
                return cls

            # LLM confirmed: build STRONG classification
            cls = DocumentClassification(
                url=url,
                document_type=expected_type,
                confidence='strong',
                is_validated=True,
                year_verified=True,   # Inherited from verified portal
                fair_verified=True,   # Inherited from verified portal
                content_verified=True,
                reason=validation.get('reason', 'Portal context + LLM confirmed'),
                text_excerpt=text_content[:1000],
            )

            # Extract schedule if present
            if validation.get('schedule_found'):
                cls.extracted_schedule = ExtractedSchedule(
                    build_up=validation.get('build_up', []),
                    tear_down=validation.get('tear_down', []),
                    source_url=url,
                )

            # Extract contacts
            if validation.get('emails') or validation.get('phones'):
                cls.extracted_contacts = ExtractedContact(
                    emails=validation.get('emails', []),
                    phones=validation.get('phones', []),
                    organization=validation.get('organization'),
                    source_url=url,
                )

            return cls

        except Exception as e:
            self.log(f"    ⚠️ Re-validation error: {e}")
            return None

    async def _llm_batch_classify_pdfs(
        self,
        pdf_links: List[Dict],
        fair_name: str,
        target_year: str,
    ) -> Dict[str, List[Dict]]:
        """Use Haiku to classify all PDFs in one call based on URL + link text.

        Returns candidates dict: {doc_type: [pdf_entries]}
        This replaces brittle keyword matching with LLM understanding.
        """
        candidates = {
            'floorplan': [],
            'exhibitor_manual': [],
            'rules': [],
            'schedule': [],
        }

        if not pdf_links:
            return candidates

        # Build PDF list for the prompt (max 60 to keep prompt reasonable)
        pdf_entries = []
        for i, pdf in enumerate(pdf_links[:60]):
            url = pdf.get('url', '') if isinstance(pdf, dict) else pdf
            text = pdf.get('text', '') if isinstance(pdf, dict) else ''
            year = pdf.get('year', '') if isinstance(pdf, dict) else ''
            pdf_entries.append(f"[{i}] URL: {url}\n    Link text: {text or '(geen)'}\n    Year: {year or '?'}")

        pdf_list = "\n".join(pdf_entries)

        # Generate classification prompt from central registry
        classification_intro = get_llm_classification_prompt(fair_name, context='pdfs')

        prompt = f"""{classification_intro}

DOCUMENTEN ({target_year}):
{pdf_list}

Classificeer elk document in een van de bovenstaande categorieën.

Antwoord ALLEEN met valide JSON - een object met document indices per categorie:
{{
  "floorplan": [0, 5],
  "exhibitor_manual": [2, 8],
  "rules": [3],
  "schedule": [7],
  "skip": [1, 4, 6, 9]
}}

Regels:
- Een document kan in MEERDERE categorieën voorkomen (bijv. een manual kan ook rules bevatten)
- Prioriteer {target_year} documenten boven oudere versies
- Wees RUIM: bij twijfel, classificeer het document liever dan het te skippen
- ELKE index moet in minstens één categorie voorkomen"""

        try:
            import random as _rnd
            response = None
            for _api_attempt in range(4):
                try:
                    response = self.client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=1000,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    break
                except Exception as rate_err:
                    if 'rate_limit' in str(rate_err).lower() or '429' in str(rate_err):
                        wait = (2 ** _api_attempt) * 3 + _rnd.uniform(0, 2)
                        self.log(f"    ⏳ API rate limit (poging {_api_attempt + 1}/4), wacht {wait:.0f}s...")
                        await asyncio.sleep(wait)
                        if _api_attempt == 3:
                            raise
                    else:
                        raise

            if response is None:
                self.log("  ⚠️ LLM batch classification failed — falling back to keyword matching")
                return self._keyword_classify_pdfs(pdf_links)

            response_text = response.content[0].text.strip()

            # Parse JSON
            if "```" in response_text:
                json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(1)

            result = json.loads(response_text)

            # Map indices back to PDF entries
            for doc_type in ['floorplan', 'exhibitor_manual', 'rules', 'schedule']:
                indices = result.get(doc_type, [])
                for idx in indices:
                    if isinstance(idx, int) and 0 <= idx < len(pdf_links):
                        candidates[doc_type].append(pdf_links[idx])

            total = sum(len(v) for v in candidates.values())
            self.log(f"  🤖 LLM classificatie: {total} documents gecategoriseerd "
                     f"(fp={len(candidates['floorplan'])}, man={len(candidates['exhibitor_manual'])}, "
                     f"rules={len(candidates['rules'])}, sched={len(candidates['schedule'])})")

            return candidates

        except Exception as e:
            self.log(f"  ⚠️ LLM batch classification error: {e} — falling back to keyword matching")
            return self._keyword_classify_pdfs(pdf_links)

    def _keyword_classify_pdfs(self, pdf_links: List[Dict]) -> Dict[str, List[Dict]]:
        """Fallback: keyword-based classification if LLM batch fails.
        Uses pdf_keywords from central document_types registry.
        """
        candidates = {
            'floorplan': [],
            'exhibitor_manual': [],
            'rules': [],
            'schedule': [],
        }

        for pdf in pdf_links:
            url = pdf.get('url', '') if isinstance(pdf, dict) else pdf
            text = pdf.get('text', '') if isinstance(pdf, dict) else ''
            combined = f"{url.lower()} {text.lower()}"

            for doc_type in candidates:
                pdf_kws = get_pdf_keywords(doc_type)
                if pdf_kws and any(kw in combined for kw in pdf_kws):
                    # For floorplan, check exclusions
                    if doc_type == 'floorplan':
                        exclusions = get_pdf_exclusions(doc_type)
                        if any(excl in combined for excl in exclusions):
                            continue
                    candidates[doc_type].append(pdf)

        return candidates

    async def _validate_pdf_strict(
        self,
        url: str,
        expected_type: str,
        fair_name: str,
        fair_keywords: List[str],
        target_year: str,
        city: str = "",
        edition_exclusions: List[str] = None,
    ) -> DocumentClassification:
        """
        STRICT validation of a PDF document.

        Requirements for STRONG confidence:
        1. Document type matches expected type
        2. Document contains target year (2026)
        3. Document mentions fair/venue name
        4. Document has extractable, meaningful content
        """
        classification = DocumentClassification(
            url=url,
            document_type=expected_type,
            confidence='none'
        )

        try:
            # Download and extract PDF text
            text_content = await self._extract_pdf_text(url, max_bytes=300_000)

            if not text_content or len(text_content) < 100:
                classification.reason = "PDF bevat geen leesbare tekst of is te kort"
                classification.content_verified = False
                return classification

            classification.content_verified = True
            classification.text_excerpt = text_content[:1000]

            # Early reject: wrong edition based on URL or content
            if edition_exclusions:
                url_lower = url.lower()
                for excl in edition_exclusions:
                    if excl in url_lower:
                        classification.reason = f"Wrong edition: URL contains '{excl}'"
                        classification.confidence = 'none'
                        self.log(f"    ✗ Skipping wrong-edition PDF: {url[:60]}... (contains '{excl}')")
                        return classification

            # Check for year in content
            text_lower = text_content.lower()
            year_patterns = [target_year, target_year[2:]]  # 2026 or 26
            classification.year_verified = any(yp in text_content for yp in year_patterns)

            # Check for fair/venue name in content
            classification.fair_verified = any(kw in text_lower for kw in fair_keywords)

            # Use LLM for detailed validation and content extraction
            validation_result = await self._llm_validate_and_extract(
                text_content[:10000],  # Limit for Haiku
                expected_type,
                fair_name,
                target_year,
                url,
                city=city,
            )

            # Update classification with LLM results
            classification.title = validation_result.get('title')
            classification.year = validation_result.get('detected_year')
            classification.reason = validation_result.get('reason', '')

            # Extract schedule if present
            if validation_result.get('schedule_found'):
                classification.extracted_schedule = ExtractedSchedule(
                    build_up=validation_result.get('build_up', []),
                    tear_down=validation_result.get('tear_down', []),
                    source_url=url
                )

            # Extract contacts if present
            if validation_result.get('emails') or validation_result.get('phones'):
                classification.extracted_contacts = ExtractedContact(
                    emails=validation_result.get('emails', []),
                    phones=validation_result.get('phones', []),
                    organization=validation_result.get('organization'),
                    source_url=url
                )

            # Extract cross-reference info
            classification.document_references = validation_result.get('document_references', [])
            classification.also_contains = validation_result.get('also_contains_types', [])

            # STRICT confidence assignment
            is_correct_type = validation_result.get('is_correct_type', False)
            is_correct_fair = validation_result.get('is_correct_fair', False) or classification.fair_verified
            is_correct_year = validation_result.get('is_correct_year', False) or classification.year_verified
            is_useful = validation_result.get('is_useful', False)

            # Update verification flags with LLM results
            classification.year_verified = is_correct_year
            classification.fair_verified = is_correct_fair

            if is_correct_type and is_correct_fair and is_correct_year and is_useful:
                classification.confidence = 'strong'
                classification.is_validated = True
            elif is_correct_type and (is_correct_fair or is_correct_year) and is_useful:
                classification.confidence = 'partial'
                classification.is_validated = True
            elif is_correct_type:
                classification.confidence = 'weak'
            else:
                classification.confidence = 'none'

        except Exception as e:
            classification.reason = f"Validatie fout: {str(e)}"
            classification.confidence = 'none'

        return classification

    async def _extract_pdf_text(self, url: str, max_bytes: int = 300_000) -> str:
        """Extract text from PDF URL."""

        if not PDF_SUPPORT:
            # Fallback: just analyze URL/filename
            return f"[PDF URL: {url}] - No PDF library available"

        try:
            # Download PDF
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                }
            )

            with urllib.request.urlopen(req, timeout=20) as response:
                pdf_bytes = response.read(max_bytes)

            if len(pdf_bytes) < 1000:
                return ""  # Too small, probably an error page

            # Try to extract text
            pdf_file = io.BytesIO(pdf_bytes)

            try:
                reader = pypdf.PdfReader(pdf_file)
                text_parts = []

                # Extract from first 10 pages (for schedule/contact extraction)
                for i, page in enumerate(reader.pages[:10]):
                    try:
                        text = page.extract_text()
                        if text:
                            text_parts.append(text)
                    except:
                        continue

                return "\n".join(text_parts)

            except Exception as e:
                return f"[PDF parse error: {str(e)}]"

        except urllib.error.HTTPError as e:
            return f"[HTTP error {e.code}]"
        except Exception as e:
            return f"[Download error: {str(e)}]"

    async def _llm_validate_and_extract(
        self,
        text_content: str,
        expected_type: str,
        fair_name: str,
        target_year: str,
        url: str,
        city: str = "",
    ) -> Dict:
        """
        Use Haiku to validate document AND extract additional info.

        Returns validation results plus:
        - Schedule dates/times if found
        - Contact emails/phones if found
        - Organization name if found
        """
        # Use semantic descriptions from central document_types registry
        type_def = DOCUMENT_TYPES.get(expected_type, {})
        expected_desc = type_def.get('llm_description', expected_type)

        city_warning = ""
        if city:
            city_warning = f"""
GEZOCHTE STAD/EDITIE: {city}
⚠️ LET OP EDITIE: Sommige beurzen hebben meerdere edities (bijv. Americas, Asia, Europe).
   Dit document moet specifiek voor de {city}-editie zijn. Als het document voor een ANDERE
   editie is (bijv. Americas ipv Amsterdam, Asia ipv Barcelona), dan is "is_correct_fair" = false!"""

        prompt = f"""Analyseer dit document GRONDIG en extraheer ALLE informatie.

DOCUMENT URL: {url}
GEZOCHTE BEURS: {fair_name}
GEZOCHT JAAR: {target_year}
VERWACHT TYPE: {expected_type} - {expected_desc}{city_warning}

DOCUMENT TEKST:
---
{text_content}
---

Beantwoord in JSON formaat:
{{
  "is_correct_type": true/false,
  "is_correct_fair": true/false,
  "is_correct_year": true/false,
  "is_useful": true/false,
  "detected_year": "2024/2025/2026/unknown",
  "title": "document titel",
  "reason": "korte uitleg",

  "schedule_found": true/false,
  "build_up": [
    {{"date": "2026-03-01", "time": "08:00-20:00", "description": "..."}}
  ],
  "tear_down": [
    {{"date": "2026-03-05", "time": "18:00-22:00", "description": "..."}}
  ],

  "emails": ["email@example.com"],
  "phones": ["+31 123 456 789"],
  "organization": "naam van de organisatie",

  "document_references": ["URLs of namen van andere documenten die in dit document worden genoemd, bijv. 'Technical Guidelines available at https://...' of 'See Event Manual for details'"],
  "also_contains_types": ["andere documenttypes die dit document OOK bevat. Keuzes: 'rules', 'schedule', 'exhibitor_manual', 'floorplan'. Bijv. als een exhibitor manual ook technische regels bevat, zet 'rules'. Als het ook opbouw/afbouw datums en tijden bevat, zet 'schedule'."]
}}

KWALITEITSEISEN:
- "is_correct_type" = ALLEEN true als dit ECHT een {expected_type} is
- "is_correct_fair" = true als document {fair_name} of de beurs-organisator noemt EN het de juiste editie/locatie is{f' (moet voor {city} zijn, NIET voor een andere editie zoals Americas/Asia/etc.)' if city else ''}
- "is_correct_year" = true als document {target_year} bevat
- "is_useful" = true als document nuttige info bevat voor standbouwers

EXTRACTIE (HEEL BELANGRIJK - zoek naar ALLES):
- Zoek naar opbouw/afbouw datums en tijden (ook als dit niet het verwachte type is!)
- Maak voor ELKE rij in een opbouw/afbouw tabel een apart entry. Als er per standgrootte (bijv. "Over 950m2", "Under 25m2") verschillende startdatums zijn, maak dan voor ELKE standgrootte een apart build_up entry met de standgrootte in de description.
- Maak voor ELKE dag van afbouw een apart tear_down entry met datum en openingstijd.
- Zoek naar contact emails en telefoonnummers
- Zoek naar de naam van de organiserende partij
- Zoek naar VERWIJZINGEN naar andere documenten (URLs, documentnamen, "zie document X")
- Bevat dit document OOK info van een ander type? Bijv. een exhibitor manual/welcome pack kan ook technische regels of een opbouwschema bevatten - dit is HEEL BELANGRIJK om te detecteren!

Antwoord ALLEEN met valide JSON."""

        try:
            import random as _rnd
            response = None
            for _api_attempt in range(4):
                try:
                    response = self.client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=2000,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    break
                except Exception as rate_err:
                    if 'rate_limit' in str(rate_err).lower() or '429' in str(rate_err):
                        wait = (2 ** _api_attempt) * 3 + _rnd.uniform(0, 2)
                        self.log(f"    ⏳ API rate limit (poging {_api_attempt + 1}/4), wacht {wait:.0f}s...")
                        await asyncio.sleep(wait)
                        if _api_attempt == 3:
                            raise
                    else:
                        raise

            if response is None:
                raise RuntimeError("API call failed after retries")

            response_text = response.content[0].text.strip()

            # Parse JSON from response
            if "```" in response_text:
                json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(1)

            result = json.loads(response_text)

            return result

        except Exception as e:
            self.log(f"    LLM validation error: {e}")
            # Fallback to basic checks
            return {
                'is_correct_type': False,
                'is_correct_fair': False,
                'is_correct_year': target_year in text_content,
                'is_useful': len(text_content) > 500,
                'reason': f'LLM validatie gefaald: {str(e)}'
            }

    async def _aggregate_extracted_info(self, result: ClassificationResult) -> None:
        """Aggregate extracted info from all classified documents."""

        # Collect all schedules (deduplicate by date+time)
        all_build_up = []
        all_tear_down = []
        seen_build_up = set()
        seen_tear_down = set()
        all_emails = []
        all_phones = []
        organization = None

        for doc_type in ['exhibitor_manual', 'rules', 'schedule', 'floorplan']:
            classification = getattr(result, doc_type)
            if not classification:
                continue

            # Aggregate schedules with deduplication
            if classification.extracted_schedule:
                for entry in classification.extracted_schedule.build_up:
                    dedup_key = (entry.get('date', ''), entry.get('time', ''))
                    if dedup_key not in seen_build_up:
                        seen_build_up.add(dedup_key)
                        all_build_up.append(entry)
                for entry in classification.extracted_schedule.tear_down:
                    dedup_key = (entry.get('date', ''), entry.get('time', ''))
                    if dedup_key not in seen_tear_down:
                        seen_tear_down.add(dedup_key)
                        all_tear_down.append(entry)

            # Aggregate contacts
            if classification.extracted_contacts:
                all_emails.extend(classification.extracted_contacts.emails)
                all_phones.extend(classification.extracted_contacts.phones)
                if classification.extracted_contacts.organization and not organization:
                    organization = classification.extracted_contacts.organization

        # Store aggregated results
        if all_build_up or all_tear_down:
            result.aggregated_schedule = ExtractedSchedule(
                build_up=all_build_up,
                tear_down=all_tear_down
            )
            self.log(f"  📅 Extracted schedule: {len(all_build_up)} build-up, {len(all_tear_down)} tear-down entries")

        if all_emails or all_phones:
            result.aggregated_contacts = ExtractedContact(
                emails=list(set(all_emails)),  # Dedupe
                phones=list(set(all_phones)),
                organization=organization
            )
            self.log(f"  📧 Extracted contacts: {len(set(all_emails))} emails, {len(set(all_phones))} phones")

        # Generate search hints based on what we found
        self._generate_search_hints(result)

    def _generate_search_hints(self, result: ClassificationResult) -> None:
        """Generate specific search hints based on classification results."""
        hints = []

        # If we found an exhibitor manual but rules are missing,
        # suggest checking if rules are within the manual or referenced
        if result.exhibitor_manual and 'rules' in result.missing_types:
            if result.exhibitor_manual.also_contains and 'rules' in result.exhibitor_manual.also_contains:
                hints.append("Het exhibitor manual bevat ook technische regels - check of dit voldoende is")
            else:
                hints.append("Exhibitor manual gevonden maar geen aparte technische richtlijnen - zoek op de download pagina")

        # If schedule is missing but we found it cross-referenced
        if 'schedule' in result.missing_types:
            # Check if any found document has schedule info
            for doc_type in ['exhibitor_manual', 'rules']:
                classification = getattr(result, doc_type)
                if classification and classification.extracted_schedule:
                    if classification.extracted_schedule.build_up or classification.extracted_schedule.tear_down:
                        hints.append(f"Schema informatie gevonden in {doc_type} document")

        # If we have document references from found docs
        if result.extra_urls_to_scan:
            hints.append(f"{len(result.extra_urls_to_scan)} document-referenties gevonden in gevalideerde PDFs")

        result.search_hints = hints
        if hints:
            self.log(f"  💡 Search hints: {'; '.join(hints)}")


async def quick_classify_url(url: str) -> Tuple[str, str]:
    """
    Quick classification based on URL only (no download).
    Returns (document_type, confidence).
    """
    url_lower = url.lower()
    filename = url.split('/')[-1].lower()

    # Floorplan
    if any(kw in url_lower for kw in ['floor', 'plan', 'map', 'hall', 'layout', 'plattegrond',
                                       'show-layout', 'show_layout', '/maps', 'site-plan', 'venue-map']):
        return ('floorplan', 'weak')

    # Exhibitor manual
    if any(kw in url_lower for kw in ['exhibitor', 'manual', 'welcome', 'pack', 'handbook', 'guide']):
        return ('exhibitor_manual', 'weak')

    # Rules
    if any(kw in url_lower for kw in ['technical', 'regulation', 'rule', 'guideline', 'normativ']):
        return ('rules', 'weak')

    # Schedule
    if any(kw in url_lower for kw in ['schedule', 'timing', 'build', 'move-in', 'opbouw']):
        return ('schedule', 'weak')

    return ('unknown', 'none')
