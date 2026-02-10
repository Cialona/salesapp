"""
Cialona Trade Fair Discovery - Email Generator
Generate emails to request missing documents from fair organizers.
"""

import streamlit as st
from pathlib import Path
import sys
from urllib.parse import quote

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
import data_manager as dm
from config import (
    CUSTOM_CSS, CIALONA_ORANGE, CIALONA_NAVY, APP_ICON,
    DOCUMENT_TYPES
)

# Page configuration
st.set_page_config(
    page_title="Email Generator | Cialona",
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
    <h1>📧 Email Generator</h1>
    <p class="tagline">Vraag missende documenten aan bij de beursorganisatie</p>
</div>
""", unsafe_allow_html=True)

# Fair selection
fairs = dm.get_fairs_for_display()
incomplete_fairs = [f for f in fairs if f.get('status') != 'complete']

# Get pre-selected fair from session state
selected_fair_id = st.session_state.get('selected_fair')

col1, col2 = st.columns([2, 1])

with col1:
    if incomplete_fairs:
        fair_options = {f['name']: f['id'] for f in incomplete_fairs}

        # Find default index
        default_index = 0
        if selected_fair_id:
            for i, f in enumerate(incomplete_fairs):
                if f['id'] == selected_fair_id:
                    default_index = i
                    break

        selected_name = st.selectbox(
            "Selecteer Beurs",
            list(fair_options.keys()),
            index=default_index
        )
        selected_fair_id = fair_options[selected_name]
    else:
        st.success("🎉 Alle beurzen zijn compleet! Geen emails nodig.")
        st.stop()

with col2:
    st.metric("Incomplete Beurzen", len(incomplete_fairs))

# Load selected fair
fair = dm.get_fair(selected_fair_id)

if not fair:
    st.error("Beurs niet gevonden")
    st.stop()

# Show missing documents
st.markdown("---")
st.markdown("### ❌ Missende Documenten")

doc_status = fair.get('doc_status', {})
missing_docs = [doc_type for doc_type, found in doc_status.items() if not found]

if not missing_docs:
    st.success("Alle documenten zijn gevonden voor deze beurs!")
    st.stop()

# Display missing docs as checkboxes (user can select which to request)
selected_docs = []
cols = st.columns(3)
for i, doc_type in enumerate(missing_docs):
    doc_info = DOCUMENT_TYPES.get(doc_type, {"icon": "📄", "dutch_name": doc_type, "name": doc_type})
    with cols[i % 3]:
        if st.checkbox(f"{doc_info['icon']} {doc_info['dutch_name']}", value=True, key=f"doc_{doc_type}"):
            selected_docs.append(doc_type)

st.markdown("---")

# Email configuration
st.markdown("### ✉️ Email Configuratie")

col_config1, col_config2 = st.columns(2)

with col_config1:
    # Contact email — default to recommended email from discovery if not manually set
    discovery_output = fair.get('discovery_output', {})
    recommended = discovery_output.get('contact_info', {}).get('recommended_email', '')
    default_email = fair.get('contact_email', '') or recommended
    contact_email = st.text_input(
        "Email Organisatie *",
        value=default_email,
        placeholder="exhibitor@messefrankfurt.com"
    )

    # Save contact email to fair
    if contact_email != fair.get('contact_email'):
        fair['contact_email'] = contact_email
        dm.save_fair(selected_fair_id, fair)

    sender_name = st.text_input(
        "Jouw Naam",
        value="",
        placeholder="Jan Jansen"
    )

with col_config2:
    language = st.selectbox(
        "Taal",
        ["Nederlands", "English", "Deutsch"],
        index=1  # Default English for international fairs
    )

    company_name = st.text_input(
        "Bedrijfsnaam",
        value="Cialona Expo",
        placeholder="Cialona Expo"
    )

# Email templates
def generate_email(fair_name: str, missing_docs: list, language: str, sender: str, company: str) -> tuple:
    """Generate email subject and body based on language."""

    # Get readable document names
    doc_names = []
    for doc_type in missing_docs:
        doc_info = DOCUMENT_TYPES.get(doc_type, {})
        if language == "Nederlands":
            doc_names.append(doc_info.get('dutch_name', doc_type))
        elif language == "Deutsch":
            german_names = {
                'floorplan': 'Geländeplan / Hallenplan',
                'exhibitor_manual': 'Ausstellerhandbuch',
                'rules': 'Technische Richtlinien',
                'schedule': 'Auf- und Abbauzeiten',
                'exhibitor_directory': 'Ausstellerverzeichnis'
            }
            doc_names.append(german_names.get(doc_type, doc_info.get('name', doc_type)))
        else:
            doc_names.append(doc_info.get('name', doc_type))

    doc_list = "\n".join([f"  • {name}" for name in doc_names])
    doc_list_inline = ", ".join(doc_names)

    if language == "Nederlands":
        subject = f"Informatieverzoek standbouw documenten - {fair_name}"
        body = f"""Geachte heer/mevrouw,

Mijn naam is {sender or '[Uw naam]'} en ik werk voor {company}, een standbouwbedrijf gespecialiseerd in beurspresentaties.

Wij zijn momenteel bezig met de voorbereiding voor de deelname van onze klant aan {fair_name}. Om de stand goed te kunnen ontwerpen en bouwen, zijn wij op zoek naar de volgende documenten:

{doc_list}

Zou u zo vriendelijk willen zijn om ons deze documenten toe te sturen, of ons te verwijzen naar de juiste downloadpagina?

Bij voorbaat dank voor uw medewerking.

Met vriendelijke groet,

{sender or '[Uw naam]'}
{company}
"""

    elif language == "Deutsch":
        subject = f"Informationsanfrage Standbau Unterlagen - {fair_name}"
        body = f"""Sehr geehrte Damen und Herren,

mein Name ist {sender or '[Ihr Name]'} und ich arbeite für {company}, ein Messebauunternehmen.

Wir bereiten derzeit die Teilnahme unseres Kunden an der {fair_name} vor. Für die Planung und den Bau des Messestands benötigen wir folgende Unterlagen:

{doc_list}

Könnten Sie uns diese Dokumente zusenden oder uns auf die entsprechende Download-Seite verweisen?

Vielen Dank im Voraus für Ihre Unterstützung.

Mit freundlichen Grüßen,

{sender or '[Ihr Name]'}
{company}
"""

    else:  # English
        subject = f"Document Request for Stand Construction - {fair_name}"
        body = f"""Dear Sir or Madam,

My name is {sender or '[Your name]'} and I work for {company}, a stand construction company specializing in exhibition presentations.

We are currently preparing for our client's participation at {fair_name}. In order to properly design and build the stand, we are looking for the following documents:

{doc_list}

Would you be so kind as to send us these documents, or direct us to the appropriate download page?

Thank you in advance for your assistance.

Best regards,

{sender or '[Your name]'}
{company}
"""

    return subject, body

# Generate email
if selected_docs:
    subject, body = generate_email(
        fair.get('name', 'Trade Fair'),
        selected_docs,
        language,
        sender_name,
        company_name
    )

    st.markdown("---")
    st.markdown("### 📝 Gegenereerde Email")

    # Editable fields
    edited_subject = st.text_input("Onderwerp", value=subject)
    edited_body = st.text_area("Bericht", value=body, height=400)

    st.markdown("---")
    st.markdown("### 🚀 Verzenden")

    # Create mailto link
    mailto_link = f"mailto:{contact_email}?subject={quote(edited_subject)}&body={quote(edited_body)}"

    col_send1, col_send2, col_send3 = st.columns(3)

    with col_send1:
        if contact_email:
            st.markdown(f"""
            <a href="{mailto_link}" target="_blank" style="
                display: inline-block;
                background: linear-gradient(135deg, {CIALONA_ORANGE} 0%, #E8850F 100%);
                color: white;
                padding: 0.75rem 1.5rem;
                border-radius: 8px;
                text-decoration: none;
                font-weight: 500;
                text-align: center;
                width: 100%;
            ">
                📧 Open in Outlook
            </a>
            """, unsafe_allow_html=True)
        else:
            st.warning("Vul eerst een email adres in")

    with col_send2:
        # Copy to clipboard button
        st.code(edited_body, language=None)

    with col_send3:
        # Mark as contacted
        if st.button("✅ Markeer als Gecontacteerd"):
            from datetime import datetime
            notes = fair.get('notes', [])
            notes.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}: Email verstuurd naar {contact_email} voor: {', '.join(selected_docs)}")
            fair['notes'] = notes
            dm.save_fair(selected_fair_id, fair)
            st.success("Gemarkeerd als gecontacteerd!")

    # Instructions
    st.markdown("---")
    st.info("""
    **Hoe te gebruiken:**
    1. Vul het email adres van de beursorganisatie in
    2. Pas eventueel de email tekst aan
    3. Klik op "Open in Outlook" om de email in je mailprogramma te openen
    4. Controleer en verstuur de email
    5. Klik op "Markeer als Gecontacteerd" om bij te houden dat je contact hebt opgenomen
    """)

else:
    st.warning("Selecteer minimaal één document om aan te vragen.")

# Footer with tips
st.markdown("---")
with st.expander("💡 Tips voor het vinden van contact informatie"):
    st.markdown("""
    **Waar vind je het juiste email adres?**

    1. **Website footer** - Vaak staat er een algemeen contact email
    2. **"For Exhibitors" sectie** - Specifieke contactpersoon voor exposanten
    3. **"Contact" pagina** - Algemene contactgegevens
    4. **Download center** - Soms staat er een contact bij de documenten
    5. **Bevestigingsmail** - Als je klant al is aangemeld, staat er vaak een contactpersoon in de bevestiging

    **Typische email formaten:**
    - exhibitor@[beursnaam].com
    - info@[beursnaam].de
    - service@messe[stad].com
    """)
