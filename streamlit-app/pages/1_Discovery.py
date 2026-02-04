"""
Cialona Trade Fair Discovery - Discovery Page
Simple interface to start discoveries directly in the app.
"""

import streamlit as st
import json
import asyncio
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import os

import anthropic
import socket
from urllib.parse import urlparse

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


def ensure_playwright_installed():
    """Ensure Playwright browsers are installed."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception as e:
        error_str = str(e)
        if "Executable doesn't exist" in error_str or "browserType.launch" in error_str:
            st.info("🔧 Eerste keer setup: Playwright browsers installeren...")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    return True
                else:
                    st.error(f"Playwright installatie mislukt: {result.stderr}")
                    return False
            except Exception as install_error:
                st.error(f"Kon Playwright niet installeren: {install_error}")
                return False
        else:
            st.error(f"Playwright fout: {e}")
            return False


def validate_url(url: str) -> bool:
    """Check if a URL's domain resolves and is reachable."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        # Try DNS resolution
        socket.gethostbyname(hostname)
        return True
    except (socket.gaierror, socket.herror, Exception):
        return False


def find_fair_website(api_key: str, fair_name: str, year: int, city: str = None, failed_url: str = None) -> dict:
    """Use Claude to find the official website URL for a trade fair."""
    client = anthropic.Anthropic(api_key=api_key)

    error_context = ""
    if failed_url:
        error_context = f"""

IMPORTANT: The previously suggested URL "{failed_url}" was INVALID (domain does not exist).
Please double-check the exact spelling of the domain name and provide a CORRECT URL.
Common mistakes: typos in domain names like "salonilemilano" instead of "salonemilano".
"""

    prompt = f"""Find the official website URL for this trade fair:{error_context}

Trade Fair: {fair_name}
Year: {year}
{f'City: {city}' if city else ''}

CRITICAL: Double-check the EXACT spelling of the domain name! Common trade fair websites:
- Salone del Mobile: salonemilano.it (NOT salonilemilano)
- Ambiente: ambiente.messefrankfurt.com
- bauma: bauma.de
- ISPO Munich: ispo.com

Return ONLY a JSON object with these fields:
- url: The official website URL (the exhibitor/aussteller section if possible). VERIFY SPELLING!
- confidence: "high", "medium", or "low"
- notes: Brief explanation

Example response:
{{"url": "https://www.bauma.de/en/trade-fair/exhibitors/", "confidence": "high", "notes": "Official bauma website, exhibitor section"}}

If you cannot find a reliable URL, return:
{{"url": null, "confidence": "low", "notes": "Could not find official website"}}

Return ONLY the JSON, no other text."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.content[0].text.strip()

        # Try to parse JSON from response
        # Handle cases where response might have markdown code blocks
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        result = json.loads(response_text)
        return result

    except Exception as e:
        return {"url": None, "confidence": "low", "notes": f"Error: {str(e)}"}


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

# Simple form
st.markdown("### Beurs Informatie")

col1, col2 = st.columns(2)

with col1:
    fair_name = st.text_input(
        "Beurs Naam *",
        placeholder="bijv. Ambiente, bauma, ISPO Munich"
    )
    fair_city = st.text_input(
        "Stad",
        placeholder="bijv. Frankfurt, München, Milaan"
    )

with col2:
    # Year input - default to next year
    current_year = datetime.now().year
    fair_year = st.number_input(
        "Jaar *",
        min_value=2020,
        max_value=2035,
        value=current_year + 1,
        step=1
    )
    fair_country = st.text_input(
        "Land",
        placeholder="bijv. Germany, Italy, Netherlands"
    )

st.markdown("---")

# Info box
st.info("""
**Hoe werkt het?**
1. Voer de beursnaam en het jaar in
2. Klik op 'Start Discovery'
3. De AI zoekt eerst de officiële website
4. Daarna worden automatisch documenten gezocht (~2-3 minuten)

**Geschatte kosten:** ~€1.80 per beurs
""")

# Check for API key
api_key = os.environ.get('ANTHROPIC_API_KEY')
if not api_key:
    try:
        api_key = st.secrets.get('ANTHROPIC_API_KEY')
    except:
        pass

if not api_key:
    st.warning("⚠️ Anthropic API key niet geconfigureerd.")
    st.markdown("""
    **Hoe configureer je de API key?**
    1. Ga naar je app in Streamlit Cloud
    2. Klik op "Manage app" (rechtsonder) → "Settings" → "Secrets"
    3. Voeg toe:
    ```
    ANTHROPIC_API_KEY = "sk-ant-..."
    ```
    """)
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

        def update_logs(msg):
            """Update the log display."""
            logs.append(msg)
            log_container.code("\n".join(logs[-25:]))  # Show last 25 lines

        # Step 1: Find the official website URL
        update_logs(f"🔍 Zoeken naar officiële website voor: {fair_name} {fair_year}")
        status_text.text("Officiële website zoeken...")
        progress_bar.progress(5)

        fair_url = None
        max_url_attempts = 3
        failed_url = None

        for attempt in range(max_url_attempts):
            website_result = find_fair_website(api_key, fair_name, fair_year, fair_city, failed_url=failed_url)
            candidate_url = website_result.get("url")
            confidence = website_result.get("confidence", "low")
            notes = website_result.get("notes", "")

            if candidate_url:
                update_logs(f"🔗 URL gevonden: {candidate_url}")
                update_logs(f"   Zekerheid: {confidence} - {notes}")

                # Validate the URL
                status_text.text("URL valideren...")
                if validate_url(candidate_url):
                    update_logs(f"✅ URL gevalideerd!")
                    fair_url = candidate_url
                    break
                else:
                    update_logs(f"⚠️ URL ongeldig (domein bestaat niet), opnieuw zoeken...")
                    failed_url = candidate_url
            else:
                update_logs(f"⚠️ Geen URL gevonden: {notes}")
                break

        if not fair_url:
            update_logs(f"⚠️ Geen geldige website gevonden, agent zal zelf zoeken...")

        progress_bar.progress(10)

        # Step 2: Check Playwright
        status_text.text("Browser controleren...")
        if not ensure_playwright_installed():
            st.error("Browser kon niet worden gestart. Probeer het later opnieuw.")
            st.stop()

        progress_bar.progress(15)

        async def run_discovery_async():
            """Run the discovery asynchronously."""
            from discovery.claude_agent import ClaudeAgent
            from discovery.schemas import TestCaseInput, output_to_dict

            if fair_url:
                update_logs(f"🌐 Start URL: {fair_url}")
            else:
                update_logs(f"🔍 Agent zal zelf zoeken naar de website")

            status_text.text("AI agent wordt gestart...")

            input_data = TestCaseInput(
                fair_name=f"{fair_name} {fair_year}",
                known_url=fair_url,
                city=fair_city if fair_city else None,
                country=fair_country if fair_country else None
            )

            agent = ClaudeAgent(
                api_key=api_key,
                max_iterations=30,
                debug=True,
                on_status=update_logs
            )

            progress_bar.progress(20)
            status_text.text("Navigeren door website...")

            output = await agent.run(input_data)
            return output_to_dict(output)

        try:
            # Run the async discovery
            result = asyncio.run(run_discovery_async())

            progress_bar.progress(90)
            status_text.text("Resultaten verwerken...")

            # Add year to result
            result['year'] = fair_year

            # Import the result into data manager
            fair_id = dm.import_discovery_result(result)

            progress_bar.progress(100)
            status_text.text("✅ Discovery voltooid!")

            update_logs("✅ Discovery succesvol afgerond!")

            # Show results summary
            fair = dm.get_fair(fair_id)
            if fair:
                completeness = fair.get('completeness', {})
                st.success(f"""
                **Discovery voltooid voor {fair_name} {fair_year}!**

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

        except Exception as e:
            error_msg = str(e)
            update_logs(f"❌ Fout: {error_msg}")
            st.error(f"Er ging iets mis: {error_msg}")

            import traceback
            with st.expander("🔧 Technische details"):
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
