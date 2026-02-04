"""
Cialona Trade Fair Discovery - Discovery Page
Start new discoveries and import results.
"""

import streamlit as st
import json
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
import data_manager as dm
from config import CUSTOM_CSS, CIALONA_ORANGE, CIALONA_NAVY, APP_ICON

# Page configuration
st.set_page_config(
    page_title="Discovery | Cialona",
    page_icon=APP_ICON,
    layout="wide"
)

# Inject custom CSS
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown(f"""
    <div style="text-align: center; padding: 1rem;">
        <h2 style="color: {CIALONA_ORANGE}; margin: 0;">CIALONA</h2>
        <p style="color: white; font-size: 0.8rem; margin: 0;">Eye for Attention</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    if st.button("🏠 Dashboard", use_container_width=True):
        st.switch_page("app.py")

# Header
st.markdown(f"""
<div class="main-header">
    <h1>🔍 Nieuwe Discovery</h1>
    <p class="tagline">Vind automatisch exhibitor documenten voor een beurs</p>
</div>
""", unsafe_allow_html=True)

# Tabs for different input methods
tab1, tab2 = st.tabs(["📝 Handmatig Invoeren", "📥 JSON Importeren"])

with tab1:
    st.markdown("### Beurs Informatie")

    col1, col2 = st.columns(2)

    with col1:
        fair_name = st.text_input(
            "Beurs Naam *",
            placeholder="bijv. Ambiente, bauma, ISPO Munich"
        )
        fair_url = st.text_input(
            "Website URL",
            placeholder="https://ambiente.messefrankfurt.com"
        )

    with col2:
        fair_city = st.text_input(
            "Stad",
            placeholder="bijv. Frankfurt, München"
        )
        fair_country = st.text_input(
            "Land",
            placeholder="bijv. Germany, Netherlands"
        )

    st.markdown("---")

    st.markdown("### Discovery Starten")

    st.info("""
    **Hoe werkt het?**
    1. Voer de beursnaam en eventueel de URL in
    2. Klik op 'Start Discovery'
    3. De AI agent navigeert automatisch door de website
    4. Resultaten worden opgeslagen in het dashboard

    **Geschatte kosten:** ~$1.90 per beurs
    **Geschatte tijd:** 2-3 minuten
    """)

    # Discovery options
    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        max_iterations = st.slider("Max Iteraties", 10, 50, 30)
    with col_opt2:
        use_github_actions = st.checkbox("Via GitHub Actions", value=True,
            help="Vink aan om discovery via GitHub Actions te runnen (aanbevolen)")

    if st.button("🚀 Start Discovery", type="primary", disabled=not fair_name):
        if use_github_actions:
            # Generate GitHub Actions workflow trigger info
            st.markdown("### 🔧 GitHub Actions")
            st.markdown("""
            Om de discovery te starten via GitHub Actions:

            1. Ga naar de [Test Single Fair](https://github.com/Cialona/salesapp/actions/workflows/test-single.yml) workflow
            2. Klik op "Run workflow"
            3. Selecteer de beurs of voer custom parameters in
            4. Wacht tot de workflow klaar is
            5. Download de JSON output en importeer hieronder
            """)

            # Show pre-filled workflow parameters
            st.code(f"""
fair_name: {fair_name}
fair_url: {fair_url or 'auto-detect'}
max_iterations: {max_iterations}
            """, language="yaml")

            st.warning("⚠️ Kopieer deze parameters naar de GitHub Actions workflow")
        else:
            # Direct discovery (requires local setup)
            st.warning("⚠️ Directe discovery vereist lokale setup met Playwright. Gebruik GitHub Actions voor de beste ervaring.")

            # Placeholder for future local integration
            st.info("Lokale discovery wordt binnenkort toegevoegd...")

with tab2:
    st.markdown("### JSON Resultaat Importeren")

    st.markdown("""
    Plak hier het JSON resultaat van een discovery (via GitHub Actions of CLI).
    """)

    json_input = st.text_area(
        "JSON Data",
        height=400,
        placeholder='{"fair_name": "Ambiente", "documents": {...}, ...}'
    )

    # File upload option
    uploaded_file = st.file_uploader("Of upload een JSON bestand", type=['json'])

    if uploaded_file is not None:
        json_input = uploaded_file.read().decode('utf-8')
        st.success(f"Bestand geladen: {uploaded_file.name}")

    if st.button("📥 Importeren", type="primary", disabled=not json_input):
        try:
            discovery_data = json.loads(json_input)

            # Validate required fields
            if 'fair_name' not in discovery_data:
                st.error("❌ JSON moet een 'fair_name' veld bevatten")
            else:
                # Import the discovery result
                fair_id = dm.import_discovery_result(discovery_data)

                st.success(f"✅ Beurs '{discovery_data['fair_name']}' succesvol geïmporteerd!")

                # Show summary
                fair = dm.get_fair(fair_id)
                if fair:
                    completeness = fair.get('completeness', {})
                    st.markdown(f"""
                    **Resultaat:**
                    - Documenten gevonden: {completeness.get('found', 0)}/{completeness.get('total', 5)}
                    - Status: {fair.get('status', 'unknown').title()}
                    """)

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("📄 Bekijk Details"):
                            st.session_state['selected_fair'] = fair_id
                            st.switch_page("pages/2_Fair_Details.py")
                    with col2:
                        if st.button("🏠 Naar Dashboard"):
                            st.switch_page("app.py")

        except json.JSONDecodeError as e:
            st.error(f"❌ Ongeldige JSON: {e}")
        except Exception as e:
            st.error(f"❌ Fout bij importeren: {e}")

# Recent imports section
st.markdown("---")
st.markdown("### 📋 Recente Beurzen")

fairs = dm.get_fairs_for_display()[:5]  # Last 5
if fairs:
    for fair in fairs:
        completeness = fair.get('completeness', {})
        status_emoji = {"complete": "✅", "partial": "⚠️", "missing": "❌"}.get(fair['status'], "❓")

        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.write(f"{status_emoji} **{fair['name']}**")
        with col2:
            st.write(f"{completeness.get('found', 0)}/{completeness.get('total', 5)} docs")
        with col3:
            if st.button("Bekijk", key=f"view_{fair['id']}"):
                st.session_state['selected_fair'] = fair['id']
                st.switch_page("pages/2_Fair_Details.py")
else:
    st.info("Nog geen beurzen geïmporteerd. Start een discovery of importeer JSON resultaten.")
