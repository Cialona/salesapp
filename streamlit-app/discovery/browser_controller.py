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


class BrowserController:
    """Controls a headless browser for Claude Computer Use."""

    def __init__(self, width: int = 1024, height: int = 768):
        self.width = width
        self.height = height
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
        """Extract all links from the current page."""
        if not self._page:
            raise RuntimeError("Browser not launched")

        # Extract links using JavaScript
        links = await self._page.eval_on_selector_all(
            'a[href]',
            '''(anchors) => anchors.map(a => ({
                href: a.getAttribute('href') || '',
                text: (a.textContent || '').trim()
            })).filter(link => link.href.length > 0)'''
        )

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
            'participate', 'preparation', 'planning',
            # German
            'aussteller', 'richtlinie', 'handbuch', 'leitfaden', 'technisch', 'gelände',
            'hallen', 'zeitplan', 'aufbau', 'abbau', 'standbau', 'verzeichnis',
            'verkehr', 'vorschrift', 'termine', 'gelaende', 'messebau',
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

        return {
            'pdf_links': pdf_links,
            'download_links': download_links,
            'exhibitor_links': exhibitor_links,
            'all_links': all_links
        }
