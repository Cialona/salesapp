/**
 * Claude Computer Use Agent for Trade Fair Discovery
 *
 * This agent uses Claude's Computer Use capability to navigate
 * trade fair websites and find exhibitor information.
 */

import Anthropic from '@anthropic-ai/sdk';
import { BrowserController, type DownloadedFile } from './browser-controller.js';
import type { DiscoveryOutput, TestCaseInput } from '../schemas/output.js';
import { createEmptyOutput } from '../schemas/output.js';

// Types for Claude Computer Use
interface ComputerToolResult {
  type: 'tool_result';
  tool_use_id: string;
  content: Array<{
    type: 'image';
    source: {
      type: 'base64';
      media_type: 'image/png';
      data: string;
    };
  }>;
}

interface TextContent {
  type: 'text';
  text: string;
}

type BetaContentBlock = Anthropic.Beta.Messages.BetaContentBlock;
type BetaToolUseBlock = Anthropic.Beta.Messages.BetaToolUseBlock;
type BetaMessageParam = Anthropic.Beta.Messages.BetaMessageParam;

const SYSTEM_PROMPT = `Je bent een expert onderzoeksagent die exhibitor documenten vindt op beurs websites. Je doel is om 100% van de gevraagde informatie te vinden.

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

\`\`\`json
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
\`\`\`

Gebruik null ALLEEN als je het echt niet kunt vinden.`;

export interface ClaudeAgentOptions {
  apiKey?: string;
  maxIterations?: number;
  debug?: boolean;
}

export class ClaudeAgent {
  private client: Anthropic;
  private browser: BrowserController;
  private maxIterations: number;
  private debug: boolean;

  constructor(options: ClaudeAgentOptions = {}) {
    this.client = new Anthropic({
      apiKey: options.apiKey || process.env['ANTHROPIC_API_KEY'],
    });
    // Smaller viewport = smaller screenshots = lower costs
    this.browser = new BrowserController(1024, 768);
    // 30 iterations: ~15 navigate, ~10 find docs, ~5 to write JSON summary
    this.maxIterations = options.maxIterations || 30;
    this.debug = options.debug || false;
  }

  async run(input: TestCaseInput): Promise<DiscoveryOutput> {
    const output = createEmptyOutput(input.fair_name);
    output.city = input.city;
    output.country = input.country;

    const startTime = Date.now();

    try {
      await this.browser.launch();
      this.log('Browser launched');

      // Navigate to the starting URL
      const startUrl = input.known_url || `https://www.google.com/search?q=${encodeURIComponent(input.fair_name + ' official website')}`;
      await this.browser.goto(startUrl);
      this.log(`Navigated to: ${startUrl}`);

      // Build initial message
      const userMessage = `
Vind informatie voor de beurs: ${input.fair_name}
${input.city ? `Stad: ${input.city}` : ''}
${input.country ? `Land: ${input.country}` : ''}
${input.known_url ? `Start URL: ${input.known_url}` : ''}

Navigeer door de website en vind alle gevraagde documenten en informatie.
`;

      // Get initial screenshot
      const screenshot = await this.browser.screenshot();
      const browserState = await this.browser.getState();

      // Start conversation with Claude
      const messages: BetaMessageParam[] = [
        {
          role: 'user',
          content: [
            { type: 'text', text: userMessage },
            {
              type: 'image',
              source: {
                type: 'base64',
                media_type: 'image/png',
                data: screenshot.base64,
              },
            },
            { type: 'text', text: `Huidige pagina: ${browserState.url}\nTitel: ${browserState.title}` },
          ],
        },
      ];

      // Agent loop
      let iteration = 0;
      let done = false;
      let finalResult: string | null = null;

      while (!done && iteration < this.maxIterations) {
        iteration++;
        this.log(`\n--- Iteration ${iteration} ---`);

        // Warn agent to wrap up when approaching limit
        if (iteration === this.maxIterations - 5) {
          messages.push({
            role: 'user',
            content: [{ type: 'text', text: '⚠️ Je hebt nog 5 acties over. Begin nu met je JSON samenvatting van wat je tot nu toe hebt gevonden. Geef de URLs die je hebt gezien.' }],
          });
        }

        // Call Claude with computer use beta
        const response = await this.client.beta.messages.create({
          model: 'claude-sonnet-4-20250514',
          max_tokens: 4096,
          system: SYSTEM_PROMPT,
          betas: ['computer-use-2025-01-24'],
          tools: [
            {
              type: 'computer_20250124' as const,
              name: 'computer',
              display_width_px: screenshot.width,
              display_height_px: screenshot.height,
              display_number: 1,
            } as Anthropic.Beta.Messages.BetaToolComputerUse20250124,
            // Custom goto_url tool for direct navigation
            {
              name: 'goto_url',
              description: 'Navigate directly to a URL. Use this to visit PDF links you see in the extracted links, or to check exhibitor directory subdomains like exhibitors.bauma.de',
              input_schema: {
                type: 'object' as const,
                properties: {
                  url: {
                    type: 'string',
                    description: 'The full URL to navigate to',
                  },
                },
                required: ['url'],
              },
            },
          ],
          messages,
        });

        // Process response
        const assistantContent = response.content;
        messages.push({ role: 'assistant', content: assistantContent as Anthropic.Beta.Messages.BetaContentBlockParam[] });

        // Check for text output (final result)
        for (const block of assistantContent) {
          if (block.type === 'text') {
            this.log(`Claude says: ${block.text.slice(0, 200)}...`);

            // Check if this contains the final JSON result
            if (block.text.includes('"floorplan_url"') || block.text.includes('"exhibitor_manual_url"')) {
              finalResult = block.text;
            }
          }
        }

        // Check for tool use
        const toolUseBlocks = assistantContent.filter((b): b is BetaToolUseBlock => b.type === 'tool_use');

        if (toolUseBlocks.length === 0) {
          // No more tool calls - Claude is done
          done = true;
          break;
        }

        // Execute tool calls
        const toolResults: Anthropic.Beta.Messages.BetaToolResultBlockParam[] = [];

        for (const toolUse of toolUseBlocks) {
          if (toolUse.name === 'computer') {
            const result = await this.executeComputerAction(toolUse.input as Record<string, unknown>);

            // Extract links after EVERY action (not just clicks)
            const linkInfo = await this.extractAndFormatLinks();

            // Add link info to the result
            const resultWithLinks = linkInfo
              ? [...(Array.isArray(result) ? result : []), { type: 'text' as const, text: linkInfo }]
              : result;

            toolResults.push({
              type: 'tool_result',
              tool_use_id: toolUse.id,
              content: resultWithLinks as Anthropic.Beta.Messages.BetaToolResultBlockParam['content'],
            });
          } else if (toolUse.name === 'goto_url') {
            // Handle goto_url tool
            const input = toolUse.input as { url: string };
            const result = await this.executeGotoUrl(input.url);
            toolResults.push({
              type: 'tool_result',
              tool_use_id: toolUse.id,
              content: result as Anthropic.Beta.Messages.BetaToolResultBlockParam['content'],
            });
          }
        }

        // Add tool results to messages
        messages.push({ role: 'user', content: toolResults });

        // Log action
        output.debug.action_log.push({
          step: 'open',
          input: `Iteration ${iteration}`,
          output: `${toolUseBlocks.length} actions executed`,
          ms: Date.now() - startTime,
        });

        // Check stop condition
        if (response.stop_reason === 'end_turn' && toolUseBlocks.length === 0) {
          done = true;
        }
      }

      // Parse final result
      if (finalResult) {
        this.parseResult(finalResult, output);
      }

      // Set official URL
      const state = await this.browser.getState();
      if (input.known_url) {
        output.official_url = input.known_url;
        output.official_domain = new URL(input.known_url).hostname;
      } else {
        output.official_url = state.url;
        output.official_domain = new URL(state.url).hostname;
      }

      // Record visited URLs
      output.debug.visited_urls.push(state.url);

      // Record downloaded files and auto-map to output fields
      const downloads = this.browser.getDownloadedFiles();
      for (const download of downloads) {
        output.debug.downloaded_files.push({
          url: download.originalUrl,
          path: download.localPath,
          content_type: download.filename.endsWith('.pdf') ? 'application/pdf' : null,
          bytes: null,
        });

        // Auto-map downloads to document fields based on filename
        const filename = download.filename.toLowerCase();
        const url = download.originalUrl;
        const urlLower = url.toLowerCase();

        // Floor plan / Hall plan / Geländeplan / Site plan
        const isFloorplan = (
          filename.includes('gelände') || filename.includes('gelande') ||
          filename.includes('floor') || filename.includes('hall') ||
          filename.includes('site') || filename.includes('hallen') ||
          (filename.includes('plan') && !filename.includes('richtlin') && !filename.includes('techni')) ||
          filename.includes('map') || filename.includes('overview') ||
          urlLower.includes('gelaende') || urlLower.includes('floorplan') ||
          urlLower.includes('hallenplan') || urlLower.includes('siteplan')
        ) && !filename.includes('richtlin') && !filename.includes('techni') && !filename.includes('guideline');

        if (isFloorplan && !output.documents.floorplan_url) {
          output.documents.floorplan_url = url;
          output.quality.floorplan = 'strong';
          output.primary_reasoning.floorplan = `Auto-detected from download: ${download.filename}`;
        }

        // Technical Guidelines / Richtlinien / Regulations
        const isRules = (
          filename.includes('richtlin') || filename.includes('guideline') ||
          filename.includes('techni') || filename.includes('regulation') ||
          filename.includes('vorschrift') || filename.includes('regel') ||
          filename.includes('construction') || filename.includes('standbau') ||
          urlLower.includes('richtlin') || urlLower.includes('guideline') ||
          urlLower.includes('technical')
        );

        if (isRules && !output.documents.rules_url) {
          output.documents.rules_url = url;
          output.quality.rules = 'strong';
          output.primary_reasoning.rules = `Auto-detected from download: ${download.filename}`;
        }

        // Exhibitor Manual / Service Documentation / Verkehrsleitfaden / Handbuch
        const isManual = (
          filename.includes('manual') || filename.includes('handbook') ||
          filename.includes('handbuch') || filename.includes('service') ||
          filename.includes('leitfaden') || filename.includes('verkehr') ||
          filename.includes('aussteller') || filename.includes('exhibitor') ||
          filename.includes('guide') || filename.includes('documentation') ||
          urlLower.includes('manual') || urlLower.includes('handbook') ||
          urlLower.includes('service-doc') || urlLower.includes('leitfaden')
        ) && !isRules; // Don't classify rules as manual

        if (isManual && !output.documents.exhibitor_manual_url) {
          output.documents.exhibitor_manual_url = url;
          output.quality.exhibitor_manual = 'strong';
          output.primary_reasoning.exhibitor_manual = `Auto-detected from download: ${download.filename}`;
        }

        // Schedule / Timeline / Zeitplan
        const isSchedule = (
          filename.includes('zeitplan') || filename.includes('timeline') ||
          filename.includes('schedule') || filename.includes('aufbau') ||
          filename.includes('abbau') || filename.includes('termine') ||
          filename.includes('dismantl') || filename.includes('set-up') ||
          urlLower.includes('schedule') || urlLower.includes('timeline')
        );

        if (isSchedule && !output.documents.schedule_page_url) {
          output.documents.schedule_page_url = url;
        }
      }

      output.debug.notes.push(`Agent completed in ${iteration} iterations`);
      output.debug.notes.push(`Auto-mapped ${downloads.length} downloaded files to output fields`);
      output.debug.notes.push(`Total time: ${Math.round((Date.now() - startTime) / 1000)}s`);

    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Unknown error';
      output.debug.notes.push(`Error: ${errorMsg}`);
      this.log(`Error: ${errorMsg}`);
    } finally {
      await this.browser.close();
    }

    return output;
  }

  private async extractAndFormatLinks(): Promise<string> {
    try {
      const relevantLinks = await this.browser.getRelevantLinks();
      let linkInfo = '';

      if (relevantLinks.pdfLinks.length > 0) {
        linkInfo += '\n\n📄 PDF LINKS OP DEZE PAGINA:\n';
        for (const link of relevantLinks.pdfLinks.slice(0, 20)) {
          linkInfo += `• ${link.text || 'PDF'}: ${link.url}\n`;
        }
      }

      if (relevantLinks.exhibitorLinks.length > 0) {
        linkInfo += '\n\n🔗 RELEVANTE LINKS:\n';
        for (const link of relevantLinks.exhibitorLinks.slice(0, 15)) {
          linkInfo += `• ${link.text}: ${link.url}\n`;
        }
      }

      // Also show download links if different from PDFs
      const downloadOnlyLinks = relevantLinks.downloadLinks.filter(
        dl => !relevantLinks.pdfLinks.some(pdf => pdf.url === dl.url)
      );
      if (downloadOnlyLinks.length > 0) {
        linkInfo += '\n\n📥 DOWNLOAD LINKS:\n';
        for (const link of downloadOnlyLinks.slice(0, 10)) {
          linkInfo += `• ${link.text}: ${link.url}\n`;
        }
      }

      return linkInfo;
    } catch {
      return '';
    }
  }

  private async executeGotoUrl(url: string): Promise<Anthropic.Beta.Messages.BetaToolResultBlockParam['content']> {
    this.log(`Navigating to: ${url}`);

    try {
      await this.browser.goto(url);
      await new Promise(resolve => setTimeout(resolve, 1000));

      // Take screenshot and extract links
      const screenshot = await this.browser.screenshot();
      const state = await this.browser.getState();
      const linkInfo = await this.extractAndFormatLinks();

      return [
        {
          type: 'image',
          source: {
            type: 'base64',
            media_type: 'image/png',
            data: screenshot.base64,
          },
        },
        {
          type: 'text',
          text: `Navigated to: ${state.url}\nTitle: ${state.title}${linkInfo}`,
        },
      ];
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Unknown error';
      this.log(`Navigation error: ${errorMsg}`);
      return [{ type: 'text', text: `Error navigating to ${url}: ${errorMsg}` }];
    }
  }

  private async executeComputerAction(input: Record<string, unknown>): Promise<Anthropic.Beta.Messages.BetaToolResultBlockParam['content']> {
    const action = input['action'] as string;
    this.log(`Action: ${action}`);

    try {
      switch (action) {
        case 'screenshot':
          // Just return current screenshot
          break;

        case 'mouse_move':
          await this.browser.moveMouse(
            input['coordinate'] ? (input['coordinate'] as number[])[0]! : 0,
            input['coordinate'] ? (input['coordinate'] as number[])[1]! : 0
          );
          break;

        case 'left_click':
          if (input['coordinate']) {
            const [x, y] = input['coordinate'] as number[];
            await this.browser.click(x!, y!);
          }
          break;

        case 'left_click_drag':
          if (input['start_coordinate'] && input['end_coordinate']) {
            const [sx, sy] = input['start_coordinate'] as number[];
            const [ex, ey] = input['end_coordinate'] as number[];
            await this.browser.drag(sx!, sy!, ex!, ey!);
          }
          break;

        case 'right_click':
          if (input['coordinate']) {
            const [x, y] = input['coordinate'] as number[];
            await this.browser.rightClick(x!, y!);
          }
          break;

        case 'double_click':
          if (input['coordinate']) {
            const [x, y] = input['coordinate'] as number[];
            await this.browser.doubleClick(x!, y!);
          }
          break;

        case 'type':
          if (input['text']) {
            await this.browser.type(input['text'] as string);
          }
          break;

        case 'key':
          if (input['key']) {
            const key = input['key'] as string;
            // Handle key combinations like "ctrl+a"
            if (key.includes('+')) {
              const parts = key.split('+');
              await this.browser.hotkey(...parts);
            } else {
              await this.browser.pressKey(key);
            }
          }
          break;

        case 'scroll':
          if (input['coordinate'] && input['scroll_direction']) {
            const [x, y] = input['coordinate'] as number[];
            const direction = input['scroll_direction'] as string;
            const deltaY = direction === 'down' ? 300 : direction === 'up' ? -300 : 0;
            const deltaX = direction === 'right' ? 300 : direction === 'left' ? -300 : 0;
            await this.browser.scroll(x!, y!, deltaX, deltaY);
          }
          break;

        default:
          this.log(`Unknown action: ${action}`);
      }

      // Wait a bit for the page to update
      await new Promise(resolve => setTimeout(resolve, 500));

      // Take new screenshot
      const screenshot = await this.browser.screenshot();
      const state = await this.browser.getState();
      this.log(`Current URL: ${state.url}`);

      return [
        {
          type: 'image',
          source: {
            type: 'base64',
            media_type: 'image/png',
            data: screenshot.base64,
          },
        },
        {
          type: 'text',
          text: `URL: ${state.url}\nTitle: ${state.title}`,
        },
      ];
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Unknown error';
      this.log(`Action error: ${errorMsg}`);
      return [{ type: 'text', text: `Error: ${errorMsg}` }];
    }
  }

  private parseResult(text: string, output: DiscoveryOutput): void {
    // Extract JSON from the text
    const jsonMatch = text.match(/```json\s*([\s\S]*?)\s*```/) || text.match(/\{[\s\S]*"floorplan_url"[\s\S]*\}/);

    if (!jsonMatch) {
      output.debug.notes.push('Could not parse final JSON result');
      return;
    }

    try {
      const jsonStr = jsonMatch[1] || jsonMatch[0];
      const result = JSON.parse(jsonStr);

      // Map to output structure
      if (result.floorplan_url) {
        output.documents.floorplan_url = result.floorplan_url;
        output.quality.floorplan = 'strong';
        output.primary_reasoning.floorplan = 'Found by Claude agent';
      }

      if (result.exhibitor_manual_url) {
        output.documents.exhibitor_manual_url = result.exhibitor_manual_url;
        output.quality.exhibitor_manual = 'strong';
        output.primary_reasoning.exhibitor_manual = 'Found by Claude agent';
      }

      if (result.rules_url) {
        output.documents.rules_url = result.rules_url;
        output.quality.rules = 'strong';
        output.primary_reasoning.rules = 'Found by Claude agent';
      }

      if (result.exhibitor_directory_url) {
        output.documents.exhibitor_directory_url = result.exhibitor_directory_url;
        output.quality.exhibitor_directory = 'strong';
        output.primary_reasoning.exhibitor_directory = 'Found by Claude agent';
      }

      if (result.downloads_page_url) {
        output.documents.downloads_overview_url = result.downloads_page_url;
      }

      // Parse schedule
      if (result.schedule) {
        if (result.schedule.build_up && Array.isArray(result.schedule.build_up)) {
          output.schedule.build_up = result.schedule.build_up.map((entry: { date?: string; time?: string; description?: string }) => ({
            date: entry.date || null,
            time: entry.time || null,
            description: entry.description || '',
            source_url: output.documents.exhibitor_manual_url || output.official_url || '',
          }));
        }

        if (result.schedule.tear_down && Array.isArray(result.schedule.tear_down)) {
          output.schedule.tear_down = result.schedule.tear_down.map((entry: { date?: string; time?: string; description?: string }) => ({
            date: entry.date || null,
            time: entry.time || null,
            description: entry.description || '',
            source_url: output.documents.exhibitor_manual_url || output.official_url || '',
          }));
        }

        if (output.schedule.build_up.length > 0 || output.schedule.tear_down.length > 0) {
          output.quality.schedule = 'strong';
          output.primary_reasoning.schedule = `Found ${output.schedule.build_up.length} build-up and ${output.schedule.tear_down.length} tear-down entries`;
        }
      }

      if (result.notes) {
        output.debug.notes.push(`Agent notes: ${result.notes}`);
      }

    } catch (error) {
      output.debug.notes.push(`JSON parse error: ${error}`);
    }
  }

  private log(message: string): void {
    if (this.debug) {
      const timestamp = new Date().toISOString().slice(11, 19);
      console.log(`[${timestamp}] ${message}`);
    } else {
      console.log(message);
    }
  }
}
