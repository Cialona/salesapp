"""
Claude Computer Use Agent for Trade Fair Discovery
Python implementation using the Anthropic SDK.
"""

import asyncio
import json
import re
import time
from typing import Optional, List, Dict, Any, Callable
from urllib.parse import urlparse

import anthropic

from .browser_controller import BrowserController, DownloadedFile
from .schemas import (
    DiscoveryOutput, TestCaseInput, create_empty_output,
    ScheduleEntry, ActionLogEntry, DownloadedFileInfo, output_to_dict
)


SYSTEM_PROMPT = """Je bent een expert onderzoeksagent die exhibitor documenten vindt op beurs websites. Je doel is om 100% van de gevraagde informatie te vinden.

=== JOUW MISSIE ===
Vind ALLE documenten en informatie die standbouwers nodig hebben:

1. **Floor Plan / Hall Plan** - Plattegrond van de beurshallen (PDF)
   - Zoekwoorden: "Geländeplan", "Hallenplan", "Floor plan", "Site plan", "Hall overview"
2. **Exhibitor Manual / Handbook** - Handleiding voor exposanten (PDF)
   - Zoekwoorden: "Service Documentation", "Exhibitor Guide", "Ausstellerhandbuch", "Verkehrsleitfaden"
3. **Technical Guidelines / Rules** - Technische voorschriften voor standbouw (PDF)
   - Zoekwoorden: "Technical Guidelines", "Technische Richtlinien", "Stand Construction Regulations"
4. **Build-up & Tear-down Schedule** - ALLE opbouw en afbouw datums met exacte tijden
5. **Exhibitor Directory** - Lijst/zoekmachine voor exposanten
   - Vaak op subdomein: exhibitors.beursnaam.de, aussteller.beursnaam.de

=== KRITIEK: GEBRUIK DE PDF LINKS! ===

Na elke actie krijg je een lijst met "📄 PDF LINKS OP DEZE PAGINA".
GEBRUIK DEZE URLS DIRECT IN JE OUTPUT!

Voorbeeld - als je dit ziet:
📄 PDF LINKS OP DEZE PAGINA:
• Geländeplan: https://example.com/content/dam/gelaendeplan.pdf
• Technical Guidelines: https://example.com/documents/guidelines.pdf

Dan gebruik je EXACT die URLs in je JSON output:
- floorplan_url: "https://example.com/content/dam/gelaendeplan.pdf"
- rules_url: "https://example.com/documents/guidelines.pdf"

Je hoeft NIET op de PDF te klikken. De URL die je ziet IS de directe download URL.

=== STRATEGIE ===

1. **Navigeer naar Exhibitor sectie**
   - Menu: "For Exhibitors", "Exhibitors", "Ausstellen", "Planning & Preparation"

2. **Vind Download Center / Service Documentation**
   - Zoek: "Downloads", "Documents", "Service Documentation", "Downloadcenter"
   - BEKIJK de PDF links die verschijnen!

3. **Vind Schedule pagina**
   - Zoek: "Set-up and dismantling", "Aufbau und Abbau", "Timeline"
   - Noteer ALLE datums met tijden

4. **Vind Exhibitor Directory**
   - Zoek: "Exhibitor Search", "Find Exhibitors", "Ausstellerverzeichnis"
   - CHECK ook subdomeinen: exhibitors.[beursnaam].de of online.[beursnaam].com
   - Gebruik goto_url om subdomeinen te bezoeken!

5. **Verzamel je resultaten**
   - Gebruik de PDF URLs die je hebt gezien in de link lijsten
   - Geef je JSON output

=== TOOLS ===

Je hebt twee tools:
1. **computer** - voor screenshots en interactie (klikken, scrollen, typen)
2. **goto_url** - om DIRECT naar een URL te navigeren (gebruik voor subdomeinen en PDF links)

=== SCHEDULE FORMAT ===

Voor build-up en tear-down, geef ALLE datums:
- Advanced set-up (vroege opbouw)
- Regular set-up (normale opbouw)
- Dismantling/Tear-down (afbouw)

Met: datum (YYYY-MM-DD), tijden (HH:MM-HH:MM), beschrijving

=== OUTPUT FORMAT ===

Geef je resultaten als JSON. BELANGRIJK: Gebruik de EXACTE URLs die je hebt gezien!

```json
{
  "floorplan_url": "https://exacte-url-die-je-zag.pdf",
  "exhibitor_manual_url": "https://exacte-url-die-je-zag.pdf",
  "rules_url": "https://exacte-url-die-je-zag.pdf",
  "exhibitor_directory_url": "https://exhibitors.beursnaam.de",
  "downloads_page_url": "https://url-naar-downloadcenter",
  "schedule": {
    "build_up": [
      {"date": "2026-01-29", "time": "07:00-24:00", "description": "Advanced set-up"},
      {"date": "2026-01-31", "time": "07:00-24:00", "description": "Regular set-up"}
    ],
    "tear_down": [
      {"date": "2026-02-10", "time": "17:00-24:00", "description": "Afbouw"}
    ]
  },
  "notes": "Beschrijving van je zoekpad"
}
```

Gebruik null ALLEEN als je het echt niet kunt vinden."""


class ClaudeAgent:
    """Claude Computer Use agent for trade fair discovery."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_iterations: int = 30,
        debug: bool = False,
        on_status: Optional[Callable[[str], None]] = None
    ):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.browser = BrowserController(1024, 768)
        self.max_iterations = max_iterations
        self.debug = debug
        self.on_status = on_status or (lambda x: None)

    def _log(self, message: str) -> None:
        """Log a message."""
        if self.debug:
            timestamp = time.strftime('%H:%M:%S')
            print(f"[{timestamp}] {message}")
        else:
            print(message)
        self.on_status(message)

    async def run(self, input_data: TestCaseInput) -> DiscoveryOutput:
        """Run the discovery agent."""
        output = create_empty_output(input_data.fair_name)
        output.city = input_data.city
        output.country = input_data.country

        start_time = time.time()

        try:
            await self.browser.launch()
            self._log("Browser launched")

            # Navigate to starting URL
            start_url = input_data.known_url or f"https://www.google.com/search?q={input_data.fair_name}+official+website"
            await self.browser.goto(start_url)
            self._log(f"Navigated to: {start_url}")

            # Build initial message
            user_message = f"""
Vind informatie voor de beurs: {input_data.fair_name}
{f'Stad: {input_data.city}' if input_data.city else ''}
{f'Land: {input_data.country}' if input_data.country else ''}
{f'Start URL: {input_data.known_url}' if input_data.known_url else ''}

Navigeer door de website en vind alle gevraagde documenten en informatie.
"""

            # Get initial screenshot
            screenshot = await self.browser.screenshot()
            browser_state = await self.browser.get_state()

            # Start conversation with Claude
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_message},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot.base64,
                            },
                        },
                        {"type": "text", "text": f"Huidige pagina: {browser_state.url}\nTitel: {browser_state.title}"},
                    ],
                },
            ]

            # Agent loop
            iteration = 0
            done = False
            final_result = None

            while not done and iteration < self.max_iterations:
                iteration += 1
                self._log(f"Iteration {iteration}/{self.max_iterations}")

                # Warn agent to wrap up when approaching limit
                if iteration == self.max_iterations - 5:
                    messages.append({
                        "role": "user",
                        "content": [{"type": "text", "text": "⚠️ Je hebt nog 5 acties over. Begin nu met je JSON samenvatting van wat je tot nu toe hebt gevonden. Geef de URLs die je hebt gezien."}],
                    })

                # Call Claude with computer use
                response = self.client.beta.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
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
                            "description": "Navigate directly to a URL. Use this to visit PDF links you see in the extracted links, or to check exhibitor directory subdomains like exhibitors.bauma.de",
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
                    ],
                    messages=messages,
                )

                # Process response
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                # Check for text output (final result)
                for block in assistant_content:
                    if block.type == "text":
                        self._log(f"Claude: {block.text[:200]}...")

                        # Check if this contains the final JSON result
                        if '"floorplan_url"' in block.text or '"exhibitor_manual_url"' in block.text:
                            final_result = block.text

                # Check for tool use
                tool_use_blocks = [b for b in assistant_content if b.type == "tool_use"]

                if len(tool_use_blocks) == 0:
                    done = True
                    break

                # Execute tool calls
                tool_results = []

                for tool_use in tool_use_blocks:
                    if tool_use.name == "computer":
                        result = await self._execute_computer_action(tool_use.input)

                        # Extract links after every action
                        link_info = await self._extract_and_format_links()

                        # Add link info to result
                        if link_info:
                            result.append({"type": "text", "text": link_info})

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": result,
                        })

                    elif tool_use.name == "goto_url":
                        url = tool_use.input.get("url", "")
                        result = await self._execute_goto_url(url)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": result,
                        })

                # Add tool results to messages
                messages.append({"role": "user", "content": tool_results})

                # Log action
                elapsed_ms = int((time.time() - start_time) * 1000)
                output.debug.action_log.append(ActionLogEntry(
                    step="action",
                    input=f"Iteration {iteration}",
                    output=f"{len(tool_use_blocks)} actions executed",
                    ms=elapsed_ms
                ))

                # Check stop condition
                if response.stop_reason == "end_turn" and len(tool_use_blocks) == 0:
                    done = True

            # Parse final result
            if final_result:
                self._parse_result(final_result, output)

            # Set official URL
            state = await self.browser.get_state()
            if input_data.known_url:
                output.official_url = input_data.known_url
                output.official_domain = urlparse(input_data.known_url).netloc
            else:
                output.official_url = state.url
                output.official_domain = urlparse(state.url).netloc

            # Record visited URLs
            output.debug.visited_urls.append(state.url)

            # Record downloaded files and auto-map to output fields
            downloads = self.browser.get_downloaded_files()
            for download in downloads:
                output.debug.downloaded_files.append(DownloadedFileInfo(
                    url=download.original_url,
                    path=download.local_path,
                    content_type='application/pdf' if download.filename.endswith('.pdf') else None,
                    bytes=None
                ))

                # Auto-map downloads to document fields based on filename
                self._auto_map_download(download, output)

            output.debug.notes.append(f"Agent completed in {iteration} iterations")
            output.debug.notes.append(f"Auto-mapped {len(downloads)} downloaded files to output fields")
            output.debug.notes.append(f"Total time: {int(time.time() - start_time)}s")

        except Exception as e:
            error_msg = str(e)
            output.debug.notes.append(f"Error: {error_msg}")
            self._log(f"Error: {error_msg}")
            raise

        finally:
            await self.browser.close()

        return output

    async def _extract_and_format_links(self) -> str:
        """Extract and format relevant links from current page."""
        try:
            relevant_links = await self.browser.get_relevant_links()
            link_info = ""

            if relevant_links['pdf_links']:
                link_info += "\n\n📄 PDF LINKS OP DEZE PAGINA:\n"
                for link in relevant_links['pdf_links'][:20]:
                    link_info += f"• {link.text or 'PDF'}: {link.url}\n"

            if relevant_links['exhibitor_links']:
                link_info += "\n\n🔗 RELEVANTE LINKS:\n"
                for link in relevant_links['exhibitor_links'][:15]:
                    link_info += f"• {link.text}: {link.url}\n"

            # Show download links if different from PDFs
            pdf_urls = {l.url for l in relevant_links['pdf_links']}
            download_only = [l for l in relevant_links['download_links'] if l.url not in pdf_urls]
            if download_only:
                link_info += "\n\n📥 DOWNLOAD LINKS:\n"
                for link in download_only[:10]:
                    link_info += f"• {link.text}: {link.url}\n"

            return link_info
        except:
            return ""

    async def _execute_goto_url(self, url: str) -> List[Dict[str, Any]]:
        """Execute goto_url tool."""
        self._log(f"Navigating to: {url}")

        try:
            await self.browser.goto(url)
            await asyncio.sleep(1)

            screenshot = await self.browser.screenshot()
            state = await self.browser.get_state()
            link_info = await self._extract_and_format_links()

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
                    "text": f"Navigated to: {state.url}\nTitle: {state.title}{link_info}",
                },
            ]
        except Exception as e:
            self._log(f"Navigation error: {e}")
            return [{"type": "text", "text": f"Error navigating to {url}: {e}"}]

    async def _execute_computer_action(self, input_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a computer action."""
        action = input_data.get("action", "")
        self._log(f"Action: {action}")

        try:
            if action == "screenshot":
                pass  # Just take screenshot

            elif action == "mouse_move":
                coord = input_data.get("coordinate", [0, 0])
                await self.browser.move_mouse(coord[0], coord[1])

            elif action == "left_click":
                coord = input_data.get("coordinate")
                if coord:
                    await self.browser.click(coord[0], coord[1])

            elif action == "left_click_drag":
                start = input_data.get("start_coordinate", [0, 0])
                end = input_data.get("end_coordinate", [0, 0])
                await self.browser.drag(start[0], start[1], end[0], end[1])

            elif action == "right_click":
                coord = input_data.get("coordinate")
                if coord:
                    await self.browser.right_click(coord[0], coord[1])

            elif action == "double_click":
                coord = input_data.get("coordinate")
                if coord:
                    await self.browser.double_click(coord[0], coord[1])

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

            else:
                self._log(f"Unknown action: {action}")

            # Wait for page to update
            await asyncio.sleep(0.5)

            # Take new screenshot
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

        except Exception as e:
            self._log(f"Action error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]

    def _auto_map_download(self, download: DownloadedFile, output: DiscoveryOutput) -> None:
        """Auto-map downloaded file to output fields based on filename."""
        filename = download.filename.lower()
        url = download.original_url
        url_lower = url.lower()

        # Floor plan / Hall plan / Geländeplan / Site plan
        is_floorplan = (
            'gelände' in filename or 'gelande' in filename or
            'floor' in filename or 'hall' in filename or
            'site' in filename or 'hallen' in filename or
            ('plan' in filename and 'richtlin' not in filename and 'techni' not in filename) or
            'map' in filename or 'overview' in filename or
            'gelaende' in url_lower or 'floorplan' in url_lower or
            'hallenplan' in url_lower or 'siteplan' in url_lower
        ) and 'richtlin' not in filename and 'techni' not in filename and 'guideline' not in filename

        if is_floorplan and not output.documents.floorplan_url:
            output.documents.floorplan_url = url
            output.quality.floorplan = 'strong'
            output.primary_reasoning.floorplan = f"Auto-detected from download: {download.filename}"

        # Technical Guidelines / Richtlinien / Regulations
        is_rules = (
            'richtlin' in filename or 'guideline' in filename or
            'techni' in filename or 'regulation' in filename or
            'vorschrift' in filename or 'regel' in filename or
            'construction' in filename or 'standbau' in filename or
            'richtlin' in url_lower or 'guideline' in url_lower or
            'technical' in url_lower
        )

        if is_rules and not output.documents.rules_url:
            output.documents.rules_url = url
            output.quality.rules = 'strong'
            output.primary_reasoning.rules = f"Auto-detected from download: {download.filename}"

        # Exhibitor Manual / Service Documentation / Verkehrsleitfaden / Handbuch
        is_manual = (
            'manual' in filename or 'handbook' in filename or
            'handbuch' in filename or 'service' in filename or
            'leitfaden' in filename or 'verkehr' in filename or
            'aussteller' in filename or 'exhibitor' in filename or
            'guide' in filename or 'documentation' in filename or
            'manual' in url_lower or 'handbook' in url_lower or
            'service-doc' in url_lower or 'leitfaden' in url_lower
        ) and not is_rules

        if is_manual and not output.documents.exhibitor_manual_url:
            output.documents.exhibitor_manual_url = url
            output.quality.exhibitor_manual = 'strong'
            output.primary_reasoning.exhibitor_manual = f"Auto-detected from download: {download.filename}"

        # Schedule / Timeline / Zeitplan
        is_schedule = (
            'zeitplan' in filename or 'timeline' in filename or
            'schedule' in filename or 'aufbau' in filename or
            'abbau' in filename or 'termine' in filename or
            'dismantl' in filename or 'set-up' in filename or
            'schedule' in url_lower or 'timeline' in url_lower
        )

        if is_schedule and not output.documents.schedule_page_url:
            output.documents.schedule_page_url = url

    def _parse_result(self, text: str, output: DiscoveryOutput) -> None:
        """Parse the final JSON result from Claude."""
        # Try to extract JSON from the text
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if not json_match:
            json_match = re.search(r'\{[\s\S]*"floorplan_url"[\s\S]*\}', text)

        if not json_match:
            output.debug.notes.append("Could not parse final JSON result")
            return

        try:
            json_str = json_match.group(1) if json_match.lastindex else json_match.group(0)
            result = json.loads(json_str)

            # Map to output structure
            if result.get("floorplan_url"):
                output.documents.floorplan_url = result["floorplan_url"]
                output.quality.floorplan = "strong"
                output.primary_reasoning.floorplan = "Found by Claude agent"

            if result.get("exhibitor_manual_url"):
                output.documents.exhibitor_manual_url = result["exhibitor_manual_url"]
                output.quality.exhibitor_manual = "strong"
                output.primary_reasoning.exhibitor_manual = "Found by Claude agent"

            if result.get("rules_url"):
                output.documents.rules_url = result["rules_url"]
                output.quality.rules = "strong"
                output.primary_reasoning.rules = "Found by Claude agent"

            if result.get("exhibitor_directory_url"):
                output.documents.exhibitor_directory_url = result["exhibitor_directory_url"]
                output.quality.exhibitor_directory = "strong"
                output.primary_reasoning.exhibitor_directory = "Found by Claude agent"

            if result.get("downloads_page_url"):
                output.documents.downloads_overview_url = result["downloads_page_url"]

            # Parse schedule
            schedule = result.get("schedule", {})
            if schedule:
                build_up = schedule.get("build_up", [])
                if isinstance(build_up, list):
                    for entry in build_up:
                        output.schedule.build_up.append(ScheduleEntry(
                            date=entry.get("date"),
                            time=entry.get("time"),
                            description=entry.get("description", ""),
                            source_url=output.documents.exhibitor_manual_url or output.official_url or ""
                        ))

                tear_down = schedule.get("tear_down", [])
                if isinstance(tear_down, list):
                    for entry in tear_down:
                        output.schedule.tear_down.append(ScheduleEntry(
                            date=entry.get("date"),
                            time=entry.get("time"),
                            description=entry.get("description", ""),
                            source_url=output.documents.exhibitor_manual_url or output.official_url or ""
                        ))

                if output.schedule.build_up or output.schedule.tear_down:
                    output.quality.schedule = "strong"
                    output.primary_reasoning.schedule = f"Found {len(output.schedule.build_up)} build-up and {len(output.schedule.tear_down)} tear-down entries"

            if result.get("notes"):
                output.debug.notes.append(f"Agent notes: {result['notes']}")

        except json.JSONDecodeError as e:
            output.debug.notes.append(f"JSON parse error: {e}")


async def run_discovery(
    fair_name: str,
    known_url: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    api_key: Optional[str] = None,
    on_status: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
    """
    Run a discovery and return the result as a dictionary.

    This is the main entry point for the Streamlit app.
    """
    input_data = TestCaseInput(
        fair_name=fair_name,
        known_url=known_url,
        city=city,
        country=country
    )

    agent = ClaudeAgent(
        api_key=api_key,
        max_iterations=30,
        debug=True,
        on_status=on_status
    )

    output = await agent.run(input_data)
    return output_to_dict(output)
