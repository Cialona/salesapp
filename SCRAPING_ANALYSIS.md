# Exhibitor Scraper: Codebase-analyse & Architectuur-advies

Gebaseerd op analyse van de salesapp-codebase (3900+ regels `claude_agent.py`, 950+ regels `browser_controller.py`, 80+ commits, 100+ beurssites).

---

## 1. Site-patronen die we zijn tegengekomen

### Bot-bescherming

| Type | Frequentie | Voorbeeld | Symptoom |
|------|-----------|-----------|----------|
| **Cloudflare** | ~30% van sites | Messe Frankfurt, RAI Amsterdam | `requests` → HTTP 403/503 met challenge-pagina. Playwright werkt meestal wel. |
| **Cookie-consent overlays** | ~70% van sites | Bijna alle EU-beurzen | Overlay blokkeert klikken. Moet weggeklikt of geaccepteerd worden. |
| **Rate limiting** | ~20% van sites | Salesforce portals, Brave Search | HTTP 429 na 5-6 snelle requests. |
| **JavaScript-only rendering** | ~40% van sites | Salesforce portals (`*.my.site.com`), React/Next.js sites | `requests.get()` geeft lege body of skeleton HTML. |
| **CAPTCHA** | ~5% van sites | DuckDuckGo (bij scraping), sommige registratie-portals | `requests` en soms ook Playwright geblokkeerd. |
| **Login-walls** | ~15% van sites | OEM portals, sommige exposantenlijsten | Content niet publiek toegankelijk. DNS valideert, maar pagina toont login-formulier. |

### Paginering-varianten

| Type | Frequentie | Voorbeeld |
|------|-----------|-----------|
| **?page=N** query parameter | ~35% | `exhibitors.bauma.de?page=2`, `?pagenumber=3` |
| **A-Z letter tabs** | ~20% | Exposantenlijsten gefilterd op eerste letter |
| **"Load more" button** | ~15% | Knop onderaan de lijst, laadt via AJAX |
| **Infinite scroll** | ~10% | Scroll-to-load, content bijgeladen via JavaScript |
| **Alles-op-één-pagina** | ~15% | Kleine beurzen, geen paginering nodig |
| **AJAX/XHR** | ~5% | Lijst update zonder page reload, URL verandert niet |

### Content-delivery patronen

| Type | Beschrijving |
|------|-------------|
| **Static HTML** | Exposantenlijst direct in de HTML. `requests.get()` + BeautifulSoup werkt. |
| **Server-rendered met JS-enhancements** | HTML is compleet, maar filtering/paginering via JS. Playwright veiliger. |
| **Single Page App (SPA)** | React/Vue/Angular. HTML is een lege `<div id="root">`. Alleen Playwright werkt. |
| **Salesforce Community (OEM)** | `*.my.site.com`. SPA met 3-6 seconden laadtijd. Extra wachttijd nodig. |
| **iFrame-embedded** | Exposantenlijst in iframe van extern platform (ExpoCad, ExpoFP, MapYourShow). |
| **PDF-only** | Exposantenlijst als PDF, geen webpagina. Moet gedownload en geparsed worden. |

### Externe platformen voor exposantenlijsten

Uit de code (`browser_controller.py:148-228` en `claude_agent.py:984-999`):

```
my.site.com           → Salesforce Community (meest voorkomend)
force.com             → Salesforce direct
cvent.com             → Cvent event platform
a2zinc.net            → A2Z Events
expocad.*             → ExpoCad (interactieve floorplans)
expofp.*              → ExpoFP (interactieve floorplans)
mapyourshow.com       → Map Your Show
map-dynamics.*        → Map Dynamics
swapcard.com          → Swapcard
grip.events           → Grip
smallworldlabs.com    → Small World Labs
n200.com              → Nth Degree events
asp.events            → ASP Events CDN
```

---

## 2. Welke oplossingen werkten?

### 2.1 Brave Search als web search (niet DDG, niet Bing)

**Probleem:** DuckDuckGo verandert constant hun HTML format (commits 42a6a4b, 94a6cde, 3edce63) en blokkeert headless browsers met CAPTCHAs. Bing rendert alles via JavaScript.

**Oplossing die werkt:** Brave Search via plain HTTP (`urllib.request`), geen Playwright nodig.

```python
import urllib.request, urllib.parse, ssl, re

def brave_search(query: str) -> list[str]:
    """Brave Search via plain HTTP. Returns list of result URLs."""
    ssl_ctx = ssl.create_default_context()
    encoded = urllib.parse.quote_plus(query)
    url = f"https://search.brave.com/search?q={encoded}"

    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
    })

    resp = urllib.request.urlopen(req, timeout=15, context=ssl_ctx)
    html = resp.read().decode('utf-8', errors='ignore')

    # Parse: elke <div class="snippet ..."> bevat één zoekresultaat
    snippet_blocks = html.split('class="snippet ')
    result_urls = []
    seen = set()

    for block in snippet_blocks[1:]:
        hrefs = re.findall(
            r'href="(https?://(?!search\.brave|brave\.com|cdn\.search\.brave)[^"]+)"',
            block[:3000]
        )
        for href in hrefs:
            clean = href.split('#')[0].rstrip('/')
            if clean not in seen:
                seen.add(clean)
                result_urls.append(href)
                break  # Eerste URL per snippet = het resultaat

    return result_urls
```

**Rate limiting voor Brave:**
- Max 3 queries per sessie
- 1-1.5 seconde tussen queries
- `threading.Lock` om concurrent discoveries te serialiseren
- 12 seconden cooldown tussen sessies van verschillende discoveries
- Retry bij 429: wacht 3s, 7s, 11s

### 2.2 Mega-menus zichtbaar maken via CSS injection

**Probleem:** `dispatchEvent(new MouseEvent('mouseenter'))` triggert NIET de CSS `:hover` pseudo-class. Dropdown-menus blijven verborgen.

**Oplossing:** CSS injection die alle submenu's forceert.

```python
# STAP 1: JavaScript events (triggert event listeners, maar niet CSS :hover)
await page.evaluate('''() => {
    document.querySelectorAll('nav > ul > li, header nav li.dropdown').forEach(el => {
        el.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
        el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
    });
}''')
await asyncio.sleep(0.3)

# STAP 2: CSS force-reveal (de echte fix)
await page.evaluate('''() => {
    const style = document.createElement("style");
    style.id = "__nav_reveal__";
    style.textContent = `
        nav ul ul, nav li > ul, nav li > div,
        .dropdown-menu, .sub-menu, .submenu, .mega-menu,
        [class*="dropdown"] > ul, [class*="dropdown"] > div,
        li.has-children > ul, li.menu-item-has-children > ul {
            display: block !important;
            visibility: visible !important;
            opacity: 1 !important;
            max-height: none !important;
            pointer-events: auto !important;
        }
    `;
    document.head.appendChild(style);
}''')
await asyncio.sleep(0.2)

# STAP 3: Extracteer links uit nu-zichtbare menu's
links = await page.evaluate('''() => { /* ... extract nav links ... */ }''')

# STAP 4: Cleanup CSS
await page.evaluate('() => document.getElementById("__nav_reveal__")?.remove()')
```

### 2.3 Salesforce portal filtering

**Probleem:** Salesforce URL's zijn overal op beurswebsites. 90% is infrastructuur (login, SAML, CDN). Slechts ~10% is nuttige content.

**Oplossing:** Expliciete whitelist/blacklist (`browser_controller.py:148-222`):

```python
# Block deze Salesforce URL's:
SALESFORCE_INFRA = [
    'login.salesforce.com', '.my.salesforce.com',     # Admin console
    '/saml/', '/login/', '/jslibrary/', '/icons/',     # Auth/resources
    '/oemlogin', '/secur/logout.jsp',                   # OEM platform
    '/exhibitorstanddetailpage',                        # Requires auth
]

# WEL doorlaten:
# - *.my.site.com/{community}/s/Home  → Portal home
# - servlet/servlet.FileDownload       → Direct PDF download

# FileDownload URL → afleiden van portal home:
# https://gsma.my.site.com/mwcoem/servlet/servlet.FileDownload?file=X
# → https://gsma.my.site.com/mwcoem/s/Home
```

### 2.4 Redirect-tracking

**Probleem:** Sommige beurzen redirecten naar een ander domein. Als je het originele domein blijft gebruiken, worden alle links als "extern" geclassificeerd.

**Oplossing:** Na de eerste navigatie checken of het domein veranderd is.

```python
# Na goto naar base_url:
actual_url = page.url
actual_netloc = urlparse(actual_url).netloc
if actual_netloc.lower() != original_netloc.lower():
    print(f"Redirect: {original_netloc} → {actual_netloc}")
    base_netloc = actual_netloc
    base_domain = f"{urlparse(actual_url).scheme}://{actual_netloc}"
```

### 2.5 SPA wachttijden

**Probleem:** Salesforce portals laden in 3-6 seconden. Standaard Playwright `wait_until='domcontentloaded'` is te snel — pagina toont skeleton.

**Oplossing uit de code (`claude_agent.py:1622-1634`):**

```python
await browser.goto(portal_url)
await asyncio.sleep(3)  # Standaard SPA wachttijd

# Check of content daadwerkelijk geladen is
text = await browser.extract_page_text()
if not text or len(text) < 200:
    # Nog steeds laden → extra wachttijd
    await asyncio.sleep(3)
    text = await browser.extract_page_text()
```

### 2.6 Navigatie met domcontentloaded + retry

**Probleem:** `wait_until='networkidle'` timeouts op 50%+ van de sites door tracking-scripts die nooit klaar zijn.

**Oplossing (`browser_controller.py:403-420`):**

```python
async def goto(self, url: str, timeout: int = 30000):
    last_error = None
    timeouts = [timeout, timeout * 2, timeout * 3]  # 30s, 60s, 90s
    for attempt, t in enumerate(timeouts, 1):
        try:
            await self._page.goto(url, wait_until='domcontentloaded', timeout=t)
            await self._page.wait_for_timeout(1000)  # Extra 1s voor JS
            return
        except Exception as e:
            last_error = e
            if attempt < len(timeouts):
                await self._page.wait_for_timeout(2000)
    raise last_error
```

---

## 3. Architectuur-advies voor de 3-laags aanpak

### Huidige architectuur

```
URL-resolutie:
  Phase 1:   Text-API (website URL + exhibitor URL) → Brave/DDG + Text-API judge
  Phase 1.5: HTTP HEAD validatie + 12 pad-variaties + Claude retry
  Phase 1.6: Nav-crawl (raw HTML regex → Playwright DOM fallback → Text-API kiest link)

Scraping:
  Layer 1: urllib fetch + text-API parse HTML       (goedkoop)
  Layer 2: Playwright render + text-API parse       (medium)
  Layer 3: Computer Use agent                       (duur, laatste redmiddel)

Paginering: programmatisch waar mogelijk (_detect_page_urls: ?page=N, /page/N, ?offset=N)
```

### Mijn advies op basis van 100+ tests

De fundamentele architectuur is goed. Hieronder concrete verbeterpunten per laag.

**Advies 1: Phase 1.5 — bot-detectie in het HTTP HEAD response verbeteren**

HTTP HEAD geeft een 200 OK terug op Cloudflare-beschermde sites, maar de body (bij GET) bevat alleen een challenge-pagina. Het HEAD-resultaat is misleidend. Mijn advies: als HEAD slaagt, doe alsnog een GET en controleer de body:

```python
import requests

def try_requests_get(url: str) -> tuple[bool, str]:
    """Probeer requests.get(). Return (success, html)."""
    try:
        resp = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36',
        })

        # Status check
        if resp.status_code != 200:
            return False, ""

        html = resp.text

        # Bot-bescherming detectie
        bot_indicators = [
            'cf-browser-verification',     # Cloudflare
            'challenge-platform',           # Cloudflare
            'Just a moment...',             # Cloudflare waiting page
            'Checking your browser',        # Generic bot check
            'Enable JavaScript and cookies', # JS-required page
            '<noscript>',                    # Alleen als de body ALLEEN noscript bevat
        ]

        # Als body < 5000 chars EN bot-indicator → geblokkeerd
        if len(html) < 5000 and any(ind in html for ind in bot_indicators):
            return False, ""

        # Als body < 500 chars → waarschijnlijk skeleton/redirect
        if len(html) < 500:
            return False, ""

        return True, html

    except Exception:
        return False, ""
```

**Advies 2: Paginering-detectie uitbreiden voorbij `_detect_page_urls`**

`_detect_page_urls` dekt `?page=N`, `/page/N`, `?offset=N`. Maar er zijn meer patronen die programmatisch opgelost kunnen worden ZONDER Computer Use ($0.03-0.05 per actie). Detecteer het volledige type paginering:

```python
async def detect_pagination_type(page) -> str:
    """Detecteer welk type paginering de pagina gebruikt."""
    html = await page.content()
    url = page.url

    # Type 1: ?page=N (of ?pagenumber=N, ?p=N)
    pagination_params = re.findall(
        r'[?&](page|pagenumber|p|offset|start)=(\d+)',
        html, re.IGNORECASE
    )
    if pagination_params:
        return "query_param"

    # Type 2: Next/Previous buttons
    next_indicators = await page.evaluate('''() => {
        const selectors = [
            'a[rel="next"]', '[class*="next"]', '[aria-label*="next"]',
            '[class*="pagination"] a:last-child',
            'button:has-text("Next")', 'button:has-text("Volgende")',
            'button:has-text(">")', 'a:has-text(">")',
        ];
        for (const sel of selectors) {
            if (document.querySelector(sel)) return sel;
        }
        return null;
    }''')
    if next_indicators:
        return "next_button"

    # Type 3: A-Z tabs
    az_tabs = await page.evaluate('''() => {
        const links = document.querySelectorAll('a, button');
        let count = 0;
        for (const el of links) {
            const text = el.textContent.trim();
            if (text.length === 1 && /^[A-Z]$/.test(text)) count++;
        }
        return count >= 10;  // Minstens 10 letters = A-Z tabs
    }''')
    if az_tabs:
        return "az_tabs"

    # Type 4: Load more button
    load_more = await page.evaluate('''() => {
        const selectors = [
            'button:has-text("Load more")', 'button:has-text("Meer laden")',
            'button:has-text("Show more")', 'button:has-text("Toon meer")',
            '[class*="load-more"]', '[class*="loadmore"]',
        ];
        for (const sel of selectors) {
            if (document.querySelector(sel)) return sel;
        }
        return null;
    }''')
    if load_more:
        return "load_more"

    # Type 5: Infinite scroll (check of er een scroll-sentinel is)
    has_scroll_trigger = await page.evaluate('''() => {
        return !!document.querySelector('[class*="infinite"], [data-infinite], [class*="lazy-load"]');
    }''')
    if has_scroll_trigger:
        return "infinite_scroll"

    return "single_page"
```

**Advies 3: Uitgebreide stappenvolgorde met paginering geïntegreerd**

De huidige architectuur is goed, maar de paginering kan op elke laag programmatisch afgehandeld worden. Hier de volledige flow:

```
URL-RESOLUTIE (jullie huidige Phase 1 / 1.5 / 1.6 — dit is goed)

SCRAPING:
  Layer 1: urllib fetch + text-API parse
    - urllib.request.urlopen() met bot-detectie (zie Advies 1)
    - Als succes: text-API parse de HTML voor exposanten
    - Paginering: _detect_page_urls + A-Z tabs herkenning
    - Loop programmatisch door alle pagina's

  Layer 2: Playwright render + text-API parse (als Layer 1 faalt)
    - Playwright render pagina
    - text-API parse de gerenderde HTML
    - Paginering: _detect_page_urls + A-Z tabs + load-more + infinite scroll
    - Playwright navigeert/klikt/scrollt per pagina

  Layer 3: Computer Use (ALLEEN als structuur onherkenbaar is)
    - Agent ziet screenshot, begrijpt layout
    - Handelt exotische UI's af (drag-to-explore floorplans, custom widgets)
    - Max 50 acties
```

**Advies 4: HTML-structuur analyse VOOR text-API**

Voordat je de text-API aanroept om HTML te parsen, kun je vaak programmatisch de structuur herkennen. Dit bespaart een API-call als de HTML een herkenbaar patroon heeft (tabel of herhalende divs):

```python
from bs4 import BeautifulSoup

def extract_exhibitors_from_html(html: str) -> list[dict] | None:
    """Probeer exposanten te extraheren zonder LLM.
    Return None als de structuur niet herkend wordt.
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Patroon 1: Tabel met exposanten
    tables = soup.find_all('table')
    for table in tables:
        rows = table.find_all('tr')
        if len(rows) > 5:  # Minstens 5 rijen
            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th', 'td'])]
            if any('company' in h or 'exhibitor' in h or 'name' in h for h in headers):
                # Tabel met bedrijfsnamen gevonden
                return _parse_table(rows, headers)

    # Patroon 2: Herhalende div/li structuur
    # Zoek naar het langste herhalende patroon van elementen met dezelfde class
    candidates = {}
    for el in soup.find_all(['div', 'li', 'article']):
        classes = ' '.join(el.get('class', []))
        if classes:
            candidates.setdefault(classes, []).append(el)

    # Filter: minstens 10 elementen met dezelfde class
    for class_name, elements in sorted(candidates.items(), key=lambda x: -len(x[1])):
        if len(elements) >= 10:
            # Check of elk element een bedrijfsnaam-achtig patroon heeft
            texts = [el.get_text(strip=True)[:100] for el in elements]
            if all(len(t) > 2 for t in texts):
                return _parse_repeating_elements(elements)

    return None  # Structuur niet herkend → fallback naar text-API
```

---

## 4. HTTP validatie-logica

### Het probleem

`requests.get()` wordt geblokkeerd door Cloudflare maar Playwright niet. Hoe valideer je of een URL werkt?

### De oplossing uit de salesapp (`claude_agent.py:307-381`)

De salesapp valideert URLs via DNS + HTTP HEAD. Maar dat is niet genoeg:

```python
import socket
import urllib.request

async def validate_url(url: str) -> dict:
    """Valideer of een URL bereikbaar is. Multi-layered check."""
    result = {'url': url, 'valid': False, 'method': None, 'needs_playwright': False}

    # Stap 1: DNS check (snel, elimineert fake URL's)
    hostname = urlparse(url).hostname
    try:
        socket.gethostbyname(hostname)
    except (socket.gaierror, socket.herror):
        result['error'] = 'dns_failed'
        return result

    # Stap 2: HTTP HEAD via urllib (snel, geen full download)
    try:
        req = urllib.request.Request(url, method='HEAD', headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36',
        })
        resp = urllib.request.urlopen(req, timeout=10)
        if resp.status < 400:
            result['valid'] = True
            result['method'] = 'head'
            return result
    except urllib.error.HTTPError as e:
        if e.code == 403:
            # 403 kan Cloudflare zijn → probeer Playwright
            result['needs_playwright'] = True
        elif e.code == 405:
            # HEAD niet toegestaan → probeer GET
            pass
        else:
            result['error'] = f'http_{e.code}'
            return result
    except Exception:
        result['needs_playwright'] = True

    # Stap 3: HTTP GET via requests (volledige pagina)
    if not result['valid'] and not result['needs_playwright']:
        try:
            import requests as req_lib
            resp = req_lib.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                              'AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36',
            })
            if resp.status_code == 200:
                html = resp.text
                # Check voor bot-bescherming
                if len(html) < 5000 and any(ind in html for ind in [
                    'cf-browser-verification', 'challenge-platform',
                    'Just a moment', 'Checking your browser'
                ]):
                    result['needs_playwright'] = True
                else:
                    result['valid'] = True
                    result['method'] = 'requests'
            else:
                result['needs_playwright'] = True
        except Exception:
            result['needs_playwright'] = True

    # Stap 4: Playwright als fallback (alleen als nodig)
    if result['needs_playwright']:
        try:
            browser = BrowserController(800, 600)
            await browser.launch()
            await browser.goto(url)
            state = await browser.get_state()
            text = await browser.extract_page_text(max_chars=500)
            await browser.close()

            if text and len(text) > 50:
                result['valid'] = True
                result['method'] = 'playwright'
            else:
                result['error'] = 'empty_page'
        except Exception as e:
            result['error'] = f'playwright_failed: {e}'

    return result
```

---

## 5. Paginering per type: de beste aanpak

### Type 1: ?page=N (query parameter)

**Aanpak:** Programmatische loop. Goedkoopst en snelst.

```python
async def scrape_paginated_query(base_url: str, page_param: str = 'page') -> list:
    """Loop door ?page=1, ?page=2, etc. tot er geen nieuwe exposanten meer zijn."""
    all_exhibitors = []
    seen_names = set()

    for page_num in range(1, 200):  # Hard cap
        sep = '&' if '?' in base_url else '?'
        url = f"{base_url}{sep}{page_param}={page_num}"

        # Probeer requests eerst, fallback naar Playwright
        success, html = try_requests_get(url)
        if not success:
            # Playwright fallback
            await browser.goto(url)
            html = await browser.get_page_content()

        # Parse exposanten uit HTML (via text-API of BeautifulSoup)
        new_exhibitors = parse_exhibitors(html)

        # Stop als geen nieuwe exposanten
        new_names = {e['company_name'] for e in new_exhibitors}
        if not new_names - seen_names:
            break

        seen_names.update(new_names)
        all_exhibitors.extend(new_exhibitors)

        await asyncio.sleep(0.5)  # Rate limiting

    return all_exhibitors
```

### Type 2: A-Z letter tabs

**Aanpak:** Loop per letter, gebruik Playwright voor klikken.

```python
async def scrape_az_tabs(page) -> list:
    """Klik door A-Z tabs en scrape per letter."""
    all_exhibitors = []

    # Vind alle letter-tabs
    letters = await page.evaluate('''() => {
        const tabs = [];
        document.querySelectorAll('a, button').forEach(el => {
            const text = el.textContent.trim();
            if (text.length === 1 && /^[A-Z0-9]$/.test(text)) {
                tabs.push({text, selector: el.tagName + ':has-text("' + text + '")'});
            }
        });
        return tabs;
    }''')

    for letter_info in letters:
        # Klik op de letter tab
        tab = await page.query_selector(f'text="{letter_info["text"]}"')
        if tab:
            await tab.click()
            await page.wait_for_timeout(1500)  # Wacht op content update

            # Parse exposanten voor deze letter
            html = await page.content()
            exhibitors = parse_exhibitors(html)
            all_exhibitors.extend(exhibitors)

    return all_exhibitors
```

### Type 3: "Load more" button

**Aanpak:** Playwright klik-loop tot de knop verdwijnt.

```python
async def scrape_load_more(page) -> list:
    """Klik op 'load more' tot alle content geladen is."""
    max_clicks = 100

    for i in range(max_clicks):
        # Zoek de "load more" knop
        button = await page.query_selector(
            'button:has-text("Load more"), button:has-text("Meer laden"), '
            'button:has-text("Show more"), [class*="load-more"]'
        )

        if not button:
            break

        # Check of knop zichtbaar en klikbaar is
        is_visible = await button.is_visible()
        if not is_visible:
            break

        await button.click()
        await page.wait_for_timeout(2000)  # Wacht op AJAX response

    # Alle content is nu geladen → parse de volledige pagina
    html = await page.content()
    return parse_exhibitors(html)
```

### Type 4: Infinite scroll

**Aanpak:** Scroll naar beneden tot de content niet meer groeit.

```python
async def scrape_infinite_scroll(page) -> list:
    """Scroll naar beneden tot alle content geladen is."""
    max_scrolls = 100
    previous_height = 0
    no_change_count = 0

    for i in range(max_scrolls):
        # Scroll naar beneden
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await page.wait_for_timeout(2000)  # Wacht op lazy loading

        # Check of de pagina gegroeid is
        current_height = await page.evaluate('document.body.scrollHeight')

        if current_height == previous_height:
            no_change_count += 1
            if no_change_count >= 3:  # 3x geen verandering → klaar
                break
        else:
            no_change_count = 0

        previous_height = current_height

    html = await page.content()
    return parse_exhibitors(html)
```

### Type 5: AJAX (pagina verandert niet, data wordt bijgeladen)

**Aanpak:** Intercepteer XHR requests om de API-endpoint te vinden.

```python
async def discover_api_endpoint(page) -> str | None:
    """Monitor netwerk-requests om de API endpoint te vinden."""
    api_urls = []

    async def handle_response(response):
        url = response.url
        if any(kw in url.lower() for kw in ['exhibitor', 'company', 'list', 'search', 'api']):
            content_type = response.headers.get('content-type', '')
            if 'json' in content_type or 'xml' in content_type:
                api_urls.append(url)

    page.on('response', handle_response)

    # Trigger een paginering-actie
    next_btn = await page.query_selector('[class*="next"], [aria-label*="next"]')
    if next_btn:
        await next_btn.click()
        await page.wait_for_timeout(3000)

    page.remove_listener('response', handle_response)

    return api_urls[0] if api_urls else None
```

---

## 6. Top-5 hardste edge cases

### Edge case 1: Salesforce OEM portals met dynamische navigatie

**Beurs:** MWC Barcelona, Provada Amsterdam
**Probleem:** Het portal is een Salesforce SPA (`*.my.site.com`). De navigatie wordt client-side gerenderd. Standaard link-extractie vindt 0 links. Content laadt pas na 3-6 seconden.
**Oplossing uit de code (`claude_agent.py:1594-1892`):**
1. 3s initiële wachttijd na navigatie
2. Als content < 200 chars: nog 3s extra wachten
3. Extract navigatie-links via Playwright
4. Per portal max 12 sub-pagina's scannen
5. Schedule-URL's proben via bekende slug-patronen (`/s/build-up-dismantling-schedule`, `/s/deadline`, etc.)

### Edge case 2: Redirect naar ander domein

**Beurs:** The Tire Cologne (`www.the-tire-cologne.com` → `www.thetire-cologne.com`)
**Probleem:** Alle interne links zijn op het nieuwe domein. De pre-scan filterde ze als "extern" en volgde ze niet.
**Oplossing (commit 2cc2403):** Na eerste navigatie het werkelijke domein detecteren en alle vergelijkingen updaten.

### Edge case 3: Nederlandse beurssites met lokale URL-paden

**Beurs:** Greentech, Building Holland, PROVADA
**Probleem:** De pre-scan probeerde 20 URL's in volgorde, maar `/standhouders` en `/standbouwers` stonden op positie 80+ en werden nooit bereikt.
**Oplossing (commit 2cc2403):** Locale-aware reordering — als TLD `.nl` is, schuif Nederlandse paden naar positie 2-N:

```python
tld = base_netloc.split('.')[-1].lower()
locale_paths = {
    'nl': ['/standhouders', '/standbouwers', '/nl/exposanten', '/nl/deelnemers'],
    'de': ['/de/aussteller', '/aussteller', '/de/downloads'],
    'it': ['/it/espositori', '/espositori', '/it/partecipare'],
}
if tld in locale_paths:
    # Verplaats matching paden naar begin van scan-queue
    matching = [u for u in urls if any(p in u for p in locale_paths[tld])]
    non_matching = [u for u in urls if u not in matching]
    urls = [urls[0]] + matching + non_matching  # Homepage + locale + rest
```

### Edge case 4: Externe floorplan-links in navigatie

**Beurs:** Greentech (rai-productie.rai.nl)
**Probleem:** De navigatie-link "Floor plan" wees naar een extern domein (`rai-productie.rai.nl`). De pre-scan volgde alleen interne links.
**Oplossing (commits 897a8a3, 36df831):** Navigatie-links die naar een extern domein wijzen maar waarvan de link-TEXT een document-keyword bevat, WEL volgen:

```python
for nav_link in nav_links:
    nav_host = urlparse(nav_link.url).netloc.lower()
    if nav_host != base_netloc:
        # Extern — maar check of link-tekst een document-keyword bevat
        link_text = (nav_link.text or '').lower()
        if any(kw in link_text for kw in ['floor', 'plan', 'map', 'layout', 'technical']):
            pages_to_scan.append(nav_link.url)
```

### Edge case 5: DuckDuckGo URL-encoding breakage

**Beurs:** Alle beurzen (generiek probleem)
**Probleem:** DuckDuckGo veranderde 4x hun HTML format in 3 maanden:
1. URLs in `href` attributen (normaal)
2. URLs in `uddg=` query parameter (encoded)
3. URLs in `uddg=` dubbel-encoded
4. URLs achter JavaScript redirect

Elke keer brak de URL-extractie (commits 42a6a4b, 94a6cde, 3edce63, 32a0a1a).

**Uiteindelijke oplossing:** Overstap naar Brave Search (commit cc80102). Brave's HTML is server-rendered en stabiel:

```python
# Brave: stabiel HTML format
snippet_blocks = html.split('class="snippet ')
for block in snippet_blocks[1:]:
    hrefs = re.findall(r'href="(https?://[^"]+)"', block[:3000])
```

---

## 7. Concrete herbruikbare code snippets

### 7.1 Accordion/dropdown expander

Direct kopieerbaar. Werkt op Bootstrap, Material UI, aria-expanded, details/summary, en generieke CSS patterns.

Bron: `browser_controller.py:584-647` — al volledig weergegeven in sectie 2.2 van `KNOWLEDGE_EXPORT.md`.

### 7.2 Link-extractie (inclusief onclick handlers, data-attributes, iframes)

Bron: `browser_controller.py:456-582` — extraheert links uit:
- `<a href>`
- `data-href`, `data-url`, `data-link`, `data-redirect`
- `onclick` handlers (`window.open`, `window.location`)
- Same-origin iframes
- Non-anchor elementen met `href`

### 7.3 Email-extractie (3 methoden)

Bron: `browser_controller.py:846-952` — combineert:
1. `mailto:` links
2. Regex op `document.body.innerText`
3. Contact-elementen (`.contact`, `footer`, `address`)

### 7.4 Cross-fair contamination preventie

Wanneer je web search gebruikt, kunnen resultaten van ANDERE beurzen verschijnen. De salesapp filtert hierop (`claude_agent.py:2265-2273`):

```python
def is_relevant_to_fair(url: str, fair_name_words: set) -> bool:
    """Check of een search result relevant is voor DEZE beurs."""
    url_lower = url.lower()

    # URL moet minstens één woord uit de beursnaam bevatten
    return any(word in url_lower for word in fair_name_words if len(word) >= 3)
```

### 7.5 Subdomain-probing voor exposantenportals

De salesapp probeert automatisch subdomeinen te ontdekken (`claude_agent.py:504-581`):

```python
# Genereer kandidaat-subdomeinen
root_domain = 'seafoodexpo.com'
abbreviations = ['seg']  # Seafood Expo Global

candidates = [
    f"exhibitors.{root_domain}",
    f"exhibitors-{abbrev}.{root_domain}",
    f"{abbrev}-exhibitors.{root_domain}",
    f"{abbrev}.{root_domain}",
]

# Verifieer via HTTP HEAD
for subdomain in candidates:
    try:
        req = urllib.request.Request(f"https://{subdomain}", method='HEAD')
        req.add_header('User-Agent', 'Mozilla/5.0 ...')
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status < 400:
                verified.append(subdomain)
    except:
        continue
```

### 7.6 API rate limit retry met exponential backoff

Bewezen patroon uit 80+ runs:

```python
import random, anthropic, asyncio

async def api_call_with_retry(client, **kwargs) -> object:
    """Anthropic API call met exponential backoff."""
    for attempt in range(5):
        try:
            return client.beta.messages.create(**kwargs)
        except anthropic.RateLimitError:
            wait = (2 ** attempt) * 5 + random.uniform(0, 3)
            # Wachttijden: ~5s, ~13s, ~23s, ~43s, ~83s
            await asyncio.sleep(wait)
            if attempt == 4:
                raise
    raise RuntimeError("API call failed after 5 retries")
```

### 7.7 Playwright installatie check (voor eerste gebruik)

```python
import subprocess, sys

def ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception as e:
        if "Executable doesn't exist" in str(e):
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True
            )
            return result.returncode == 0
        return False
```
