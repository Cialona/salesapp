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

        type_search_hints = {
            'floorplan': [
                'Check /maps of /floorplan pagina',
                'Zoek naar "Hall plan", "Site map", "Venue map"',
                'Soms te vinden op interactieve kaart pagina',
            ],
            'exhibitor_manual': [
                'Zoek naar "Exhibitor Manual", "Welcome Pack", "Exhibitor Guide", "Event Manual"',
                'Check externe portals (Salesforce/my.site.com, OEM)',
                'Vaak achter "Downloads" of "Exhibitor Resources" sectie',
                'Probeer web search: "[beursnaam] exhibitor welcome pack PDF"',
            ],
            'rules': [
                'Zoek naar "Technical Guidelines", "Stand Construction Rules", "Technical Regulations"',
                'NIET zoeken naar venue-specifieke regels (bijv. Fira Barcelona algemene regels)',
                'Check of het exhibitor manual/welcome pack ook technische regels bevat',
                'Vaak te vinden als aparte PDF op de download pagina',
            ],
            'schedule': [
                'Check of het exhibitor manual ook opbouw/afbouw schema bevat',
                'Zoek naar "Build-up schedule", "Move-in dates", "Set-up and dismantling"',
                'Soms te vinden op de "Practical Information" of "Planning" pagina',
                'Kijk naar de agenda/programma pagina voor beursdatums',
            ],
            'exhibitor_directory': [
                'Zoek naar /exhibitors, /catalogue, exhibitor lijst',
                'Soms op een apart subdomein: exhibitors.[domain]',
            ],
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

        # First pass: Quick classification based on URL and filename
        candidates = {
            'floorplan': [],
            'exhibitor_manual': [],
            'rules': [],
            'schedule': [],
        }

        for pdf in pdf_links:
            url = pdf.get('url', '') if isinstance(pdf, dict) else pdf
            text = pdf.get('text', '') if isinstance(pdf, dict) else ''
            pdf_type = pdf.get('type', 'unknown') if isinstance(pdf, dict) else 'unknown'
            pdf_year = pdf.get('year') if isinstance(pdf, dict) else None

            # Quick URL-based classification
            url_lower = url.lower()
            text_lower = text.lower()
            combined = f"{url_lower} {text_lower}"

            # Floorplan indicators
            if any(kw in combined for kw in ['floor', 'plan', 'map', 'hall', 'plattegrond', 'layout', 'venue']):
                candidates['floorplan'].append(pdf)

            # Exhibitor manual indicators
            if any(kw in combined for kw in ['exhibitor', 'manual', 'welcome', 'pack', 'handbook', 'guide', 'exposant']):
                candidates['exhibitor_manual'].append(pdf)

            # Rules/regulations indicators
            if any(kw in combined for kw in ['technical', 'regulation', 'rule', 'guideline', 'normativ', 'richtlijn', 'provision']):
                candidates['rules'].append(pdf)

            # Schedule indicators
            if any(kw in combined for kw in ['schedule', 'timing', 'build-up', 'buildup', 'tear-down', 'teardown', 'opbouw', 'afbouw', 'move-in', 'move-out']):
                candidates['schedule'].append(pdf)

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
                    url, doc_type, fair_name, fair_keywords, target_year
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
                portal_pages, result, fair_name, fair_keywords, target_year
            )

        # CROSS-REFERENCE PHASE: Use already-validated docs to fill gaps
        # If an exhibitor manual also contains rules/schedule, use it for those types too
        self.log("🔄 Cross-referencing validated documents...")
        for doc_type in ['exhibitor_manual', 'rules', 'schedule', 'floorplan']:
            classification = getattr(result, doc_type)
            if not classification or not classification.also_contains:
                continue

            for also_type in classification.also_contains:
                if also_type in candidates and not getattr(result, also_type, None):
                    # This document also contains info for another missing type
                    # Create a cross-referenced classification
                    cross_ref = DocumentClassification(
                        url=classification.url,
                        document_type=also_type,
                        confidence=classification.confidence,
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
                    self.log(f"  🔄 Cross-ref: {doc_type} document bevat ook {also_type} info → {classification.url[:60]}...")

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
        if exhibitor_pages:
            for page in exhibitor_pages:
                page_lower = page.lower()
                if any(kw in page_lower for kw in ['exhibitor', 'directory', 'list', 'companies', 'exposant']):
                    result.exhibitor_directory = page
                    self.log(f"  ✓ exhibitor_directory: {page[:60]}...")
                    break

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

    async def _classify_portal_pages(
        self,
        portal_pages: List[Dict],
        result: 'ClassificationResult',
        fair_name: str,
        fair_keywords: List[str],
        target_year: str,
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
            if page.get('is_pdf') or not text_content or len(text_content) < 100:
                continue

            detected_type = page.get('detected_type', 'unknown')
            mapped_type = type_mapping.get(detected_type)

            # If type is unknown, try to detect from content
            if not mapped_type:
                mapped_type = self._detect_content_type(page_url, text_content)

            if not mapped_type:
                continue

            # Skip if we already have a strong classification for this type
            existing = getattr(result, mapped_type, None)
            if existing and existing.confidence == 'strong':
                continue

            # Validate the page content with LLM (same as PDF but no download needed)
            classification = await self._validate_page_content(
                page_url, text_content, mapped_type,
                fair_name, fair_keywords, target_year,
                page_title=page.get('page_title', '')
            )

            if classification.confidence == 'strong':
                setattr(result, mapped_type, classification)
                self.log(f"  ✓ Portal page [{mapped_type}]: STRONG ✓year={classification.year_verified} ✓fair={classification.fair_verified}")
                self.log(f"    URL: {page_url[:70]}...")
            elif classification.confidence == 'partial' and not getattr(result, mapped_type):
                setattr(result, mapped_type, classification)
                self.log(f"  ~ Portal page [{mapped_type}]: partial")

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

    def _detect_content_type(self, url: str, text: str) -> Optional[str]:
        """Detect document type from page URL and content."""
        combined = f"{url} {text[:500]}".lower()

        if any(kw in combined for kw in [
            'stand build rule', 'construction rule', 'technical guideline',
            'technical regulation', 'height limit', 'fire safety',
            'electrical requirement', 'stand design rule',
        ]):
            return 'rules'

        if any(kw in combined for kw in [
            'build-up schedule', 'dismantling schedule', 'tear-down',
            'move-in schedule', 'set-up and dismantl', 'build up & dismantl',
        ]):
            return 'schedule'

        if any(kw in combined for kw in [
            'floor plan', 'floorplan', 'hall plan', 'venue map',
        ]):
            return 'floorplan'

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
                url
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

    async def _validate_pdf_strict(
        self,
        url: str,
        expected_type: str,
        fair_name: str,
        fair_keywords: List[str],
        target_year: str
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
                url
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
        url: str
    ) -> Dict:
        """
        Use Haiku to validate document AND extract additional info.

        Returns validation results plus:
        - Schedule dates/times if found
        - Contact emails/phones if found
        - Organization name if found
        """
        type_descriptions = {
            'floorplan': 'een plattegrond/floorplan met hal-indelingen, standnummers, of venue layout',
            'exhibitor_manual': 'een exposanten handleiding/manual met informatie over standbouw, regels voor exposanten, of een "welcome pack"',
            'rules': 'technische richtlijnen/regulations met constructie-eisen, elektra specificaties, of veiligheidsvoorschriften',
            'schedule': 'een opbouw/afbouw schema met specifieke datums en tijden voor move-in/move-out',
        }

        expected_desc = type_descriptions.get(expected_type, expected_type)

        prompt = f"""Analyseer dit document GRONDIG en extraheer ALLE informatie.

DOCUMENT URL: {url}
GEZOCHTE BEURS: {fair_name}
GEZOCHT JAAR: {target_year}
VERWACHT TYPE: {expected_type} - {expected_desc}

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
- "is_correct_fair" = true als document {fair_name} of de beurs-organisator noemt
- "is_correct_year" = true als document {target_year} bevat
- "is_useful" = true als document nuttige info bevat voor standbouwers

EXTRACTIE (HEEL BELANGRIJK - zoek naar ALLES):
- Zoek naar opbouw/afbouw datums en tijden (ook als dit niet het verwachte type is!)
- Zoek naar contact emails en telefoonnummers
- Zoek naar de naam van de organiserende partij
- Zoek naar VERWIJZINGEN naar andere documenten (URLs, documentnamen, "zie document X")
- Bevat dit document OOK info van een ander type? Bijv. een exhibitor manual/welcome pack kan ook technische regels of een opbouwschema bevatten - dit is HEEL BELANGRIJK om te detecteren!

Antwoord ALLEEN met valide JSON."""

        try:
            response = self.client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )

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

        # Collect all schedules
        all_build_up = []
        all_tear_down = []
        all_emails = []
        all_phones = []
        organization = None

        for doc_type in ['exhibitor_manual', 'rules', 'schedule', 'floorplan']:
            classification = getattr(result, doc_type)
            if not classification:
                continue

            # Aggregate schedules
            if classification.extracted_schedule:
                all_build_up.extend(classification.extracted_schedule.build_up)
                all_tear_down.extend(classification.extracted_schedule.tear_down)

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
    if any(kw in url_lower for kw in ['floor', 'plan', 'map', 'hall', 'layout', 'plattegrond']):
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
