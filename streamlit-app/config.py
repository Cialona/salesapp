"""
Cialona Trade Fair Discovery - Configuration & Branding
"""

# Brand Colors
CIALONA_ORANGE = "#F7931E"
CIALONA_NAVY = "#1E2A5E"
CIALONA_LIGHT_ORANGE = "#FFF4E6"
CIALONA_LIGHT_NAVY = "#E8EAF0"
CIALONA_WHITE = "#FFFFFF"
CIALONA_GRAY = "#6B7280"

# Status Colors
STATUS_COMPLETE = "#10B981"  # Green
STATUS_PARTIAL = "#F59E0B"   # Amber
STATUS_MISSING = "#EF4444"   # Red
STATUS_PENDING = "#6B7280"   # Gray

# App Configuration
APP_TITLE = "Trade Fair Discovery"
APP_ICON = "🎪"
COMPANY_NAME = "Cialona"
TAGLINE = "Eye for Attention"

# Document Types
DOCUMENT_TYPES = {
    "floorplan": {
        "name": "Floor Plan",
        "icon": "🗺️",
        "description": "Plattegrond van de beurshallen",
        "dutch_name": "Plattegrond"
    },
    "exhibitor_manual": {
        "name": "Exhibitor Manual",
        "icon": "📋",
        "description": "Handleiding voor exposanten",
        "dutch_name": "Exposanten Handleiding"
    },
    "rules": {
        "name": "Technical Guidelines",
        "icon": "📐",
        "description": "Technische voorschriften standbouw",
        "dutch_name": "Technische Richtlijnen"
    },
    "schedule": {
        "name": "Build-up Schedule",
        "icon": "📅",
        "description": "Opbouw en afbouw tijden",
        "dutch_name": "Opbouw Schema"
    },
    "exhibitor_directory": {
        "name": "Exhibitor Directory",
        "icon": "📇",
        "description": "Lijst van exposanten",
        "dutch_name": "Exposanten Lijst"
    }
}

# Custom CSS for Cialona branding
CUSTOM_CSS = f"""
<style>
    /* Import Google Font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* Global Styles */
    .stApp {{
        font-family: 'Inter', sans-serif;
    }}

    /* Header Styling */
    .main-header {{
        background: linear-gradient(135deg, {CIALONA_NAVY} 0%, #2D3A6E 100%);
        padding: 2rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        color: white;
    }}

    .main-header h1 {{
        color: white;
        margin: 0;
        font-weight: 600;
    }}

    .main-header .tagline {{
        color: {CIALONA_ORANGE};
        font-size: 1.1rem;
        margin-top: 0.5rem;
    }}

    /* Card Styles */
    .fair-card {{
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        border: 1px solid #E5E7EB;
        margin-bottom: 1rem;
        transition: transform 0.2s, box-shadow 0.2s;
    }}

    .fair-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.12);
    }}

    .fair-card-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1rem;
    }}

    .fair-card-title {{
        font-size: 1.25rem;
        font-weight: 600;
        color: {CIALONA_NAVY};
        margin: 0;
    }}

    /* Status Badges */
    .status-badge {{
        display: inline-flex;
        align-items: center;
        padding: 0.25rem 0.75rem;
        border-radius: 9999px;
        font-size: 0.875rem;
        font-weight: 500;
    }}

    .status-complete {{
        background: #D1FAE5;
        color: #065F46;
    }}

    .status-partial {{
        background: #FEF3C7;
        color: #92400E;
    }}

    .status-missing {{
        background: #FEE2E2;
        color: #991B1B;
    }}

    /* Document Chips */
    .doc-chip {{
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 1rem;
        border-radius: 8px;
        font-size: 0.875rem;
        margin: 0.25rem;
    }}

    .doc-found {{
        background: #D1FAE5;
        color: #065F46;
        border: 1px solid #A7F3D0;
    }}

    .doc-missing {{
        background: #FEE2E2;
        color: #991B1B;
        border: 1px solid #FECACA;
    }}

    /* Metric Cards */
    .metric-card {{
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        text-align: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        border: 1px solid #E5E7EB;
    }}

    .metric-value {{
        font-size: 2.5rem;
        font-weight: 700;
        color: {CIALONA_NAVY};
    }}

    .metric-label {{
        font-size: 0.875rem;
        color: {CIALONA_GRAY};
        margin-top: 0.5rem;
    }}

    /* Button Styles */
    .stButton > button {{
        background: linear-gradient(135deg, {CIALONA_ORANGE} 0%, #E8850F 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.5rem 1.5rem;
        font-weight: 500;
        transition: transform 0.2s, box-shadow 0.2s;
    }}

    .stButton > button:hover {{
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(247, 147, 30, 0.4);
    }}

    /* Secondary Button */
    .secondary-btn > button {{
        background: white;
        color: {CIALONA_NAVY};
        border: 2px solid {CIALONA_NAVY};
    }}

    .secondary-btn > button:hover {{
        background: {CIALONA_LIGHT_NAVY};
    }}

    /* Sidebar Styling */
    [data-testid="stSidebar"] {{
        background: {CIALONA_NAVY};
    }}

    [data-testid="stSidebar"] .stMarkdown {{
        color: white;
    }}

    [data-testid="stSidebar"] .stMarkdown p {{
        color: white !important;
    }}

    [data-testid="stSidebar"] .stMarkdown h1,
    [data-testid="stSidebar"] .stMarkdown h2,
    [data-testid="stSidebar"] .stMarkdown h3 {{
        color: white !important;
    }}

    [data-testid="stSidebar"] .stSelectbox label {{
        color: white !important;
    }}

    [data-testid="stSidebar"] .stTextInput label {{
        color: white !important;
    }}

    [data-testid="stSidebar"] span {{
        color: white !important;
    }}

    /* Sidebar page links */
    [data-testid="stSidebar"] a {{
        color: white !important;
    }}

    [data-testid="stSidebar"] .stPageLink {{
        color: white !important;
    }}

    /* Make the sidebar navigation items visible */
    [data-testid="stSidebarNav"] {{
        background: transparent;
    }}

    [data-testid="stSidebarNav"] span {{
        color: white !important;
    }}

    [data-testid="stSidebarNav"] a {{
        color: white !important;
    }}

    /* Sidebar navigation list items */
    [data-testid="stSidebarNavItems"] li {{
        color: white !important;
    }}

    [data-testid="stSidebarNavItems"] li span {{
        color: white !important;
    }}

    /* Active page in sidebar */
    [data-testid="stSidebarNavLink"] {{
        color: white !important;
    }}

    [data-testid="stSidebarNavLink"][aria-selected="true"] {{
        background-color: rgba(247, 147, 30, 0.3) !important;
    }}

    [data-testid="stSidebarNavLink"]:hover {{
        background-color: rgba(255, 255, 255, 0.1) !important;
    }}

    /* Progress Bar */
    .progress-bar {{
        height: 8px;
        background: #E5E7EB;
        border-radius: 4px;
        overflow: hidden;
    }}

    .progress-fill {{
        height: 100%;
        background: linear-gradient(90deg, {CIALONA_ORANGE} 0%, #E8850F 100%);
        border-radius: 4px;
        transition: width 0.3s ease;
    }}

    /* Table Styling */
    .dataframe {{
        border-radius: 8px;
        overflow: hidden;
    }}

    .dataframe th {{
        background: {CIALONA_NAVY};
        color: white;
        padding: 1rem;
    }}

    .dataframe td {{
        padding: 0.75rem 1rem;
    }}

    /* Hide Streamlit branding */
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}

    /* Custom scrollbar */
    ::-webkit-scrollbar {{
        width: 8px;
        height: 8px;
    }}

    ::-webkit-scrollbar-track {{
        background: #F1F1F1;
    }}

    ::-webkit-scrollbar-thumb {{
        background: {CIALONA_NAVY};
        border-radius: 4px;
    }}

    ::-webkit-scrollbar-thumb:hover {{
        background: #2D3A6E;
    }}
</style>
"""

def get_status_html(found: int, total: int) -> str:
    """Generate status badge HTML based on completion."""
    if found == total:
        return f'<span class="status-badge status-complete">✓ Compleet ({found}/{total})</span>'
    elif found > 0:
        return f'<span class="status-badge status-partial">⚠ Deels ({found}/{total})</span>'
    else:
        return f'<span class="status-badge status-missing">✗ Ontbreekt ({found}/{total})</span>'

def get_doc_chip_html(doc_type: str, found: bool) -> str:
    """Generate document chip HTML."""
    doc_info = DOCUMENT_TYPES.get(doc_type, {"icon": "📄", "dutch_name": doc_type})
    if found:
        return f'<span class="doc-chip doc-found">{doc_info["icon"]} {doc_info["dutch_name"]}</span>'
    else:
        return f'<span class="doc-chip doc-missing">{doc_info["icon"]} {doc_info["dutch_name"]}</span>'
