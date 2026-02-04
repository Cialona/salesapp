"""
Cialona Trade Fair Discovery - Discovery Page
Simple interface to start discoveries directly in the app.
"""

import streamlit as st
import json
import asyncio
from pathlib import Path
import sys
import os

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

# Simple form - just name and URL
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

# Info box
st.info("""
**Hoe werkt het?**
1. Voer de beursnaam en website URL in
2. Klik op 'Start Discovery'
3. De AI agent zoekt automatisch naar documenten (~2-3 minuten)
4. Resultaten verschijnen direct in het dashboard

**Geschatte kosten:** ~€1.75 per beurs
""")

# Check for API key
api_key = os.environ.get('ANTHROPIC_API_KEY') or st.secrets.get('ANTHROPIC_API_KEY', None)

if not api_key:
    st.warning("⚠️ Anthropic API key niet geconfigureerd. Vraag de beheerder om deze toe te voegen in de app settings.")
    st.stop()

# Start Discovery button
if st.button("🚀 Start Discovery", type="primary", disabled=not fair_name, use_container_width=True):
    if not fair_name:
        st.error("Vul een beursnaam in")
    else:
        # Show progress
        progress_container = st.container()

        with progress_container:
            st.markdown("### 🔄 Discovery bezig...")
            progress_bar = st.progress(0)
            status_text = st.empty()
            log_expander = st.expander("📋 Voortgang details", expanded=True)

            with log_expander:
                log_container = st.empty()
                logs = []

        try:
            # Import the discovery module
            status_text.text("Initialiseren...")
            progress_bar.progress(5)

            # We need to run the TypeScript agent via subprocess
            # For now, let's use a Python-based approach that calls the CLI
            import subprocess
            import tempfile

            status_text.text("Discovery starten...")
            progress_bar.progress(10)

            # Create input JSON
            input_data = {
                "fair_name": fair_name,
                "known_url": fair_url if fair_url else None,
                "city": fair_city if fair_city else None,
                "country": fair_country if fair_country else None
            }

            # Save to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(input_data, f)
                input_file = f.name

            logs.append(f"🎯 Zoeken naar: {fair_name}")
            if fair_url:
                logs.append(f"🌐 Start URL: {fair_url}")
            log_container.code("\n".join(logs))

            status_text.text("AI agent navigeert door de website...")
            progress_bar.progress(20)

            # Run the discovery CLI
            # Note: This requires the Node.js environment to be set up
            result = subprocess.run(
                ['npx', 'tsx', 'cli/discover-claude.ts', '--input', input_file, '--output', '/dev/stdout'],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                env={**os.environ, 'ANTHROPIC_API_KEY': api_key}
            )

            progress_bar.progress(90)

            if result.returncode == 0:
                # Parse the output JSON
                output_lines = result.stdout.strip().split('\n')
                # Find the JSON output (last valid JSON in output)
                json_output = None
                for line in reversed(output_lines):
                    try:
                        json_output = json.loads(line)
                        break
                    except:
                        continue

                if json_output:
                    # Import the result
                    fair_id = dm.import_discovery_result(json_output)

                    progress_bar.progress(100)
                    status_text.text("✅ Discovery voltooid!")

                    logs.append("✅ Discovery succesvol afgerond!")
                    log_container.code("\n".join(logs))

                    # Show results summary
                    fair = dm.get_fair(fair_id)
                    if fair:
                        completeness = fair.get('completeness', {})
                        st.success(f"""
                        **Discovery voltooid voor {fair_name}!**

                        Documenten gevonden: **{completeness.get('found', 0)}/{completeness.get('total', 5)}**
                        """)

                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("📄 Bekijk Details", use_container_width=True):
                                st.session_state['selected_fair'] = fair_id
                                st.switch_page("pages/2_Fair_Details.py")
                        with col2:
                            if st.button("🏠 Naar Dashboard", use_container_width=True):
                                st.switch_page("app.py")
                else:
                    st.error("Kon resultaat niet verwerken")
                    st.code(result.stdout)
            else:
                st.error(f"Discovery mislukt: {result.stderr}")
                logs.append(f"❌ Fout: {result.stderr}")
                log_container.code("\n".join(logs))

        except subprocess.TimeoutExpired:
            st.error("Discovery duurde te lang (timeout na 5 minuten)")
        except FileNotFoundError:
            st.error("Node.js/npm niet gevonden. Neem contact op met de beheerder.")
        except Exception as e:
            st.error(f"Er ging iets mis: {str(e)}")
            import traceback
            st.code(traceback.format_exc())

st.markdown("---")

# Alternative: JSON Import (collapsible, for advanced users)
with st.expander("📥 JSON Importeren (voor beheerders)"):
    st.markdown("Heb je al een discovery resultaat? Plak de JSON hier.")

    json_input = st.text_area(
        "JSON Data",
        height=200,
        placeholder='{"fair_name": "Ambiente", "documents": {...}, ...}'
    )

    uploaded_file = st.file_uploader("Of upload een JSON bestand", type=['json'])

    if uploaded_file is not None:
        json_input = uploaded_file.read().decode('utf-8')
        st.success(f"Bestand geladen: {uploaded_file.name}")

    if st.button("📥 Importeren", disabled=not json_input):
        try:
            discovery_data = json.loads(json_input)

            if 'fair_name' not in discovery_data:
                st.error("JSON moet een 'fair_name' veld bevatten")
            else:
                fair_id = dm.import_discovery_result(discovery_data)
                st.success(f"✅ Beurs '{discovery_data['fair_name']}' geïmporteerd!")

                if st.button("Bekijk Details"):
                    st.session_state['selected_fair'] = fair_id
                    st.switch_page("pages/2_Fair_Details.py")

        except json.JSONDecodeError as e:
            st.error(f"Ongeldige JSON: {e}")
