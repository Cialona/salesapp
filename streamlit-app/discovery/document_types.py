"""
Central Document Type Registry — Single Source of Truth

ALL keyword lists, LLM prompts, and detection logic reference this module.
Adding a new synonym or document type = ONE change here, everywhere updated.

Architecture:
- DOCUMENT_TYPES: semantic descriptions + URL patterns + keywords per type
- get_scan_frontier_paths(): generates generic_paths from URL patterns
- get_llm_classification_prompt(): generates LLM prompts from semantic descriptions
- get_all_keywords(): returns flat keyword list for fast-path matching
"""

from typing import Dict, List, Set

# =============================================================================
# CENTRAL DOCUMENT TYPE DEFINITIONS
# =============================================================================
# Each type has:
#   - description: what this document IS (for humans)
#   - llm_description: semantic description for LLM classification
#   - url_patterns: URL path segments that indicate this type
#   - keywords: text/link keywords for fast-path matching
#   - title_keywords: keywords in page titles (higher specificity)
#   - content_keywords: keywords in page content (multi-language)
#   - exclusions: keywords that EXCLUDE this type (false positives)
# =============================================================================

DOCUMENT_TYPES: Dict[str, dict] = {
    'floorplan': {
        'description': 'Plattegrond/floorplan van de beurshallen',
        'llm_description': (
            'Visual layout of the exhibition halls showing stand/booth positions, '
            'hall numbers, entrances, and exits. Can be interactive maps, PDFs, '
            'or web pages. Also known as: show layout, venue map, site plan, '
            'maps page, hall plan, Geländeplan, Hallenplan, plattegrond.'
        ),
        'url_patterns': [
            '/floorplan', '/floor-plan', '/maps', '/map',
            '/show-layout', '/hall-plan', '/venue-map', '/site-plan',
            '/hall-and-site-plan', '/site-map',
        ],
        'title_keywords': [
            # English
            'floorplan', 'floor-plan', 'floor plan', 'expo-floorplan',
            'hall-plan', 'hall plan', 'hall & site plan', 'hall and site plan',
            'show-layout', 'show layout', 'show_layout',
            'venue-map', 'venue map', 'site-map', 'site map',
            'site-plan', 'site plan', '/maps',
            # Known providers
            'expocad', 'expofp', 'mapyourshow',
            # German
            'hallenplan', 'geländeplan', 'gelaendeplan',
            # Dutch
            'plattegrond',
            # Italian
            'planimetria',
        ],
        'content_keywords': [
            # English
            'floor plan', 'floorplan', 'hall plan', 'site map', 'venue map',
            'exhibition layout', 'expo floorplan', 'show layout',
            'hall & site plan', 'hall and site plan', 'site plan',
            # Known providers
            'expocad', 'expofp', 'mapyourshow',
            # German
            'hallenplan', 'geländeplan', 'gelaendeplan',
            # Dutch
            'plattegrond',
            # French
            'plan du salon', 'plan des halls',
            # Spanish
            'plano de la feria', 'plano del recinto',
            # Italian
            'pianta del salone', 'planimetria',
        ],
        'pdf_keywords': [
            'floor', 'plan', 'hall', 'gelaende', 'site', 'map', 'layout',
            'show-layout', 'show layout', 'venue-map', 'site-plan',
        ],
        'pdf_exclusions': [
            'technical', 'data sheet', 'datasheet', 'evacuation', 'emergency',
            'safety', 'regulation', 'provision', 'guideline', 'specification',
            'spec', 'elettric', 'electric', 'water', 'gas', 'service',
        ],
        'download_keywords': [
            'gelände', 'gelande', 'floor', 'hall', 'site', 'hallen',
            'map', 'overview', 'show',
        ],
        'download_url_keywords': [
            'gelaende', 'floorplan', 'hallenplan', 'siteplan',
            'show-layout', 'show_layout',
        ],
        'known_providers': [
            'expocad.com', 'a2zinc.net', 'mapyourshow.com',
            'map-dynamics.', 'expofp.com',
        ],
        'scoring_keywords': [
            'floorplan', 'floor plan', 'expocad', 'hall plan',
            'expofp', 'mapyourshow', 'show layout',
            'venue map', 'site map', 'site plan', '/maps',
            'hall & site plan', 'hall and site plan',
            'hallenplan', 'plattegrond', 'geländeplan', 'planimetria',
        ],
        'search_hints': [
            'Check /maps, /floorplan, /show-layout, /hall-plan pagina',
            'Zoek naar "Hall plan", "Site map", "Venue map", "Show Layout", "Maps"',
            'Soms te vinden op interactieve kaart pagina of als "Hall & site plan"',
        ],
    },

    'exhibitor_manual': {
        'description': 'Exposanten handleiding/manual met standbouw regels',
        'llm_description': (
            'Exhibitor manual, handbook, or welcome pack containing general '
            'information for exhibitors: rules, setup procedures, logistics, '
            'deadlines. Also includes GENERAL/STANDARD terms and conditions '
            '(participation rules, Allgemeine Geschäftsbedingungen, '
            'algemene voorwaarden, conditions générales).'
        ),
        'url_patterns': [
            '/exhibitor-manual', '/exhibitor-handbook', '/exhibitor-guide',
            '/welcome-pack', '/event-manual', '/event-information',
            '/exhibitor-info', '/exhibitor-resources',
        ],
        'title_keywords': [
            # English
            'event-information', 'event information', 'event-guideline',
            'event guideline', 'exhibitor-manual', 'exhibitor manual',
            'exhibitor-handbook', 'exhibitor handbook', 'exhibitor-guide',
            'exhibitor guide', 'welcome-pack', 'event-manual',
            'exhibitor-info', 'exhibitor info',
            # General/Standard T&C → exhibitor_manual
            'standard-terms', 'standard terms', 'standard_terms',
            'general-terms', 'general terms', 'general_terms',
            'algemene-voorwaarden', 'algemene voorwaarden',
            'conditions-generales', 'conditions générales',
            'allgemeine-geschaeftsbedingung', 'allgemeine geschäftsbedingung',
            'condizioni-generali', 'condiciones-generales',
            'teilnahmebedingung', 'participation-conditions', 'participation conditions',
            # German
            'ausstellerhandbuch',
            # French
            'manuel-exposant', 'manuel exposant',
            # Spanish
            'manual-del-expositor',
        ],
        'content_keywords': [
            # English
            'exhibitor manual', 'exhibitor handbook', 'exhibitor guide',
            'welcome pack', 'event manual', 'event information',
            'exhibitor info', 'service documentation', 'exhibitor resource',
            # General/Standard T&C
            'standard terms', 'general terms', 'general conditions',
            'participation conditions',
            # German
            'ausstellerhandbuch', 'ausstellerinformation',
            'allgemeine geschäftsbedingung', 'teilnahmebedingung',
            # Dutch
            'handleiding exposant', 'exposanten handleiding',
            'algemene voorwaarden',
            # French
            'manuel exposant', 'guide exposant',
            'conditions générales',
            # Spanish
            'manual del expositor', 'guía del expositor',
            # Italian
            'manuale espositore', 'guida espositore',
        ],
        'pdf_keywords': [
            'exhibitor', 'manual', 'welcome', 'handbook', 'guide',
            'aussteller', 'btb', 'provision', 'stand', 'design',
            'fitting', 'allestimento', 'smm_', 'handbuch',
        ],
        'scoring_keywords_strong': [
            'event rules', 'exhibitor manual', 'welcome pack', 'event manual',
            'event information', 'event guideline',
        ],
        'scoring_keywords_medium': [
            'rules and regulation', 'handbook', 'exhibitor guide',
            'standard terms', 'general terms', 'general conditions',
            'participation conditions', 'participation rules',
            'algemene voorschriften', 'handleiding', 'algemene voorwaarden',
            'ausstellerhandbuch', 'allgemeine vorschriften',
            'allgemeine geschäftsbedingung', 'teilnahmebedingung',
            'manuel exposant', 'guide exposant',
            'conditions générales', 'conditions generales',
        ],
        'scoring_penalties': [
            'vehicle access', 'parking', 'catering', 'restaurant', 'accreditation',
        ],
        'search_hints': [
            'Zoek naar "Exhibitor Manual", "Welcome Pack", "Exhibitor Guide", "Event Manual"',
            'Check externe portals (Salesforce/my.site.com, OEM)',
            'Vaak achter "Downloads" of "Exhibitor Resources" sectie',
            'Probeer web search: "[beursnaam] exhibitor welcome pack PDF"',
        ],
    },

    'rules': {
        'description': 'Technische richtlijnen/regulations voor standbouw (BEURS-SPECIFIEK, niet van de venue!)',
        'llm_description': (
            'Technical regulations, construction rules, design guidelines '
            'SPECIFIC to this fair. Contains height limits, electrical specs, '
            'fire safety, stand construction requirements. Also includes '
            'SPECIFIC terms and conditions (fair-specific rules, not general '
            'participation conditions).'
        ),
        'url_patterns': [
            '/technical-regulations', '/technical-guidelines',
            '/design-regulations', '/stand-construction',
            '/construction-rules', '/stand-build-rules',
        ],
        'title_keywords': [
            # English — specific/technical rules
            'design-regulation', 'design regulation', 'technical-regulation',
            'technical regulation', 'technical-guideline', 'technical guideline',
            'stand-build-rule', 'stand build rule', 'construction-rule',
            # Specific terms & conditions
            'specific-terms', 'specific terms', 'specific_terms',
            'terms-and-condition', 'terms_and_condition', 'terms and condition',
            'voorschriften',
            # French
            'reglement-technique',
            # Italian
            'regolamento-tecnico',
            # Spanish
            'reglamento-tecnico',
            # Dutch
            'technische-richtlijn', 'standbouwregels',
        ],
        'content_keywords': [
            # English
            'stand build rule', 'construction rule', 'technical guideline',
            'technical regulation', 'stand design rule', 'design regulation',
            'design rule', 'height limit', 'technical specification',
            'fire safety', 'construction requirement',
            # German
            'technische richtlinie', 'standbauvorgabe', 'bauvorschrift',
            # French
            'reglement technique', 'règlement technique',
            # Spanish
            'reglamento tecnico', 'regulación técnica',
            # Italian
            'regolamento tecnico',
            # Dutch
            'technische richtlijn', 'standbouwregels',
        ],
        'pdf_keywords': [
            'technical', 'regulation', 'richtlin', 'regolamento',
            'reg.', 'reg_', 'tecnic',
        ],
        'scoring_keywords_strong': [
            'stand build rule', 'technical regulation', 'construction rule',
            'design regulation', 'booth construction',
            'specific terms', 'specific conditions',
            'standbouw', 'bouwvoorschriften', 'specifieke voorwaarden',
            'standbauvorschrift', 'technische vorschrift',
            'reglement technique',
        ],
        'scoring_keywords_medium': [
            'technical guideline', 'stand design', 'design rule',
            'technische richtlijn', 'technische richtlinie',
        ],
        'scoring_penalties': [
            'algemene voorwaarden', 'general terms', 'standard terms',
            'allgemeine geschäftsbedingung', 'conditions générales',
            'participation condition',
        ],
        'search_hints': [
            'Zoek naar "Technical Guidelines", "Stand Construction Rules", "Technical Regulations"',
            'NIET zoeken naar venue-specifieke regels (bijv. Fira Barcelona algemene regels)',
            'Check of het exhibitor manual/welcome pack ook technische regels bevat',
            'Vaak te vinden als aparte PDF op de download pagina',
        ],
    },

    'schedule': {
        'description': 'Opbouw/afbouw schema met datums en tijden',
        'llm_description': (
            'Build-up and tear-down (dismantling) schedule with SPECIFIC dates '
            'and times for move-in/move-out. Should contain actual calendar dates '
            '(DD-MM-YYYY) and time slots (HH:MM).'
        ),
        'url_patterns': [
            '/event-schedule', '/build-up-schedule',
            '/dismantling-schedule', '/setup-schedule',
            '/move-in', '/move-out', '/set-up-and-dismantling',
            '/opbouw-en-afbouw', '/op-en-afbouw', '/toegangsbeleid',
        ],
        'title_keywords': [
            'event-schedule', 'event schedule', 'build-up-schedule',
            'dismantling-schedule', 'tear-down-schedule', 'move-in-schedule',
            'setup-schedule', '/deadline', 'access-policy', 'timetable',
            'important-dates', 'important dates', 'key-dates', 'key dates',
            'move-in-move-out', 'move-in schedule',
            'aufbau-und-abbau', 'opbouw-en-afbouw', 'op-en-afbouw',
            'toegangsbeleid', 'opbouw', 'afbouw',
        ],
        'content_keywords': [
            # English
            'event schedule', 'build-up schedule', 'build up schedule',
            'dismantling schedule', 'tear-down schedule', 'move-in schedule',
            'set-up schedule', 'build-up & dismantl', 'installation & dismantl',
            'setup and dismantle', 'setup & dismantle',
            # German
            'aufbau und abbau', 'aufbauzeiten', 'abbauzeiten',
            # French
            'calendrier de montage', 'montage et démontage',
            # Spanish
            'calendario de montaje', 'montaje y desmontaje',
            # Italian
            'calendario allestimento', 'allestimento e smontaggio',
            # Dutch
            'opbouw en afbouw', 'opbouwschema',
        ],
        'pdf_keywords': [
            'schedule', 'timeline', 'aufbau', 'montaggio', 'calendar',
            'abbau', 'dismant', 'opbouw', 'afbouw',
        ],
        'scoring_keywords_strong': [
            'build up and dismantling schedule', 'build-up schedule', 'event schedule',
            'opbouw en afbouw', 'aufbau und abbau',
        ],
        'scoring_keywords_medium': [
            'schedule', 'timing', 'move-in', 'deadline',
            'opbouw', 'afbouw', 'aufbau', 'abbau',
        ],
        'search_hints': [
            'Check of het exhibitor manual ook opbouw/afbouw schema bevat',
            'Zoek naar "Build-up schedule", "Move-in dates", "Set-up and dismantling"',
            'Soms te vinden op de "Practical Information" of "Planning" pagina',
            'Kijk naar de agenda/programma pagina voor beursdatums',
        ],
    },

    'exhibitor_directory': {
        'description': 'Exposantenlijst met bedrijfsnamen',
        'llm_description': (
            'Exhibitor directory or list showing companies/brands exhibiting '
            'at the fair. Usually a searchable list with company names and '
            'optionally stand numbers.'
        ),
        'url_patterns': [
            '/exhibitors', '/exhibitor-list', '/exhibitor-directory',
            '/catalogue', '/catalog', '/companies',
        ],
        'title_keywords': [
            'exhibitor list', 'exhibitor directory', 'exhibitor search',
            'find exhibitor', 'exhibitors', 'list of exhibitors',
            'ausstellerliste', 'aussteller suchen',
            'company directory', 'exhibitor catalogue', 'exhibitor catalog',
        ],
        'scoring_keywords_strong': [
            'directory', 'catalogue', 'catalog', '/exhibitors',
            'exhibitor-list', 'exhibitor list', '/companies',
            '/espositori', '/aussteller',
        ],
        'scoring_keywords_medium': [
            '/list', 'exposant',
        ],
        'scoring_penalties': [
            'resource', 'service', 'download', 'manual', 'guide', 'technical',
            'checklist', 'register', 'login', 'dashboard', 'faq',
            'shipping', 'marketing', 'contact', 'order', 'profile',
        ],
        'search_hints': [
            'Zoek naar /exhibitors, /catalogue, exhibitor lijst',
            'Soms op een apart subdomein: exhibitors.[domain]',
        ],
    },
}


# =============================================================================
# DERIVED CONSTANTS — auto-generated from DOCUMENT_TYPES
# =============================================================================

def get_scan_frontier_paths() -> List[str]:
    """Generate URL paths to always try during pre-scan.
    Returns deduplicated list from all document types' url_patterns.
    """
    paths = []
    seen = set()
    for doc_type in DOCUMENT_TYPES.values():
        for path in doc_type.get('url_patterns', []):
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def get_doc_keywords() -> List[str]:
    """Generate flat keyword list for fast-path link matching.
    Used in prescan to decide if a link is worth following.
    """
    keywords = set()
    for doc_type in DOCUMENT_TYPES.values():
        # Use title_keywords (most specific) for link matching
        for kw in doc_type.get('title_keywords', []):
            # Only use multi-word or specific keywords to avoid false positives
            if len(kw) >= 5 or '-' in kw:
                keywords.add(kw)
    # Add some common base keywords
    keywords.update([
        'technical', 'regulation', 'provision', 'guideline', 'manual',
        'handbook', 'richtlin', 'regolamento', 'standbau', 'construction',
        'setup', 'dismant', 'aufbau', 'abbau', 'montaggio', 'allestimento',
        'floor', 'plan', 'hall', 'gelaende', 'exhibitor', 'aussteller',
        'show-layout', 'show layout', 'venue-map', 'site-map', 'site-plan',
        'standbouw', 'standhouder', 'opbouw', 'afbouw', 'toegang',
        'contractor', 'terms-and-condition', 'terms_and_condition',
    ])
    return sorted(keywords)


def get_page_keywords() -> List[str]:
    """Generate keywords for portal page scanning."""
    keywords = set()
    for doc_type in DOCUMENT_TYPES.values():
        for kw in doc_type.get('title_keywords', []):
            if len(kw) >= 4:
                keywords.add(kw)
        for kw in doc_type.get('content_keywords', []):
            if len(kw) >= 4:
                keywords.add(kw)
    return sorted(keywords)


def get_known_floorplan_providers() -> List[str]:
    """Get list of known floorplan provider domains."""
    return DOCUMENT_TYPES['floorplan'].get('known_providers', [])


def get_llm_classification_prompt(fair_name: str = '', context: str = 'links') -> str:
    """Generate LLM classification prompt from semantic descriptions.

    Args:
        fair_name: Name of the trade fair
        context: 'links' for link classification, 'pages' for page content,
                 'pdfs' for PDF classification
    """
    type_descriptions = []
    for type_name, type_def in DOCUMENT_TYPES.items():
        if type_name == 'exhibitor_directory' and context != 'pages':
            continue
        type_descriptions.append(
            f'- "{type_name}": {type_def["llm_description"]}'
        )

    types_str = '\n'.join(type_descriptions)

    if context == 'links':
        return f"""You are helping discover exhibitor documentation for the trade fair "{fair_name}".

Below is a list of internal website links (link text + URL). For each link, decide whether it
is likely to lead to a page containing information that a stand builder (contractor) would need.

DOCUMENT TYPES to look for:
{types_str}

Also include links to:
- Exhibitor services, logistics, sustainability guidelines
- Important deadlines for exhibitors
- Document downloads, forms, or resources for exhibitors

IMPORTANT: Think SEMANTICALLY, not just about keywords. A page called "Maps" IS a floorplan.
A page called "Show Layout" IS a floorplan. Use your understanding of what stand builders need.

This can be in ANY language (English, Dutch, German, French, Italian, Spanish, etc.).
Be GENEROUS — if a link MIGHT contain useful exhibitor info, include it.
Do NOT select: news articles, blog posts, visitor info, ticket sales, exhibitor directories/lists, company profiles."""

    elif context == 'pages':
        return f"""You are classifying web pages from the trade fair "{fair_name}" website.

For each page below, decide which type of exhibitor document it is based on its URL, title, and content.

Types:
{types_str}
- "not_relevant" = Not useful for stand builders (news, visitor info, company profiles, etc.)

IMPORTANT: Think SEMANTICALLY. Use the page content to understand what the document IS,
regardless of the specific terminology used. Different fairs use different terms for the same thing."""

    elif context == 'pdfs':
        return f"""Classificeer deze PDF documenten voor de beurs "{fair_name}".

Categorieën:
{types_str}
- "skip": niet relevant (bijv. privacy policy, cookie policy, sponsorship, marketing, visitor info)

BELANGRIJK: Denk SEMANTISCH. Gebruik je begrip van wat het document IS, niet alleen keywords.
Classificeer RUIM: bij twijfel, classificeer het document liever dan het te skippen."""

    return types_str


def get_type_search_hints(doc_type: str) -> List[str]:
    """Get search hints for a specific document type."""
    type_def = DOCUMENT_TYPES.get(doc_type, {})
    return type_def.get('search_hints', [])


def get_scoring_keywords(doc_type: str) -> dict:
    """Get scoring keywords for a document type.
    Returns {'strong': [...], 'medium': [...], 'penalties': [...]}.
    """
    type_def = DOCUMENT_TYPES.get(doc_type, {})
    return {
        'strong': type_def.get('scoring_keywords_strong', []),
        'medium': type_def.get('scoring_keywords_medium', []),
        'penalties': type_def.get('scoring_penalties', []),
    }


def get_title_keywords(doc_type: str) -> List[str]:
    """Get title/URL keywords for a document type."""
    return DOCUMENT_TYPES.get(doc_type, {}).get('title_keywords', [])


def get_content_keywords(doc_type: str) -> List[str]:
    """Get content keywords for a document type."""
    return DOCUMENT_TYPES.get(doc_type, {}).get('content_keywords', [])


def get_pdf_keywords(doc_type: str) -> List[str]:
    """Get PDF-specific keywords for a document type."""
    return DOCUMENT_TYPES.get(doc_type, {}).get('pdf_keywords', [])


def get_pdf_exclusions(doc_type: str) -> List[str]:
    """Get exclusion keywords for PDF classification."""
    return DOCUMENT_TYPES.get(doc_type, {}).get('pdf_exclusions', [])


def get_all_url_patterns() -> List[str]:
    """Get all URL patterns across all document types."""
    patterns = []
    for type_def in DOCUMENT_TYPES.values():
        patterns.extend(type_def.get('url_patterns', []))
    return patterns
