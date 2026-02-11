"""
Browser Controller for Claude Computer Use
Python implementation using Playwright.
"""

import asyncio
import base64
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, Browser, Page, BrowserContext


@dataclass
class ScreenshotResult:
    base64: str
    width: int
    height: int


@dataclass
class BrowserState:
    url: str
    title: str


@dataclass
class DownloadedFile:
    original_url: str
    local_path: str
    filename: str


@dataclass
class LinkInfo:
    url: str
    text: str
    is_pdf: bool = False


@dataclass
class ExtractedEmail:
    """Email address extracted from a page with context."""
    email: str
    context: str = ""  # Surrounding text or link text
    source_type: str = ""  # 'mailto', 'text', 'contact_page'


class BrowserController:
    """Controls a headless browser for Claude Computer Use."""

    def __init__(self, width: int = 1024, height: int = 768, download_dir_suffix: str = ""):
        self.width = width
        self.height = height
        if download_dir_suffix:
            self.download_dir = Path.cwd() / '.cache' / 'downloads' / download_dir_suffix
        else:
            self.download_dir = Path.cwd() / '.cache' / 'downloads'
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._downloads: List[DownloadedFile] = []

    async def launch(self) -> None:
        """Launch the browser."""
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

        # Handle downloads - track original URL and local path
        self._page.on('download', self._handle_download)

    async def _handle_download(self, download) -> None:
        """Handle file downloads."""
        filename = download.suggested_filename
        filepath = self.download_dir / filename
        original_url = download.url

        await download.save_as(str(filepath))

        self._downloads.append(DownloadedFile(
            original_url=original_url,
            local_path=str(filepath),
            filename=filename
        ))

        print(f"[DOWNLOAD] Saved: {filename}")
        print(f"[DOWNLOAD] Original URL: {original_url}")

    async def close(self) -> None:
        """Close the browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._context = None
        self._page = None

    async def screenshot(self) -> ScreenshotResult:
        """Take a screenshot of the current page."""
        if not self._page:
            raise RuntimeError("Browser not launched")

        buffer = await self._page.screenshot(type='png')
        b64 = base64.b64encode(buffer).decode('utf-8')

        return ScreenshotResult(
            base64=b64,
            width=self.width,
            height=self.height
        )

    async def get_state(self) -> BrowserState:
        """Get current browser state."""
        if not self._page:
            raise RuntimeError("Browser not launched")

        return BrowserState(
            url=self._page.url,
            title=await self._page.title()
        )

    async def extract_page_text(self, max_chars: int = 15000) -> str:
        """Extract the visible text content from the current page."""
        if not self._page:
            return ""
        try:
            text = await self._page.evaluate("() => document.body.innerText")
            return (text or "")[:max_chars]
        except Exception:
            return ""

    @staticmethod
    def _is_salesforce_infrastructure_url(url: str) -> bool:
        """
        Check if a URL is a Salesforce infrastructure/platform URL (not actual portal content).
        These are internal Salesforce services like login, SAML, payments, CDN, etc.
        that should be filtered out from portal detection.
        """
        lower = url.lower()
        host = urlparse(url).netloc.lower()
        path = urlparse(url).path.lower()

        # Block known Salesforce infrastructure hosts
        infra_hosts = [
            'login.salesforce.com',
            'c.salesforce.com',
            'payments.salesforce.com',
            'service.force.com',
            'location.force.com',
            'sfdc-link-preview.',
        ]
        if any(h in host for h in infra_hosts):
            return True

        # Block known Salesforce infrastructure subdomains
        infra_patterns = [
            '.secure.force.com',    # SCORM, trial apps, etc.
            '.file.force.com',      # File serving (requires login)
            'sfdc-',                 # Salesforce internal CDN
        ]
        if any(p in host for p in infra_patterns):
            return True

        # Block infrastructure paths on any Salesforce domain
        infra_paths = [
            '/saml/', '/saml?',
            '/login/', '/login?',
            '/jslibrary/',
            '/icons/',
            '/brand-asset/',
            '/embeddedservice/',
            '/login-messages/',
            '/sessionserver',
        ]
        if any(p in path for p in infra_paths):
            return True

        # Block *.my.salesforce.com (admin console, not community portal)
        if '.my.salesforce.com' in host:
            return True

        # Block OEM platform internal URLs (require authentication, not public content)
        oem_paths = [
            '/oemlogin',                    # OEM login page
            '/secur/logout.jsp',            # Salesforce logout
            '/oempageredirect',             # OEM internal redirect
            '/oemprogressbar',              # OEM UI progress bar component
            '/oemindex',                    # OEM search/index page
            '/exhibitorstanddetailpage',    # Stand detail (requires auth)
        ]
        if any(p in path for p in oem_paths):
            return True

        # Block static resource URLs on force.com (JS, CSS, images)
        if '.force.com' in host and '/resource/' in path:
            return True

        # Block image/media file URLs on portal domains
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.webp', '.bmp')
        if any(path.endswith(ext) for ext in image_extensions):
            # Only block on known portal domains (not on general websites)
            portal_hosts = ['.my.site.com', '.force.com', '.salesforce.com',
                           '.cvent.com', '.a2zinc.net', '.expocad.', '.smallworldlabs.com']
            if any(ph in host for ph in portal_hosts):
                return True

        return False

    @staticmethod
    def _is_salesforce_file_download(url: str) -> bool:
        """Check if a URL is a Salesforce file download link (should be treated as PDF)."""
        return 'servlet/servlet.FileDownload' in url or 'servlet.FileDownload' in url

    @staticmethod
    def _derive_portal_home_from_file_url(url: str) -> Optional[str]:
        """
        Derive the portal home URL from a Salesforce FileDownload URL.
        E.g., https://gsma.my.site.com/mwcoem/servlet/servlet.FileDownload?file=X
        -> https://gsma.my.site.com/mwcoem/s/Home
        """
        if 'my.site.com' not in url:
            return None
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        # Path is like: mwcoem/servlet/servlet.FileDownload
        # We want: mwcoem/s/Home
        if len(path_parts) >= 1:
            community_prefix = path_parts[0]  # e.g., "mwcoem"
            return f"{parsed.scheme}://{parsed.netloc}/{community_prefix}/s/Home"
        return None

    async def extract_external_portal_urls(self) -> List[Dict[str, str]]:
        """
        Extract external portal URLs from the page HTML source.
        Searches the raw HTML for URLs pointing to known portal platforms
        (Salesforce, Cvent, etc.) that may be hidden in JavaScript, data attributes,
        or dynamically rendered content.

        Filters out Salesforce infrastructure URLs (login, SAML, payments, CDN).
        Classifies FileDownload URLs separately for PDF treatment.
        """
        if not self._page:
            return []

        try:
            # Get the full HTML source
            html = await self._page.content()

            import re
            portal_patterns = [
                r'(https?://[a-zA-Z0-9.-]+\.my\.site\.com[^\s"\'<>]*)',  # Salesforce community
                r'(https?://[a-zA-Z0-9.-]+\.force\.com[^\s"\'<>]*)',     # Salesforce
                r'(https?://[a-zA-Z0-9.-]+\.salesforce\.com[^\s"\'<>]*)', # Salesforce
                r'(https?://[a-zA-Z0-9.-]+\.cvent\.com[^\s"\'<>]*)',     # Cvent
                r'(https?://[a-zA-Z0-9.-]+\.a2zinc\.net[^\s"\'<>]*)',    # A2Z
                r'(https?://[a-zA-Z0-9.-]+\.expocad\.[a-z]+[^\s"\'<>]*)',# ExpoCad
                r'(https?://[a-zA-Z0-9.-]+\.smallworldlabs\.com[^\s"\'<>]*)', # SWL
            ]

            found = []
            seen = set()
            derived_homes = set()

            for pattern in portal_patterns:
                matches = re.findall(pattern, html)
                for url in matches:
                    # Clean up the URL
                    url = url.rstrip('\\').rstrip(')').rstrip(';')
                    if url in seen:
                        continue
                    seen.add(url)

                    # Skip Salesforce infrastructure URLs
                    if self._is_salesforce_infrastructure_url(url):
                        continue

                    # Classify FileDownload URLs specially
                    if self._is_salesforce_file_download(url):
                        found.append({'url': url, 'source': 'html_source', 'is_file_download': True})
                        # Derive portal home from FileDownload URL
                        home = self._derive_portal_home_from_file_url(url)
                        if home and home not in derived_homes:
                            derived_homes.add(home)
                            found.append({'url': home, 'source': 'derived_from_file_download', 'is_file_download': False})
                    else:
                        found.append({'url': url, 'source': 'html_source', 'is_file_download': False})

            return found
        except Exception:
            return []

    # Computer Use Actions

    async def click(self, x: int, y: int) -> None:
        """Click at coordinates."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.mouse.click(x, y)
        await self._page.wait_for_timeout(500)

    async def double_click(self, x: int, y: int) -> None:
        """Double click at coordinates."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.mouse.dblclick(x, y)
        await self._page.wait_for_timeout(500)

    async def right_click(self, x: int, y: int) -> None:
        """Right click at coordinates."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.mouse.click(x, y, button='right')
        await self._page.wait_for_timeout(300)

    async def move_mouse(self, x: int, y: int) -> None:
        """Move mouse to coordinates."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.mouse.move(x, y)

    async def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        """Drag from start to end coordinates."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.mouse.move(start_x, start_y)
        await self._page.mouse.down()
        await self._page.mouse.move(end_x, end_y)
        await self._page.mouse.up()

    async def type_text(self, text: str) -> None:
        """Type text."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.keyboard.type(text, delay=50)

    async def press_key(self, key: str) -> None:
        """Press a keyboard key."""
        if not self._page:
            raise RuntimeError("Browser not launched")

        # Map common key names
        key_map = {
            'enter': 'Enter',
            'return': 'Enter',
            'tab': 'Tab',
            'escape': 'Escape',
            'esc': 'Escape',
            'backspace': 'Backspace',
            'delete': 'Delete',
            'up': 'ArrowUp',
            'down': 'ArrowDown',
            'left': 'ArrowLeft',
            'right': 'ArrowRight',
            'home': 'Home',
            'end': 'End',
            'pageup': 'PageUp',
            'pagedown': 'PageDown',
            'space': ' ',
        }

        mapped_key = key_map.get(key.lower(), key)
        await self._page.keyboard.press(mapped_key)

    async def hotkey(self, *keys: str) -> None:
        """Press a key combination."""
        if not self._page:
            raise RuntimeError("Browser not launched")

        modifiers = list(keys[:-1])
        final_key = keys[-1] if keys else ''

        for mod in modifiers:
            await self._page.keyboard.down(mod)

        await self._page.keyboard.press(final_key)

        for mod in reversed(modifiers):
            await self._page.keyboard.up(mod)

    async def scroll(self, x: int, y: int, delta_x: int, delta_y: int) -> None:
        """Scroll at coordinates."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.mouse.move(x, y)
        await self._page.mouse.wheel(delta_x, delta_y)
        await self._page.wait_for_timeout(300)

    async def goto(self, url: str) -> None:
        """Navigate to URL."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await self._page.wait_for_timeout(1000)

    async def wait_for_navigation(self, timeout: int = 10000) -> None:
        """Wait for navigation to complete."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        try:
            await self._page.wait_for_navigation(timeout=timeout)
        except:
            pass  # Timeout is ok

    def get_downloaded_files(self) -> List[DownloadedFile]:
        """Get list of downloaded files."""
        return self._downloads

    def clear_downloads(self) -> None:
        """Clear download tracking."""
        self._downloads = []

    async def get_page_content(self) -> str:
        """Get page HTML content."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        return await self._page.content()

    async def is_pdf_page(self) -> bool:
        """Check if current page is a PDF."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        url = self._page.url.lower()
        return url.endswith('.pdf') or '/pdf/' in url

    def get_display_size(self) -> Dict[str, int]:
        """Get display dimensions."""
        return {'width': self.width, 'height': self.height}

    async def extract_links(self) -> List[LinkInfo]:
        """Extract all links from the current page, including buttons and interactive elements."""
        if not self._page:
            raise RuntimeError("Browser not launched")

        # First, expand all accordions/details/dropdowns to reveal hidden content
        await self._expand_all_hidden_sections()

        # Extract links from <a> tags AND from buttons/interactive elements
        links = await self._page.evaluate('''() => {
            const results = [];
            const seen = new Set();

            // 1. Standard <a href> links
            document.querySelectorAll('a[href]').forEach(a => {
                const href = a.getAttribute('href') || '';
                const text = (a.textContent || '').trim();
                if (href.length > 0 && !seen.has(href)) {
                    seen.add(href);
                    results.push({href, text, source: 'a'});
                }
            });

            // 2. Buttons and clickable elements with data-href, data-url, data-link
            const dataAttrs = ['data-href', 'data-url', 'data-link', 'data-target-url', 'data-redirect'];
            document.querySelectorAll('button, [role="button"], [class*="btn"], [class*="button"]').forEach(el => {
                for (const attr of dataAttrs) {
                    const val = el.getAttribute(attr);
                    if (val && val.startsWith('http') && !seen.has(val)) {
                        seen.add(val);
                        results.push({href: val, text: (el.textContent || '').trim(), source: 'data-attr'});
                    }
                }
            });

            // 3. Elements with onclick containing URLs (window.open, window.location, etc.)
            document.querySelectorAll('[onclick]').forEach(el => {
                const onclick = el.getAttribute('onclick') || '';
                // Extract URLs from onclick handlers
                const urlPatterns = [
                    /window\.open\s*\(\s*['"]([^'"]+)['"]/,
                    /window\.location\s*=\s*['"]([^'"]+)['"]/,
                    /window\.location\.href\s*=\s*['"]([^'"]+)['"]/,
                    /location\.href\s*=\s*['"]([^'"]+)['"]/,
                    /https?:\/\/[^\s'"]+/
                ];
                for (const pattern of urlPatterns) {
                    const match = onclick.match(pattern);
                    if (match) {
                        const url = match[1] || match[0];
                        if (!seen.has(url)) {
                            seen.add(url);
                            results.push({href: url, text: (el.textContent || '').trim(), source: 'onclick'});
                        }
                    }
                }
            });

            // 4. Links in iframes (if same-origin)
            try {
                document.querySelectorAll('iframe').forEach(iframe => {
                    try {
                        const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
                        if (iframeDoc) {
                            iframeDoc.querySelectorAll('a[href]').forEach(a => {
                                const href = a.getAttribute('href') || '';
                                if (href.startsWith('http') && !seen.has(href)) {
                                    seen.add(href);
                                    results.push({href, text: (a.textContent || '').trim(), source: 'iframe'});
                                }
                            });
                        }
                    } catch(e) {} // Cross-origin iframe - skip
                });
            } catch(e) {}

            // 5. Any element with href attribute (not just <a>)
            document.querySelectorAll('[href]:not(a):not(link):not(base)').forEach(el => {
                const href = el.getAttribute('href') || '';
                if (href.startsWith('http') && !seen.has(href)) {
                    seen.add(href);
                    results.push({href, text: (el.textContent || '').trim(), source: 'other-href'});
                }
            });

            return results;
        }''')

        base_url = self._page.url
        parsed_base = urlparse(base_url)

        result = []
        for link in links:
            href = link['href']
            text = link['text']

            # Convert relative URLs to absolute
            if href.startswith('/'):
                full_url = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
            elif not href.startswith('http'):
                full_url = urljoin(base_url, href)
            else:
                full_url = href

            lower_url = full_url.lower()
            lower_text = text.lower()

            # Detect PDF links comprehensively
            is_pdf = (
                lower_url.endswith('.pdf') or
                '/pdf/' in lower_url or
                '.pdf?' in lower_url or
                '/document/' in lower_url or
                '/content/dam/' in lower_url or
                '/sites/default/files/' in lower_url or  # Drupal CMS
                'cloudfront.net' in lower_url or
                'pdf' in lower_text or
                'download' in lower_text
            )

            result.append(LinkInfo(
                url=full_url,
                text=text[:100],  # Limit text length
                is_pdf=is_pdf
            ))

        return result

    async def _expand_all_hidden_sections(self) -> None:
        """Expand all accordion, details, and dropdown elements to reveal hidden content."""
        if not self._page:
            return

        try:
            # JavaScript to expand various types of hidden content
            await self._page.evaluate('''() => {
                // 1. Expand all <details> elements
                document.querySelectorAll('details').forEach(d => d.open = true);

                // 2. Click on accordion triggers (common patterns)
                const accordionSelectors = [
                    '[data-toggle="collapse"]',
                    '[data-bs-toggle="collapse"]',
                    '.accordion-button:not(.collapsed)',
                    '.accordion-trigger',
                    '.collapse-trigger',
                    '[aria-expanded="false"]',
                    '.expandable:not(.expanded)',
                    '.collapsible:not(.open)',
                    'button[class*="accordion"]',
                    'div[class*="accordion"] > button',
                    'div[class*="accordion"] > div > button',
                    '.faq-question',
                    '.toggle-content',
                    '[class*="expand"]',
                    '[class*="dropdown"]:not(.open)',
                ];

                accordionSelectors.forEach(selector => {
                    try {
                        document.querySelectorAll(selector).forEach(el => {
                            if (el.getAttribute('aria-expanded') === 'false') {
                                el.click();
                            }
                        });
                    } catch(e) {}
                });

                // 3. Set aria-expanded to true
                document.querySelectorAll('[aria-expanded="false"]').forEach(el => {
                    el.setAttribute('aria-expanded', 'true');
                    el.click();
                });

                // 4. Show hidden collapse elements
                document.querySelectorAll('.collapse:not(.show)').forEach(el => {
                    el.classList.add('show');
                });

                // 5. Expand Material UI / React accordions
                document.querySelectorAll('[class*="MuiAccordion"]:not([class*="expanded"])').forEach(el => {
                    const button = el.querySelector('[class*="MuiAccordionSummary"]');
                    if (button) button.click();
                });
            }''')

            # Wait for content to load
            await self._page.wait_for_timeout(500)

        except Exception as e:
            # Silently continue if expansion fails - it's optional
            print(f"[DEBUG] Accordion expansion error (non-fatal): {e}")

    async def get_relevant_links(self) -> Dict[str, List[LinkInfo]]:
        """Get relevant links for trade fair research."""
        all_links = await self.extract_links()

        pdf_links = [l for l in all_links if l.is_pdf]

        # Expanded download keywords with CMS patterns
        download_keywords = [
            'download', 'document', 'pdf', 'file', 'media', 'asset',
            'content/dam', 'cloudfront', 'sites/default/files',  # Drupal CMS
            '/files/', '/docs/', '/downloads/', '/documents/',
            'blob.core.windows.net', 's3.amazonaws.com'  # Cloud storage
        ]
        download_links = [
            l for l in all_links
            if any(kw in l.url.lower() or kw in l.text.lower() for kw in download_keywords)
        ]

        # Expanded exhibitor keywords with more languages
        exhibitor_keywords = [
            # English
            'exhibitor', 'manual', 'handbook', 'guideline', 'technical', 'floor', 'plan',
            'hall', 'schedule', 'timeline', 'directory', 'service', 'documentation',
            'set-up', 'dismantl', 'build-up', 'tear-down', 'construction', 'regulation',
            'provision', 'sustainable', 'stand design', 'booth', 'catalogue', 'catalog',
            'participate', 'preparation', 'planning', 'contractor',
            # German
            'aussteller', 'richtlinie', 'handbuch', 'leitfaden', 'technisch', 'gelände',
            'hallen', 'zeitplan', 'aufbau', 'abbau', 'standbau', 'verzeichnis',
            'verkehr', 'vorschrift', 'termine', 'gelaende', 'messebau',
            # Dutch
            'standbouw', 'standbouwer', 'standhouder', 'opbouw', 'afbouw',
            'toegang', 'voorschrift',
            # Italian (for fairs like Salone del Mobile)
            'espositore', 'espositori', 'regolamento', 'tecnico', 'montaggio', 'smontaggio',
            'allestimento', 'partecipare', 'servizi', 'catalogo', 'padiglione',
            # French
            'exposant', 'règlement', 'technique', 'montage', 'démontage', 'stand',
            # Spanish
            'expositor', 'reglamento', 'técnico', 'montaje', 'desmontaje',
        ]
        exhibitor_links = [
            l for l in all_links
            if any(kw in l.url.lower() or kw in l.text.lower() for kw in exhibitor_keywords)
        ]

        # Identify high-value document links (likely technical docs)
        high_value_keywords = [
            'technical', 'regulation', 'provision', 'richtlin', 'regolamento',
            'construction', 'standbau', 'allestimento', 'setup', 'dismant',
            'montaggio', 'smontaggio', 'aufbau', 'abbau',
            'contractor', 'standbouw', 'opbouw', 'afbouw',
        ]
        high_value_links = [
            l for l in all_links
            if any(kw in l.url.lower() or kw in l.text.lower() for kw in high_value_keywords)
        ]

        return {
            'pdf_links': pdf_links,
            'download_links': download_links,
            'exhibitor_links': exhibitor_links,
            'high_value_links': high_value_links,
            'all_links': all_links
        }

    async def extract_navigation_links(self) -> List[LinkInfo]:
        """Extract links from the site's main navigation (header, nav elements).

        These represent the site's own structure and should always be followed,
        regardless of whether they match document keywords. This helps discover
        pages like "Show Layout", "Exhibiting", "Stand Build" that may not match
        hardcoded keyword patterns.
        """
        if not self._page:
            return []

        try:
            nav_links = await self._page.evaluate('''() => {
                const results = [];
                const seen = new Set();

                // Selectors for navigation containers (ordered by specificity)
                const navSelectors = [
                    'nav a[href]',
                    'header a[href]',
                    '[role="navigation"] a[href]',
                    '.nav a[href]', '.navbar a[href]',
                    '.main-nav a[href]', '.main-menu a[href]',
                    '.primary-nav a[href]', '.site-nav a[href]',
                    '.menu a[href]', '.top-menu a[href]',
                    '#main-navigation a[href]', '#primary-menu a[href]',
                ];

                for (const selector of navSelectors) {
                    try {
                        document.querySelectorAll(selector).forEach(a => {
                            const href = a.getAttribute('href') || '';
                            const text = (a.textContent || '').trim();
                            if (href.length > 1 && !seen.has(href) && text.length > 0 && text.length < 100) {
                                seen.add(href);
                                results.push({href, text});
                            }
                        });
                    } catch(e) {}
                }

                return results;
            }''')

            base_url = self._page.url
            parsed_base = urlparse(base_url)
            result = []

            for link in nav_links:
                href = link['href']
                text = link['text']

                # Convert relative to absolute
                if href.startswith('/'):
                    full_url = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
                elif not href.startswith('http'):
                    full_url = urljoin(base_url, href)
                else:
                    full_url = href

                # Skip fragment-only links, javascript: etc
                if href.startswith('#') or href.startswith('javascript:'):
                    continue

                result.append(LinkInfo(
                    url=full_url,
                    text=text[:80],
                    is_pdf=full_url.lower().endswith('.pdf')
                ))

            return result

        except Exception:
            return []

    async def extract_emails(self) -> List[ExtractedEmail]:
        """Extract email addresses from the current page."""
        import re

        if not self._page:
            return []

        emails_found = []
        seen_emails = set()

        # Email regex pattern
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

        try:
            # Method 1: Extract from mailto: links
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
                if email and email not in seen_emails and '@' in email:
                    seen_emails.add(email)
                    emails_found.append(ExtractedEmail(
                        email=email,
                        context=item['context'][:100] if item['context'] else '',
                        source_type='mailto'
                    ))

            # Method 2: Extract from page text content
            page_text = await self._page.evaluate("() => document.body.innerText")
            text_emails = re.findall(email_pattern, page_text)

            for email in text_emails:
                email_lower = email.lower()
                if email_lower not in seen_emails:
                    # Try to find context around the email
                    context = ""
                    idx = page_text.lower().find(email_lower)
                    if idx != -1:
                        start = max(0, idx - 50)
                        end = min(len(page_text), idx + len(email) + 50)
                        context = page_text[start:end].strip()

                    seen_emails.add(email_lower)
                    emails_found.append(ExtractedEmail(
                        email=email_lower,
                        context=context[:100] if context else '',
                        source_type='text'
                    ))

            # Method 3: Look for contact-related elements
            contact_emails = await self._page.evaluate("""
                () => {
                    const emailPattern = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/g;
                    const results = [];

                    // Look in elements that typically contain contact info
                    const selectors = [
                        '.contact', '#contact', '[class*="contact"]',
                        '.footer', '#footer', 'footer',
                        '.email', '[class*="email"]',
                        'address', '[itemtype*="ContactPoint"]'
                    ];

                    selectors.forEach(selector => {
                        try {
                            const elements = document.querySelectorAll(selector);
                            elements.forEach(el => {
                                const text = el.innerText || '';
                                const matches = text.match(emailPattern);
                                if (matches) {
                                    matches.forEach(email => {
                                        results.push({
                                            email: email,
                                            context: selector
                                        });
                                    });
                                }
                            });
                        } catch(e) {}
                    });

                    return results;
                }
            """)

            for item in contact_emails:
                email = item['email'].lower()
                if email not in seen_emails:
                    seen_emails.add(email)
                    emails_found.append(ExtractedEmail(
                        email=email,
                        context=item['context'],
                        source_type='contact_page'
                    ))

        except Exception as e:
            print(f"Error extracting emails: {e}")

        return emails_found
