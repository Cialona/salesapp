# Knowledge Export: Salesapp → Exhibitor Scraper

Dit document is een volledige kennisoverdracht van de bestaande **salesapp** (Trade Fair Discovery) naar een nieuw project: de **Exhibitor Scraper**. Het bevat alle patronen, code-blokken, configuratie en lessen die nuttig zijn om mee te nemen.

---

## Inhoudsopgave

1. [Hoe praat de app met de Anthropic API?](#1-hoe-praat-de-app-met-de-anthropic-api)
2. [Hoe wordt de browser aangestuurd?](#2-hoe-wordt-de-browser-aangestuurd)
3. [Hoe is de Streamlit app opgezet?](#3-hoe-is-de-streamlit-app-opgezet)
4. [Welke lessen zijn geleerd?](#4-welke-lessen-zijn-geleerd)
5. [Welke code-patronen zijn het waard om over te nemen?](#5-welke-code-patronen-zijn-het-waard-om-over-te-nemen)
6. [Dependencies en environment](#6-dependencies-en-environment)

---

## 1. Hoe praat de app met de Anthropic API?

### 1.1 Client initialisatie

De Anthropic client wordt aangemaakt in de `ClaudeAgent.__init__()` methode. De API key komt uit een environment variable of Streamlit Secrets.

```python
import anthropic

# In de agent class
self.client = anthropic.Anthropic(api_key=api_key)

# API key ophalen (in de Streamlit pagina)
api_key = os.environ.get('ANTHROPIC_API_KEY')
if not api_key:
    try:
        api_key = st.secrets.get('ANTHROPIC_API_KEY')
    except Exception:
        pass
```

**Belangrijk:** De `anthropic` package wordt gebruikt, niet de REST API direct. Dit handelt automatisch headers, serialisatie en error types af.

### 1.2 Model en versie

Het model is `claude-sonnet-4-20250514`. Dit wordt op twee manieren aangeroepen:

**1. Gewone text-API calls** (voor simpele taken zoals URL lookup):
```python
resp = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=500,
    messages=[{"role": "user", "content": prompt}],
)
text = resp.content[0].text.strip()
```

**2. Computer Use beta API** (voor browser-interactie):
```python
response = self.client.beta.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4096,
    system=system_prompt,
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
            "description": "Navigate directly to a URL.",
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
            "description": "Perform a deep scan of the current page.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    ],
    messages=messages,
)
```

**Let op:** Computer Use gebruikt `client.beta.messages.create()` (niet `client.messages.create()`), en vereist de `betas=["computer-use-2025-01-24"]` parameter.

### 1.3 De agent-loop (kern van het systeem)

De agent-loop is het hart van het hele systeem. Dit is hoe het werkt:

```
Stap 1: Stuur screenshot + systeem-prompt naar Claude
Stap 2: Claude antwoordt met text EN/OF tool_use blokken
Stap 3: Als er tool_use blokken zijn → voer ze uit → stuur resultaat terug → ga naar stap 1
Stap 4: Als Claude klaar is (geen tool_use) → parse het eindresultaat
```

Hier is het volledige patroon, vereenvoudigd voor hergebruik:

```python
import asyncio
import anthropic

async def run_agent_loop(
    client: anthropic.Anthropic,
    browser,  # BrowserController instance
    system_prompt: str,
    initial_url: str,
    max_iterations: int = 40,
):
    """Generiek agent-loop patroon met Computer Use."""

    # 1. Navigeer naar start-URL en maak eerste screenshot
    await browser.goto(initial_url)
    screenshot = await browser.screenshot()

    # 2. Bouw de initiële messages-lijst
    messages = [
        {
            "role": "user",
            "content": [
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
                    "text": f"Je bent op: {initial_url}\nStart met je opdracht.",
                },
            ],
        }
    ]

    final_result = None

    # 3. Agent-loop
    for iteration in range(max_iterations):

        # 3a. Roep Claude aan
        response = client.beta.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            betas=["computer-use-2025-01-24"],
            tools=[ ... ],  # computer + custom tools
            messages=messages,
        )

        # 3b. Voeg Claude's antwoord toe aan messages
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # 3c. Check voor tekst (mogelijk eindresultaat)
        for block in assistant_content:
            if block.type == "text":
                # Check of dit het eindresultaat bevat
                if is_final_result(block.text):
                    final_result = block.text

        # 3d. Check voor tool_use blokken
        tool_use_blocks = [b for b in assistant_content if b.type == "tool_use"]

        if len(tool_use_blocks) == 0:
            # Claude is klaar (geen tools meer nodig)
            break

        # 3e. Voer elke tool uit en verzamel resultaten
        tool_results = []
        for tool_use in tool_use_blocks:
            if tool_use.name == "computer":
                result = await execute_computer_action(browser, tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })
            elif tool_use.name == "my_custom_tool":
                result = await execute_custom_tool(tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })
            else:
                # Onbekende tool → foutmelding teruggeven
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": [{"type": "text", "text": f"Tool '{tool_use.name}' is not available."}],
                    "is_error": True,
                })

        # 3f. Voeg tool resultaten toe als user message
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        else:
            # BELANGRIJK: Voorkom lege user messages!
            messages.append({"role": "user", "content": [{"type": "text", "text": "Ga verder."}]})

    return final_result
```

### 1.4 Screenshots terugsturen naar Claude

Na elke tool-actie wordt een screenshot gemaakt en als base64-encoded PNG teruggestuurd. Dit is het format:

```python
# Screenshot maken
screenshot = await browser.screenshot()  # Geeft ScreenshotResult(base64, width, height)

# Als tool_result terugsturen
tool_result_content = [
    {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": screenshot.base64,  # base64-encoded PNG string
        },
    },
    {
        "type": "text",
        "text": f"URL: {state.url}\nTitle: {state.title}",
    },
]
```

**Belangrijk:** Stuur ALTIJD een screenshot terug na elke computer-actie. Claude heeft de visuele feedback nodig om te begrijpen wat er op de pagina staat. Voeg ook de huidige URL en titel toe als tekst — dat helpt Claude met navigatie.

### 1.5 Extra context meesturen na elke actie

Een belangrijk patroon: na elke browser-actie worden niet alleen de screenshot maar ook de **geëxtraheerde links** meegestuurd. Dit geeft Claude extra context die niet altijd zichtbaar is in de screenshot:

```python
# Na elke computer-actie
result = await self._execute_computer_action(tool_use.input)

# Extract links from page and append as text
link_info = await self._extract_and_format_links()
if link_info:
    result.append({"type": "text", "text": link_info})
```

De link_info bevat gestructureerde tekst zoals:
```
📄 PDF LINKS OP DEZE PAGINA:
• Technical Guidelines 2026: https://example.com/technical.pdf
• Floor Plan Hall 1: https://example.com/floor-plan.pdf

🔗 RELEVANTE LINKS:
• For Exhibitors: https://example.com/exhibitors
• Downloads: https://example.com/downloads
```

**Voor de Exhibitor Scraper:** Stuur na elke actie ook de geëxtraheerde exposantendata mee, zodat Claude weet wat er al gevonden is.

### 1.6 Rate limiting en retry

De Anthropic API geeft soms `429 Rate Limit` errors. Het retry-patroon met exponential backoff:

```python
import random
import anthropic

response = None
for attempt in range(5):
    try:
        response = client.beta.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            betas=["computer-use-2025-01-24"],
            tools=tools,
            messages=messages,
        )
        break  # Succes!
    except anthropic.RateLimitError as e:
        wait = (2 ** attempt) * 5 + random.uniform(0, 3)
        # Wachttijden: ~5s, ~13s, ~23s, ~43s, ~83s
        print(f"Rate limit (poging {attempt + 1}/5), wacht {wait:.0f}s...")
        await asyncio.sleep(wait)
        if attempt == 4:
            raise  # Geef op na 5 pogingen

if response is None:
    raise RuntimeError("API call failed after 5 retries")
```

**Geleerde les:** De base wait is 5 seconden (niet 1 seconde). Anthropic rate limits zijn per minuut, dus korte waits zijn niet effectief. De `random.uniform(0, 3)` voorkomt dat meerdere concurrent processen tegelijk opnieuw proberen (thundering herd).

### 1.7 Midpoint-waarschuwing en afsluitsignaal

De agent krijgt op twee momenten extra instructies ingestuurd:

**Halverwege de iteraties — tussentijdse check:**
```python
midpoint = effective_max_iterations // 2
if iteration == midpoint:
    inject_text = f"""📊 TUSSENTIJDSE CHECK (iteratie {midpoint}/{effective_max_iterations}):
Je zoekt nog naar: {missing_items}
Je hebt nog {remaining} acties - gebruik ze gericht!"""
```

**3 iteraties voor het einde — afsluitsignaal:**
```python
if iteration == effective_max_iterations - 3:
    inject_text = """⚠️ Je hebt nog 3 acties over. Begin nu met je JSON samenvatting."""
```

**Patroon voor injecteren van extra tekst in messages:**
```python
# BELANGRIJK: Vermijd twee opeenvolgende user-messages!
# Merge inject_text in de laatste user-message als die er al is.
if inject_text and messages and messages[-1]["role"] == "user":
    last_content = messages[-1]["content"]
    if isinstance(last_content, list):
        last_content.append({"type": "text", "text": inject_text})
    else:
        messages[-1]["content"] = [{"type": "text", "text": inject_text}]
elif inject_text:
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": inject_text}],
    })
```

**Waarom dit belangrijk is:** De Anthropic API staat geen twee opeenvolgende `user` messages toe. Als je na tool_results NOG een instructie wilt meegeven, moet je die MERGEN in de bestaande user message.

### 1.8 Hoe het gesprek (messages) wordt opgebouwd

De messages-lijst groeit gedurende de sessie:

```
messages = [
    {"role": "user",      "content": [screenshot + initial_text]},          # Iteratie 0: start
    {"role": "assistant", "content": [text + tool_use(click)]},             # Claude wil klikken
    {"role": "user",      "content": [tool_result(screenshot + links)]},    # Resultaat van klik
    {"role": "assistant", "content": [text + tool_use(goto_url)]},          # Claude wil navigeren
    {"role": "user",      "content": [tool_result(screenshot + links)]},    # Resultaat van navigatie
    {"role": "assistant", "content": [text + tool_use(scroll)]},            # Claude wil scrollen
    {"role": "user",      "content": [tool_result(screenshot)]},            # Resultaat van scroll
    ...
    {"role": "assistant", "content": [text(JSON resultaat)]},               # Eindresultaat
]
```

**Let op:** De messages worden NIET getrimmed of samengevat. De volledige conversatie wordt bij elke API call meegestuurd. Dit is prima voor 20-40 iteraties, maar zou een probleem kunnen worden bij langere sessies door het context window.

---

## 2. Hoe wordt de browser aangestuurd?

### 2.1 Playwright opstarten

De browser wordt headless gestart met specifieke instellingen:

```python
from playwright.async_api import async_playwright, Browser, Page, BrowserContext

class BrowserController:
    def __init__(self, width: int = 1024, height: int = 768):
        self.width = width
        self.height = height
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def launch(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        self._context = await self._browser.new_context(
            viewport={'width': self.width, 'height': self.height},
            accept_downloads=True
        )
        self._page = await self._context.new_page()

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
```

**Belangrijk:**
- `headless=True` — verplicht op servers / Streamlit Cloud
- `--no-sandbox` — nodig in Docker/containerized omgevingen
- `--disable-setuid-sandbox` — zelfde reden
- `viewport={'width': 1024, 'height': 768}` — de Computer Use API verwacht screenshots van deze grootte
- `accept_downloads=True` — nodig als je bestanden wilt downloaden

### 2.2 Screenshots maken en naar base64

```python
import base64

async def screenshot(self) -> ScreenshotResult:
    buffer = await self._page.screenshot(type='png')
    b64 = base64.b64encode(buffer).decode('utf-8')
    return ScreenshotResult(
        base64=b64,
        width=self.width,
        height=self.height
    )
```

De screenshot is een PNG van de hele viewport (1024x768). Dit wordt als base64 string meegestuurd in de API call.

### 2.3 Navigeren met retry

```python
async def goto(self, url: str, timeout: int = 30000):
    """Navigate to URL with retry on timeout."""
    last_error = None
    timeouts = [timeout, timeout * 2, timeout * 3]
    for attempt, t in enumerate(timeouts, 1):
        try:
            await self._page.goto(url, wait_until='domcontentloaded', timeout=t)
            await self._page.wait_for_timeout(1000)  # Extra 1s wachten
            return
        except Exception as e:
            last_error = e
            if attempt < len(timeouts):
                await self._page.wait_for_timeout(2000)  # 2s wachten voor retry
    raise last_error
```

**Geleerde les:** `wait_until='domcontentloaded'` is beter dan `'networkidle'` voor beurswebsites. Veel sites laden tracking-scripts die nooit klaar zijn, waardoor `networkidle` timeouts geeft. Na `domcontentloaded` is de pagina meestal bruikbaar.

**Extra wachttijd:** Na navigatie altijd 1 seconde wachten (`wait_for_timeout(1000)`). Veel beurswebsites laden content dynamisch na DOMContentLoaded.

### 2.4 Klikken, scrollen, typen

```python
async def click(self, x: int, y: int):
    await self._page.mouse.click(x, y)
    await self._page.wait_for_timeout(500)

async def scroll(self, x: int, y: int, delta_x: int, delta_y: int):
    await self._page.mouse.move(x, y)
    await self._page.mouse.wheel(delta_x, delta_y)
    await self._page.wait_for_timeout(300)

async def type_text(self, text: str):
    await self._page.keyboard.type(text, delay=50)

async def press_key(self, key: str):
    key_map = {
        'enter': 'Enter', 'return': 'Enter', 'tab': 'Tab',
        'escape': 'Escape', 'backspace': 'Backspace',
        'up': 'ArrowUp', 'down': 'ArrowDown',
        'pageup': 'PageUp', 'pagedown': 'PageDown',
        'space': ' ',
    }
    mapped_key = key_map.get(key.lower(), key)
    await self._page.keyboard.press(mapped_key)
```

**Belangrijk:** Na elke interactie een korte wacht inbouwen:
- Na klik: 500ms
- Na scroll: 300ms
- Na navigatie: 1000ms

Dit geeft de pagina tijd om te reageren (animaties, lazy loading, AJAX requests).

### 2.5 Computer Use actie-handler

Dit is hoe Claude's `computer` tool acties worden vertaald naar Playwright commando's:

```python
async def _execute_computer_action(self, input_data: dict):
    action = input_data.get("action", "")

    if action == "screenshot":
        pass  # Alleen screenshot (wordt altijd aan het einde gemaakt)

    elif action == "left_click":
        coord = input_data.get("coordinate")
        if coord:
            await self.browser.click(coord[0], coord[1])

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

    elif action == "mouse_move":
        coord = input_data.get("coordinate", [0, 0])
        await self.browser.move_mouse(coord[0], coord[1])

    elif action == "double_click":
        coord = input_data.get("coordinate")
        if coord:
            await self.browser.double_click(coord[0], coord[1])

    elif action == "right_click":
        coord = input_data.get("coordinate")
        if coord:
            await self.browser.right_click(coord[0], coord[1])

    elif action == "left_click_drag":
        start = input_data.get("start_coordinate", [0, 0])
        end = input_data.get("end_coordinate", [0, 0])
        await self.browser.drag(start[0], start[1], end[0], end[1])

    # Altijd na de actie: wacht, screenshot, en return
    await asyncio.sleep(0.5)
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
```

### 2.6 Links extraheren van een pagina

Een uitgebreide link-extractie die ook verborgen content vindt:

```python
async def extract_links(self):
    """Extract all links from the current page."""
    # STAP 1: Eerst alle verborgen secties openen
    await self._expand_all_hidden_sections()

    # STAP 2: Links extraheren via JavaScript
    links = await self._page.evaluate('''() => {
        const results = [];
        const seen = new Set();

        // Standaard <a href> links
        document.querySelectorAll('a[href]').forEach(a => {
            const href = a.getAttribute('href') || '';
            const text = (a.textContent || '').trim();
            if (href.length > 0 && !seen.has(href)) {
                seen.add(href);
                results.push({href, text, source: 'a'});
            }
        });

        // Buttons met data-href, data-url, etc.
        const dataAttrs = ['data-href', 'data-url', 'data-link', 'data-target-url'];
        document.querySelectorAll('button, [role="button"]').forEach(el => {
            for (const attr of dataAttrs) {
                const val = el.getAttribute(attr);
                if (val && val.startsWith('http') && !seen.has(val)) {
                    seen.add(val);
                    results.push({href: val, text: (el.textContent || '').trim()});
                }
            }
        });

        // onclick handlers met URL's
        document.querySelectorAll('[onclick]').forEach(el => {
            const onclick = el.getAttribute('onclick') || '';
            const urlPatterns = [
                /window\\.open\\s*\\(\\s*['"]([^'"]+)['"]/,
                /window\\.location\\.href\\s*=\\s*['"]([^'"]+)['"]/,
            ];
            for (const pattern of urlPatterns) {
                const match = onclick.match(pattern);
                if (match) {
                    const url = match[1] || match[0];
                    if (!seen.has(url)) {
                        seen.add(url);
                        results.push({href: url, text: (el.textContent || '').trim()});
                    }
                }
            }
        });

        return results;
    }''')

    return links
```

### 2.7 Verborgen secties openen (accordions, dropdowns)

Veel beurswebsites verbergen content achter accordions. Deze functie opent ze allemaal:

```python
async def _expand_all_hidden_sections(self):
    """Open alle accordions, details, en dropdowns."""
    await self._page.evaluate('''() => {
        // 1. Alle <details> elementen openen
        document.querySelectorAll('details').forEach(d => d.open = true);

        // 2. Accordion triggers klikken
        const selectors = [
            '[data-toggle="collapse"]',
            '[data-bs-toggle="collapse"]',
            '.accordion-button',
            '.accordion-trigger',
            '[aria-expanded="false"]',
            '.expandable:not(.expanded)',
            'button[class*="accordion"]',
        ];
        selectors.forEach(selector => {
            try {
                document.querySelectorAll(selector).forEach(el => {
                    if (el.getAttribute('aria-expanded') === 'false') {
                        el.click();
                    }
                });
            } catch(e) {}
        });

        // 3. aria-expanded op true zetten
        document.querySelectorAll('[aria-expanded="false"]').forEach(el => {
            el.setAttribute('aria-expanded', 'true');
            el.click();
        });

        // 4. Bootstrap collapse elementen tonen
        document.querySelectorAll('.collapse:not(.show)').forEach(el => {
            el.classList.add('show');
        });

        // 5. Material UI accordions
        document.querySelectorAll('[class*="MuiAccordion"]:not([class*="expanded"])').forEach(el => {
            const button = el.querySelector('[class*="MuiAccordionSummary"]');
            if (button) button.click();
        });
    }''')
    await self._page.wait_for_timeout(500)
```

### 2.8 Navigatie-links extraheren (mega-menu's zichtbaar maken)

Veel beurswebsites gebruiken mega-menu's die alleen zichtbaar worden bij hover. Deze functie maakt ze zichtbaar via CSS injection:

```python
async def extract_navigation_links(self):
    """Extract links from the main navigation, including hidden dropdown menus."""

    # Stap 1: Hover-events triggeren op top-level nav items
    await self._page.evaluate('''() => {
        const selectors = [
            'nav > ul > li', 'header nav li.dropdown',
            '.navbar-nav > li', '[role="navigation"] > ul > li',
        ];
        for (const sel of selectors) {
            try {
                document.querySelectorAll(sel).forEach(el => {
                    el.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
                    el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                });
            } catch(e) {}
        }
    }''')
    await asyncio.sleep(0.3)

    # Stap 2: CSS injection om dropdown-menus te forceren
    await self._page.evaluate('''() => {
        const style = document.createElement("style");
        style.id = "__nav_reveal__";
        style.textContent = `
            nav ul ul, nav li > ul, nav li > div,
            .dropdown-menu, .sub-menu, .submenu, .mega-menu,
            [class*="dropdown"] > ul, [class*="dropdown"] > div,
            [class*="submenu"], [class*="sub-menu"],
            nav li ul, header nav li ul, .navbar ul ul {
                display: block !important;
                visibility: visible !important;
                opacity: 1 !important;
                max-height: none !important;
            }
        `;
        document.head.appendChild(style);
    }''')
    await asyncio.sleep(0.2)

    # Stap 3: Links extraheren uit nu-zichtbare navigatie
    nav_links = await self._page.evaluate('''() => {
        const results = [];
        const seen = new Set();
        const selectors = [
            'nav a[href]', 'header a[href]',
            '[role="navigation"] a[href]',
            '.nav a[href]', '.navbar a[href]',
        ];
        for (const selector of selectors) {
            document.querySelectorAll(selector).forEach(a => {
                const href = a.getAttribute('href') || '';
                const text = (a.textContent || '').trim();
                if (href.length > 1 && !seen.has(href) && text.length > 0) {
                    seen.add(href);
                    results.push({href, text});
                }
            });
        }
        return results;
    }''')

    # Stap 4: CSS cleanup
    await self._page.evaluate('''() => {
        const el = document.getElementById("__nav_reveal__");
        if (el) el.remove();
    }''')

    return nav_links
```

### 2.9 Email-adressen extraheren

```python
async def extract_emails(self):
    """Extract email addresses from the current page."""
    import re
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    emails_found = []
    seen = set()

    # Methode 1: mailto: links
    mailto_links = await self._page.evaluate("""
        () => {
            const links = document.querySelectorAll('a[href^="mailto:"]');
            return Array.from(links).map(link => ({
                email: link.href.replace('mailto:', '').split('?')[0],
                context: link.innerText || link.title || ''
            }));
        }
    """)
    for item in mailto_links:
        email = item['email'].lower().strip()
        if email and email not in seen and '@' in email:
            seen.add(email)
            emails_found.append({'email': email, 'context': item['context'], 'source': 'mailto'})

    # Methode 2: Page text
    page_text = await self._page.evaluate("() => document.body.innerText")
    for email in re.findall(email_pattern, page_text):
        if email.lower() not in seen:
            seen.add(email.lower())
            emails_found.append({'email': email.lower(), 'context': '', 'source': 'text'})

    # Methode 3: Contact-elementen
    contact_emails = await self._page.evaluate("""
        () => {
            const pattern = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/g;
            const results = [];
            const selectors = ['.contact', '#contact', '.footer', 'footer', '.email', 'address'];
            selectors.forEach(sel => {
                try {
                    document.querySelectorAll(sel).forEach(el => {
                        const matches = (el.innerText || '').match(pattern);
                        if (matches) matches.forEach(e => results.push({email: e, context: sel}));
                    });
                } catch(e) {}
            });
            return results;
        }
    """)
    for item in contact_emails:
        if item['email'].lower() not in seen:
            seen.add(item['email'].lower())
            emails_found.append({'email': item['email'].lower(), 'context': item['context'], 'source': 'contact'})

    return emails_found
```

### 2.10 Paginatekst extraheren

```python
async def extract_page_text(self, max_chars: int = 15000) -> str:
    """Extract visible text from the current page."""
    try:
        text = await self._page.evaluate("() => document.body.innerText")
        return (text or "")[:max_chars]
    except Exception:
        return ""
```

---

## 3. Hoe is de Streamlit app opgezet?

### 3.1 Pagina-structuur

Streamlit's multi-page app structuur:

```
streamlit-app/
├── app.py                    # Home/dashboard (standaard pagina)
├── config.py                 # Branding, CSS, helpers
├── data_manager.py           # Data persistentie (JSON)
├── job_manager.py            # Background jobs
├── pages/
│   ├── 1_Discovery.py        # Pagina 1
│   ├── 2_Fair_Details.py     # Pagina 2
│   └── 3_Email_Generator.py  # Pagina 3
├── .streamlit/
│   └── config.toml           # Streamlit configuratie
└── data/
    └── fairs.json             # Opgeslagen data
```

**Elke pagina begint met:**
```python
import streamlit as st
from config import CUSTOM_CSS, CIALONA_ORANGE, CIALONA_NAVY, APP_ICON

st.set_page_config(
    page_title="Pagina Naam | Cialona",
    page_icon=APP_ICON,
    layout="wide"
)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
```

**Navigatie tussen pagina's:**
```python
# Navigeer naar een andere pagina
st.switch_page("pages/1_Discovery.py")

# Data meegeven via session_state
st.session_state['selected_fair'] = fair_id
st.switch_page("pages/2_Fair_Details.py")
```

### 3.2 Streamlit configuratie

`.streamlit/config.toml`:
```toml
[theme]
primaryColor = "#F7931E"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F8FAFC"
textColor = "#1E2A5E"
font = "sans serif"

[server]
headless = true
port = 8501
enableCORS = false

[browser]
gatherUsageStats = false
```

### 3.3 Branding en CSS (config.py)

De complete `config.py` is direct herbruikbaar. Kernpunten:

```python
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
```

De `CUSTOM_CSS` variabele bevat 380+ regels CSS met:
- Google Fonts (Inter)
- Card styling (.fair-card)
- Status badges (.status-badge .status-complete/.status-partial/.status-missing)
- Document chips (.doc-chip .doc-found/.doc-missing)
- Metric cards (.metric-card)
- Button styling (Cialona oranje gradient)
- Sidebar styling (navy achtergrond, witte tekst)
- Progress bar
- Table styling
- Verborgen Streamlit branding (#MainMenu, footer)
- Custom scrollbar

**Helper functies:**
```python
def get_status_html(found: int, total: int) -> str:
    """Generate status badge HTML."""
    if found == total:
        return f'<span class="status-badge status-complete">✓ Compleet ({found}/{total})</span>'
    elif found > 0:
        return f'<span class="status-badge status-partial">⚠ Deels ({found}/{total})</span>'
    else:
        return f'<span class="status-badge status-missing">✗ Ontbreekt ({found}/{total})</span>'

def get_doc_chip_html(doc_type: str, found: bool) -> str:
    """Generate document chip HTML."""
    doc_info = DOCUMENT_TYPES.get(doc_type, {"icon": "📄", "dutch_name": doc_type})
    css_class = "doc-found" if found else "doc-missing"
    return f'<span class="doc-chip {css_class}">{doc_info["icon"]} {doc_info["dutch_name"]}</span>'
```

### 3.4 Achtergrondtaken (job_manager.py)

Streamlit herlaadt de hele pagina bij elke interactie. Om langlopende taken te draaien zonder de UI te blokkeren, worden background threads gebruikt:

```python
import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, List

@dataclass
class Job:
    job_id: str
    status: str = "pending"       # pending | running | completed | failed | cancelled
    progress: int = 0
    logs: List[str] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None
    start_time: float = 0.0
    end_time: float = 0.0
    cancel_event: Optional[threading.Event] = field(default=None, repr=False)

# Module-level singleton (gedeeld tussen alle Streamlit sessies)
_jobs: Dict[str, Job] = {}
_lock = threading.Lock()

def get_job(job_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(job_id)

def get_active_jobs() -> List[Job]:
    with _lock:
        return [j for j in _jobs.values() if j.status in ("pending", "running")]

def stop_job(job_id: str) -> bool:
    """Request cancellation."""
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.status not in ("pending", "running"):
            return False
        if job.cancel_event:
            job.cancel_event.set()
        return True

def start_job(task_params: dict, api_key: str) -> str:
    """Start a job in a background thread."""
    job_id = uuid.uuid4().hex[:8]
    job = Job(
        job_id=job_id,
        start_time=time.time(),
        cancel_event=threading.Event(),
    )
    with _lock:
        _jobs[job_id] = job

    thread = threading.Thread(
        target=_run_job_thread,
        args=(job_id, task_params, api_key),
        daemon=True,
    )
    thread.start()
    return job_id

def _run_job_thread(job_id: str, params: dict, api_key: str):
    """Execute job in background thread with own event loop."""
    job = _jobs[job_id]
    job.status = "running"

    # BELANGRIJK: Elke thread heeft zijn eigen event loop nodig
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(_run_job_async(job, params, api_key))
        job.result = result
        job.status = "completed"
    except Exception as e:
        if job.cancel_event and job.cancel_event.is_set():
            job.status = "cancelled"
        else:
            job.error = str(e)
            job.status = "failed"
    finally:
        job.end_time = time.time()
        loop.close()
```

**Belangrijk patroon: elke thread heeft zijn eigen `asyncio` event loop nodig.** Streamlit's main thread heeft al een event loop, en `asyncio.run()` werkt niet in een sub-thread. Je moet expliciet `asyncio.new_event_loop()` aanroepen.

**Cancellation:** De `cancel_event` is een `threading.Event()`. De agent checkt periodiek of deze is gezet:

```python
def _check_cancelled(self):
    if self._cancel_event and self._cancel_event.is_set():
        raise CancelledException()
```

### 3.5 Voortgangsweergave in de UI

De Discovery-pagina toont live voortgang met auto-refresh:

```python
# In de pagina-code
for job in active_jobs:
    progress = calc_progress(job)
    remaining = calc_remaining(job)

    with st.container(border=True):
        st.markdown(f"**{job.name}** · :orange[{current_phase}]")
        st.progress(min(max(progress, 0), 100))

        # Logs (uitklapbaar)
        with st.expander("Voortgang details", expanded=False):
            if job.logs:
                st.code("\n".join(job.logs[-20:]))

# AUTO-REFRESH: aan het EINDE van de pagina
if active_jobs:
    time.sleep(2)
    st.rerun()
```

**Belangrijk:** De `time.sleep(2)` + `st.rerun()` moet aan het **einde** van de pagina staan, nadat ALLE sections gerenderd zijn. Anders worden sommige elementen niet weergegeven.

**Voortgangsberekening met fases:**

```python
PHASES = [
    {"id": "scraping",    "label": "Pagina scrapen",     "pct_start": 0,  "pct_end": 60,  "est_secs": 120},
    {"id": "filtering",   "label": "Filteren",           "pct_start": 60, "pct_end": 75,  "est_secs": 5},
    {"id": "enrichment",  "label": "Verrijken",          "pct_start": 75, "pct_end": 95,  "est_secs": 60},
    {"id": "results",     "label": "Resultaten",         "pct_start": 95, "pct_end": 100, "est_secs": 2},
]

def calc_progress(job) -> int:
    """Interpolated progress percentage."""
    if job.status == "completed": return 100
    if job.status == "failed": return 0
    phase = get_phase(job.current_phase)
    elapsed = time.time() - job.phase_start_time
    ratio = min(1.0, elapsed / max(1, phase["est_secs"]))
    pct = phase["pct_start"] + ratio * (phase["pct_end"] - phase["pct_start"])
    return min(int(pct), 99)
```

### 3.6 Data opslaan en laden (data_manager.py)

Thread-safe JSON file storage met `fcntl` locks:

```python
import fcntl
import json
import threading
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_FILE = DATA_DIR / "data.json"
_file_lock = threading.Lock()

def ensure_data_dir():
    DATA_DIR.mkdir(exist_ok=True)

def load_data() -> dict:
    """Load data (thread-safe with shared lock)."""
    ensure_data_dir()
    if DATA_FILE.exists():
        with _file_lock:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)  # Shared (read) lock
                try:
                    return json.load(f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return {}

def save_item(item_id: str, item_data: dict):
    """Atomic read-modify-write (thread-safe with exclusive lock)."""
    ensure_data_dir()
    item_data['updated_at'] = datetime.now().isoformat()
    with _file_lock:
        # Read under lock
        data = {}
        if DATA_FILE.exists():
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        # Modify
        data[item_id] = item_data
        # Write under exclusive lock
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2, ensure_ascii=False)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

**Waarom twee locks?**
- `_file_lock` (threading.Lock) — beschermt tegen concurrent access binnen hetzelfde Python process (meerdere Streamlit sessies/threads)
- `fcntl.flock` — beschermt tegen concurrent access tussen processen (bijv. als Streamlit herstart terwijl een thread nog schrijft)

### 3.7 Playwright installeren bij eerste gebruik

```python
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
            st.info("Eerste keer setup: Playwright browsers installeren...")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True, text=True
                )
                return result.returncode == 0
            except Exception:
                return False
        return False
```

---

## 4. Welke lessen zijn geleerd?

### 4.1 Web search problemen

Uit de git history (commits 42a6a4b, 94a6cde, 3edce63, 32a0a1a, cc80102, c9f8a2b):

1. **DuckDuckGo HTML format veranderde** — de URL-extractie brak regelmatig. Fixes nodig voor elk format-wijziging.
2. **DuckDuckGo blocking** — DDG blokkeert scraping-achtige requests. Oplossing: Playwright gebruiken i.p.v. urllib, maar zelfs dat faalde soms.
3. **Uiteindelijk overgestapt naar Brave Search** — stabielere HTML, minder agressieve blocking. Wel rate limiting nodig.
4. **Rate limiting voor web search** — een `threading.Lock` + 12s cooldown tussen searches voor concurrent discoveries om 429 errors te voorkomen.

**Les voor Exhibitor Scraper:** Voor web search (in de verrijkings-stap) is Google via de browser de betrouwbaarste optie. Navigeer gewoon naar `google.com` en zoek daar.

### 4.2 Beurswebsite-specifieke problemen

Uit commits en code comments:

1. **Mega-menu's** (commit 36df831): CSS `:hover` werkt NIET met JavaScript `dispatchEvent(new MouseEvent('mouseenter'))`. Oplossing: CSS injection om dropdown-menus te forceren met `display: block !important`.

2. **Redirect-tracking** (commit 2cc2403): Sommige beursen redirecten naar een ander domein (bijv. `www.the-tire-cologne.com` → `www.thetire-cologne.com`). Als je het originele domein blijft gebruiken voor vergelijkingen, mis je alle links.

3. **Locale-aware scanning** (commit 2cc2403): Nederlandse sites (`.nl` TLD) verstoppen hun exposanten-pagina's onder `/standhouders` of `/standbouwers`, niet onder `/exhibitors`. De pre-scan moet locale-specifieke paden prioriteren.

4. **Salesforce portals** (commits 945796e, 2cb3def): Veel beurzen gebruiken Salesforce communities (`*.my.site.com`) voor hun exposanten-portals. Deze URL's bevatten vaak alle documenten, maar:
   - Veel Salesforce URL's zijn infrastructuur (login, SAML, CDN) — filter deze eruit
   - FileDownload URL's zijn directe PDF's, niet portal-pagina's
   - Het portal-home is afleidbaar: `/mwcoem/servlet/servlet.FileDownload?file=X` → `/mwcoem/s/Home`

5. **Paginering variaties:** Beurswebsites gebruiken diverse paginerings-methoden:
   - Standaard next/previous buttons
   - A-Z letter tabs
   - Lazy loading (scroll-to-load)
   - "Load more" buttons
   - Genummerde pagina's (?page=2)
   - AJAX requests (pagina verandert niet, data wordt bijgeladen)

6. **Bot-bescherming:** Sommige beurswebsites gebruiken:
   - Cloudflare protection (CAPTCHA)
   - Rate limiting per IP
   - Cookie-consent overlays die de pagina blokkeren
   - Login-walls voor exposantenportals

### 4.3 Playwright instellingen voor beurswebsites

Uit de werkende code:

```python
# Viewport: 1024x768 — de standaard voor Computer Use
self._browser = await self._playwright.chromium.launch(
    headless=True,
    args=['--no-sandbox', '--disable-setuid-sandbox']
)
self._context = await self._browser.new_context(
    viewport={'width': 1024, 'height': 768},
    accept_downloads=True
)
```

**Wat ontbreekt (en je misschien wilt toevoegen):**
- `user_agent` — sommige sites blokkeren de standaard Playwright user agent
- `locale` — kan helpen bij sites die content per taal serveren
- `geolocation` — sommige sites serveren andere content per regio
- `ignore_https_errors=True` — nuttig voor sites met verlopen certificaten

### 4.4 Timing en wachttijden

Uit de code:

| Actie | Wachttijd | Reden |
|-------|-----------|-------|
| Na navigatie (goto) | 1000ms | JavaScript uitvoeren |
| Na klik | 500ms | Pagina-update afwachten |
| Na scroll | 300ms | Lazy loading triggeren |
| Na accordion-expansie | 500ms | Content laden |
| Na mega-menu CSS injection | 200ms | CSS toepassen |
| Tussen pre-scan pagina's | 500ms | Rate limiting |

### 4.5 Empty user messages bug

Commit 5e821a9: De Anthropic API crasht op lege user messages. Dit kan gebeuren als:
- Alle tool_use blocks een error geven en geen results produceren
- De fallback message per ongeluk leeg is

Oplossing: altijd een non-empty fallback:
```python
if tool_results:
    messages.append({"role": "user", "content": tool_results})
else:
    messages.append({"role": "user", "content": [{"type": "text", "text": "Ga verder."}]})
```

### 4.6 Streamlit UI problemen

1. **st.progress en st.expander accepteren geen `key` parameter** in oudere Streamlit versies (commits 9a59692, 022324d). Gebruik `st.container(key=...)` als wrapper.

2. **Auto-refresh verbergt content** (commit fcd8af6): Als `st.rerun()` te vroeg wordt aangeroepen, worden sommige HTML-elementen niet gerenderd. Oplossing: `st.rerun()` altijd als LAATSTE statement.

3. **Session state na pagina-refresh** (commit 5fe7187): Na een pagina-refresh zijn de `my_job_ids` in session_state leeg. Oplossing: ook actieve jobs ophalen die niet in `my_job_ids` staan.

4. **File uploader rerun loop** (commit 0f0afb7): `st.file_uploader` triggert een rerun bij elke upload. Als je daaronder een `st.rerun()` hebt, krijg je een infinite loop. Oplossing: check of het bestand echt nieuw is voordat je `st.rerun()` aanroept.

---

## 5. Welke code-patronen zijn het waard om over te nemen?

### 5.1 Cancellation pattern

Gecontroleerde annulering via `threading.Event`:

```python
class Agent:
    def __init__(self, cancel_event=None):
        self._cancel_event = cancel_event

    def _check_cancelled(self):
        """Roep dit aan in elke iteratie van de agent-loop."""
        if self._cancel_event and self._cancel_event.is_set():
            raise CancelledException()
```

In de job_manager:
```python
job.cancel_event = threading.Event()

# In de UI:
if st.button("Stop"):
    job.cancel_event.set()
```

### 5.2 Logging pattern

Dual-purpose logging: print naar console EN collect in lijst voor UI:

```python
class Agent:
    def __init__(self, on_status=None):
        self.on_status = on_status or (lambda x: None)
        self._log_history = []

    def _log(self, message: str):
        timestamp = time.strftime('%H:%M:%S')
        formatted = f"[{timestamp}] {message}"
        print(formatted)
        self.on_status(message)
        self._log_history.append(formatted)
```

### 5.3 ID generatie

```python
import re

def create_id(name: str) -> str:
    """Create a URL-safe ID from a name."""
    clean = re.sub(r'[^a-zA-Z0-9\s-]', '', name.lower())
    return re.sub(r'\s+', '-', clean.strip())
```

### 5.4 Error handling in de agent-loop

De agent vangt fouten op per tool-call, niet per iteratie. Als één tool faalt, gaat de loop door:

```python
for tool_use in tool_use_blocks:
    try:
        result = await execute_tool(tool_use)
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": tool_use.id,
            "content": result,
        })
    except Exception as e:
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": tool_use.id,
            "content": [{"type": "text", "text": f"Error: {e}"}],
            "is_error": True,
        })
```

### 5.5 Custom tool definitie

Om een custom tool toe te voegen aan de Computer Use API:

```python
tools = [
    # Computer Use tool (verplicht voor screenshots/interactie)
    {
        "type": "computer_20250124",
        "name": "computer",
        "display_width_px": 1024,
        "display_height_px": 768,
        "display_number": 1,
    },
    # Custom tool: gestructureerde output
    {
        "name": "report_exhibitors",
        "description": "Report a batch of exhibitors found on the current page. Call this after reading each page of the exhibitor list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "exhibitors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "company_name": {"type": "string"},
                            "country": {"type": "string"},
                            "stand_number": {"type": "string"},
                            "website": {"type": "string"},
                            "email": {"type": "string"},
                            "phone": {"type": "string"},
                            "stand_size": {"type": "string"}
                        },
                        "required": ["company_name"]
                    }
                },
                "page_info": {"type": "string"},
                "has_more_pages": {"type": "boolean"}
            },
            "required": ["exhibitors"]
        }
    },
]
```

De tool-output wordt gestructureerd als JSON door Claude, waardoor je geen free-text parsing nodig hebt. Dit is VEEL betrouwbaarder dan Claude vragen om JSON in een tekst-blok te zetten.

---

## 6. Dependencies en environment

### 6.1 Python packages (requirements.txt)

```
streamlit>=1.32.0
anthropic>=0.40.0
playwright>=1.40.0
pandas>=2.0.0
openpyxl                # Voor Excel export (nieuw voor Exhibitor Scraper)
```

**Optioneel:**
```
pypdf>=4.0.0            # Als je PDF's wilt parsen
plotly>=5.18.0           # Als je grafieken wilt
requests>=2.31.0         # Als je HTTP calls wilt buiten Playwright
```

### 6.2 Systeem packages (packages.txt)

Nodig voor Playwright/Chromium op Linux:

```
libnspr4
libnss3
libnss3-tools
libatk1.0-0
libatk-bridge2.0-0
libcups2
libdrm2
libxkbcommon0
libxcomposite1
libxdamage1
libxfixes3
libxrandr2
libgbm1
libasound2
libpango-1.0-0
libpangocairo-1.0-0
libgtk-3-0
libx11-xcb1
libxcb-dri3-0
libxshmfence1
libglu1-mesa
```

### 6.3 Environment variables

| Variable | Beschrijving | Verplicht |
|----------|-------------|-----------|
| `ANTHROPIC_API_KEY` | API key voor Claude | Ja |

In Streamlit Cloud: stel in via Settings > Secrets:
```
ANTHROPIC_API_KEY = "sk-ant-..."
```

In code ophalen:
```python
api_key = os.environ.get('ANTHROPIC_API_KEY')
if not api_key:
    try:
        api_key = st.secrets.get('ANTHROPIC_API_KEY')
    except Exception:
        pass
```

### 6.4 Streamlit Cloud deployment

De app draait op Streamlit Cloud. Relevante bestanden:
- `requirements.txt` — Python packages
- `packages.txt` — Systeem packages (apt-get)
- `.streamlit/config.toml` — Streamlit configuratie

`.streamlit/postBuild` (optioneel, voor Playwright installatie):
```bash
#!/bin/bash
python -m playwright install chromium
```

---

## Samenvatting: Wat direct te hergebruiken

| Component | Actie | Bron |
|-----------|-------|------|
| Branding/CSS | Kopieer `config.py` volledig | `streamlit-app/config.py` |
| Streamlit config | Kopieer `.streamlit/config.toml` | `streamlit-app/.streamlit/config.toml` |
| Browser controller | Kopieer en pas aan | `streamlit-app/discovery/browser_controller.py` |
| Data persistence | Kopieer patroon | `streamlit-app/data_manager.py` |
| Job manager | Kopieer patroon | `streamlit-app/job_manager.py` |
| Agent loop | Schrijf opnieuw met dit document als referentie | `streamlit-app/discovery/claude_agent.py` |
| System packages | Kopieer volledig | `streamlit-app/packages.txt` |
| Requirements | Pas aan voor nieuwe project | `streamlit-app/requirements.txt` |
