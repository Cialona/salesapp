"""
Document Classifier Module

Uses a fast LLM (Haiku) to classify and validate PDFs found during prescan.
This allows us to skip the expensive browser agent when documents are already found.
"""

import re
import io
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

    def get_missing_prompt_section(self) -> str:
        """Generate prompt section describing what's missing."""
        if not self.missing_types:
            return ""

        type_descriptions = {
            'floorplan': 'Plattegrond/floorplan van de beurshallen',
            'exhibitor_manual': 'Exposanten handleiding/manual met standbouw regels',
            'rules': 'Technische richtlijnen/regulations voor standbouw',
            'schedule': 'Opbouw/afbouw schema met datums en tijden',
        }

        lines = ["NOG TE VINDEN (focus hierop):"]
        for doc_type in self.missing_types:
            desc = type_descriptions.get(doc_type, doc_type)
            lines.append(f"  ✗ {doc_type}: {desc}")

        return "\n".join(lines)

    def get_found_prompt_section(self) -> str:
        """Generate prompt section describing what's already found."""
        if not self.found_types:
            return ""

        lines = ["REEDS GEVONDEN (niet meer zoeken):"]

        if self.floorplan and self.floorplan.confidence in ['strong', 'partial']:
            lines.append(f"  ✓ floorplan: {self.floorplan.url}")
        if self.exhibitor_manual and self.exhibitor_manual.confidence in ['strong', 'partial']:
            lines.append(f"  ✓ exhibitor_manual: {self.exhibitor_manual.url}")
        if self.rules and self.rules.confidence in ['strong', 'partial']:
            lines.append(f"  ✓ rules: {self.rules.url}")
        if self.schedule and self.schedule.confidence in ['strong', 'partial']:
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
        exhibitor_pages: List[str] = None
    ) -> ClassificationResult:
        """
        Classify all found PDFs and determine what's found vs missing.

        Args:
            pdf_links: List of PDF dicts with 'url', 'text', 'type', 'year'
            fair_name: Name of the fair (e.g., "MWC Barcelona")
            target_year: Year we're looking for (default 2026)
            exhibitor_pages: List of exhibitor page URLs for directory detection

        Returns:
            ClassificationResult with found/missing document types
        """
        result = ClassificationResult()

        self.log(f"📋 Classifying {len(pdf_links)} documents for {fair_name}...")

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
            if any(kw in combined for kw in ['floor', 'plan', 'map', 'hall', 'plattegrond', 'layout']):
                candidates['floorplan'].append(pdf)

            # Exhibitor manual indicators
            if any(kw in combined for kw in ['exhibitor', 'manual', 'welcome', 'pack', 'handbook', 'guide', 'exposant']):
                candidates['exhibitor_manual'].append(pdf)

            # Rules/regulations indicators
            if any(kw in combined for kw in ['technical', 'regulation', 'rule', 'guideline', 'normativ', 'richtlijn', 'regulation']):
                candidates['rules'].append(pdf)

            # Schedule indicators
            if any(kw in combined for kw in ['schedule', 'timing', 'build-up', 'buildup', 'tear-down', 'teardown', 'opbouw', 'afbouw', 'move-in', 'move-out']):
                candidates['schedule'].append(pdf)

        # Second pass: Validate best candidates with LLM
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

            # Validate top candidate(s)
            for pdf in sorted_pdfs[:2]:  # Check top 2
                url = pdf.get('url', '') if isinstance(pdf, dict) else pdf
                classification = await self._validate_pdf(url, doc_type, fair_name, target_year)

                if classification.confidence in ['strong', 'partial']:
                    setattr(result, doc_type, classification)
                    self.log(f"  ✓ {doc_type}: {classification.confidence} - {url[:60]}...")
                    break

            if not getattr(result, doc_type):
                self.log(f"  ✗ {doc_type}: geen valide document gevonden")

        # Check for exhibitor directory (URL-based, no PDF validation)
        if exhibitor_pages:
            for page in exhibitor_pages:
                page_lower = page.lower()
                if any(kw in page_lower for kw in ['exhibitor', 'directory', 'list', 'companies', 'exposant']):
                    result.exhibitor_directory = page
                    self.log(f"  ✓ exhibitor_directory: {page[:60]}...")
                    break

        # Calculate summary
        all_types = ['floorplan', 'exhibitor_manual', 'rules', 'schedule']
        for doc_type in all_types:
            classification = getattr(result, doc_type)
            if classification and classification.confidence in ['strong', 'partial']:
                result.found_types.append(doc_type)
            else:
                result.missing_types.append(doc_type)

        # Add exhibitor_directory to found if present
        if result.exhibitor_directory:
            result.found_types.append('exhibitor_directory')
        else:
            result.missing_types.append('exhibitor_directory')

        result.all_found = len(result.missing_types) == 0

        self.log(f"📊 Classificatie compleet: {len(result.found_types)}/5 gevonden, {len(result.missing_types)} missend")

        return result

    async def _validate_pdf(
        self,
        url: str,
        expected_type: str,
        fair_name: str,
        target_year: str
    ) -> DocumentClassification:
        """
        Validate a single PDF by downloading and analyzing it.

        Uses LLM to verify:
        1. Is this the right type of document?
        2. Is this for the right fair?
        3. Is this for the right year?
        4. Does it contain useful information?
        """
        classification = DocumentClassification(
            url=url,
            document_type=expected_type,
            confidence='none'
        )

        try:
            # Download PDF (first 200KB for efficiency)
            text_content = await self._extract_pdf_text(url, max_bytes=200_000)

            if not text_content or len(text_content) < 50:
                classification.reason = "Kon geen tekst uit PDF extraheren"
                return classification

            classification.text_excerpt = text_content[:500]

            # Use LLM to validate
            validation_result = await self._llm_validate(
                text_content[:8000],  # Limit to ~8k chars for Haiku
                expected_type,
                fair_name,
                target_year,
                url
            )

            classification.confidence = validation_result.get('confidence', 'none')
            classification.year = validation_result.get('year')
            classification.title = validation_result.get('title')
            classification.reason = validation_result.get('reason', '')
            classification.is_validated = True

        except Exception as e:
            classification.reason = f"Fout bij validatie: {str(e)}"

        return classification

    async def _extract_pdf_text(self, url: str, max_bytes: int = 200_000) -> str:
        """Extract text from PDF URL."""

        if not PDF_SUPPORT:
            # Fallback: just analyze URL/filename
            return f"[PDF URL: {url}]"

        try:
            # Download PDF (partial)
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Range': f'bytes=0-{max_bytes}'  # Only first part
                }
            )

            with urllib.request.urlopen(req, timeout=15) as response:
                pdf_bytes = response.read()

            # Try to extract text
            pdf_file = io.BytesIO(pdf_bytes)

            try:
                reader = pypdf.PdfReader(pdf_file)
                text_parts = []

                # Extract from first few pages
                for i, page in enumerate(reader.pages[:5]):
                    try:
                        text = page.extract_text()
                        if text:
                            text_parts.append(text)
                    except:
                        continue

                return "\n".join(text_parts)

            except Exception as e:
                # PDF might be truncated, try with what we have
                return f"[Partial PDF from: {url}]"

        except urllib.error.HTTPError as e:
            if e.code == 416:  # Range not satisfiable - download full
                try:
                    req = urllib.request.Request(url, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    with urllib.request.urlopen(req, timeout=15) as response:
                        pdf_bytes = response.read()

                    pdf_file = io.BytesIO(pdf_bytes)
                    reader = pypdf.PdfReader(pdf_file)
                    text_parts = []
                    for page in reader.pages[:5]:
                        try:
                            text = page.extract_text()
                            if text:
                                text_parts.append(text)
                        except:
                            continue
                    return "\n".join(text_parts)
                except:
                    pass
            return ""
        except Exception as e:
            return ""

    async def _llm_validate(
        self,
        text_content: str,
        expected_type: str,
        fair_name: str,
        target_year: str,
        url: str
    ) -> Dict:
        """Use Haiku to validate document content."""

        type_descriptions = {
            'floorplan': 'een plattegrond/floorplan met hal-indelingen, standnummers, of venue layout',
            'exhibitor_manual': 'een exposanten handleiding/manual met informatie over standbouw, regels voor exposanten, of een "welcome pack"',
            'rules': 'technische richtlijnen/regulations met constructie-eisen, elektra specificaties, of veiligheidsvoorschriften',
            'schedule': 'een opbouw/afbouw schema met specifieke datums en tijden voor move-in/move-out',
        }

        expected_desc = type_descriptions.get(expected_type, expected_type)

        prompt = f"""Analyseer dit document en bepaal of het geschikt is.

DOCUMENT URL: {url}
GEZOCHTE BEURS: {fair_name}
GEZOCHT JAAR: {target_year}
VERWACHT TYPE: {expected_type} - {expected_desc}

DOCUMENT TEKST (eerste deel):
---
{text_content}
---

Beantwoord in JSON formaat:
{{
  "is_correct_type": true/false,  // Is dit echt {expected_type}?
  "is_correct_fair": true/false,  // Is dit voor {fair_name} (of de venue/organisator)?
  "detected_year": "2024/2025/2026/unknown",  // Welk jaar staat in het document?
  "is_useful": true/false,  // Bevat het nuttige informatie voor standbouwers?
  "confidence": "strong/partial/weak/none",
  "title": "document titel indien gevonden",
  "reason": "korte uitleg van je beoordeling"
}}

BELANGRIJK:
- "strong" = juiste type, juiste beurs, juist jaar, nuttige info
- "partial" = juiste type, maar verkeerd jaar OF algemene venue info (nog steeds bruikbaar)
- "weak" = mogelijk relevant maar niet zeker
- "none" = niet wat we zoeken

Antwoord ALLEEN met de JSON, geen andere tekst."""

        try:
            # Use Haiku for speed and cost efficiency
            response = self.client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text.strip()

            # Parse JSON from response
            # Handle potential markdown code blocks
            if "```" in response_text:
                json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(1)

            import json
            result = json.loads(response_text)

            return {
                'confidence': result.get('confidence', 'none'),
                'year': result.get('detected_year'),
                'title': result.get('title'),
                'reason': result.get('reason', ''),
            }

        except Exception as e:
            # Fallback: basic URL-based confidence
            url_lower = url.lower()
            if target_year in url_lower or target_year[2:] in url_lower:
                return {'confidence': 'partial', 'year': target_year, 'reason': 'Jaar in URL gevonden'}
            return {'confidence': 'weak', 'reason': f'LLM validatie gefaald: {str(e)}'}


async def quick_classify_url(url: str) -> Tuple[str, str]:
    """
    Quick classification based on URL only (no download).
    Returns (document_type, confidence).
    """
    url_lower = url.lower()
    filename = url.split('/')[-1].lower()

    # Floorplan
    if any(kw in url_lower for kw in ['floor', 'plan', 'map', 'hall', 'layout', 'plattegrond']):
        return ('floorplan', 'partial')

    # Exhibitor manual
    if any(kw in url_lower for kw in ['exhibitor', 'manual', 'welcome', 'pack', 'handbook', 'guide']):
        return ('exhibitor_manual', 'partial')

    # Rules
    if any(kw in url_lower for kw in ['technical', 'regulation', 'rule', 'guideline', 'normativ']):
        return ('rules', 'partial')

    # Schedule
    if any(kw in url_lower for kw in ['schedule', 'timing', 'build', 'move-in', 'opbouw']):
        return ('schedule', 'partial')

    return ('unknown', 'none')
