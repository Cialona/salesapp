/**
 * Claude Computer Use Agent for Trade Fair Discovery
 *
 * This agent uses Claude's Computer Use capability to navigate
 * trade fair websites and find exhibitor information.
 */

import Anthropic from '@anthropic-ai/sdk';
import { BrowserController } from './browser-controller.js';
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
2. **Exhibitor Manual / Handbook** - Handleiding voor exposanten (PDF)
   - Ook: "Service Documentation", "Exhibitor Guide", "Ausstellerhandbuch"
3. **Technical Guidelines / Rules** - Technische voorschriften voor standbouw (PDF)
   - Vaak een apart document van de beursorganisator (Messe Frankfurt, Messe München, etc.)
4. **Build-up & Tear-down Schedule** - ALLE opbouw en afbouw datums met exacte tijden
5. **Exhibitor Directory** - Lijst/zoekmachine voor exposanten

=== STRATEGIE (VOLG EXACT!) ===

STAP 1: Navigeer naar de Exhibitor/Aussteller sectie
- Zoek in menu: "For Exhibitors", "Exhibitors", "Ausstellen", "Planning & Preparation"
- Klik door naar subsecties

STAP 2: Vind het Download Center
- Zoek: "Downloads", "Documents", "Service Documentation", "Downloadcenter"
- Dit is waar de meeste PDFs staan

STAP 3: Vind Set-up/Tear-down informatie
- Zoek specifiek naar: "Set-up and dismantling", "Aufbau und Abbau", "Build-up"
- Hier staan de exacte datums en tijden
- Noteer ALLE datums (advanced set-up, regular set-up, dismantling)

STAP 4: Vind de PDF URLs
- BELANGRIJK: Hover over links om de echte URL te zien
- PDF URLs bevatten vaak: /content/dam/, /media/, /asset/, cloudfront.net, /documents/
- Noteer de VOLLEDIGE URL inclusief .pdf extensie

STAP 5: Check gerelateerde sites
- Messe Frankfurt: check ook andere subdomeinen voor Technical Guidelines
- De Technical Guidelines zijn vaak een algemeen document van de beursorganisator

STAP 6: Vind de Exhibitor Directory
- Zoek: "Exhibitor Search", "Find Exhibitors", "Exhibitor List"
- Vaak een apart subdomein: exhibitors.beursnaam.de of online.beursnaam.com

=== PDF URL HERKENNING ===

Echte PDF URLs zien er zo uit:
✅ https://ambiente.messefrankfurt.com/content/dam/.../document.pdf
✅ https://d2n1n6byqxibyi.cloudfront.net/asset/.../document.pdf
✅ https://messe-berlinprod-media.e-spirit.cloud/.../document.pdf

NIET zo:
❌ "Download PDF" (dit is een linktekst, geen URL)
❌ "document.pdf (500 KB)" (dit bevat extra tekst)

=== SCHEDULE FORMAT ===

Voor build-up en tear-down, geef ALLE datums:
- Advanced set-up (vroege opbouw, vaak tegen betaling)
- Regular set-up (normale opbouw)
- Dismantling/Tear-down (afbouw)

Inclusief:
- Exacte datum (YYYY-MM-DD)
- Tijden (HH:MM-HH:MM)
- Beschrijving (wat mag wanneer)

=== OUTPUT FORMAT ===

Geef je resultaten als JSON:
\`\`\`json
{
  "floorplan_url": "https://volledig-pad-naar-bestand.pdf",
  "exhibitor_manual_url": "https://volledig-pad-naar-bestand.pdf",
  "rules_url": "https://volledig-pad-naar-bestand.pdf",
  "exhibitor_directory_url": "https://url-naar-exposantenlijst",
  "downloads_page_url": "https://url-naar-downloadcenter",
  "schedule": {
    "build_up": [
      {"date": "2026-01-29", "time": "07:00-24:00", "description": "Advanced set-up (optioneel, €550/dag)"},
      {"date": "2026-01-30", "time": "07:00-24:00", "description": "Advanced set-up"},
      {"date": "2026-01-31", "time": "07:00-24:00", "description": "Regular set-up begint"},
      {"date": "2026-02-01", "time": "07:00-24:00", "description": "Regular set-up"}
    ],
    "tear_down": [
      {"date": "2026-02-10", "time": "17:00-20:00", "description": "Afbouw start, alleen binnen stands"},
      {"date": "2026-02-10", "time": "20:30-24:00", "description": "Voertuigen toegestaan"},
      {"date": "2026-02-11", "time": "07:00-21:00", "description": "Doorlopende afbouw"}
    ]
  },
  "notes": "Gedetailleerde beschrijving van je zoekpad en wat je vond"
}
\`\`\`

Gebruik null ALLEEN als je het echt niet kunt vinden na grondig zoeken.
Begin nu met navigeren!`;

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
            toolResults.push({
              type: 'tool_result',
              tool_use_id: toolUse.id,
              content: result,
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

      // Record downloaded files
      const downloads = this.browser.getDownloadedFiles();
      for (const filepath of downloads) {
        output.debug.downloaded_files.push({
          url: filepath,
          path: filepath,
          content_type: filepath.endsWith('.pdf') ? 'application/pdf' : null,
          bytes: null,
        });
      }

      output.debug.notes.push(`Agent completed in ${iteration} iterations`);
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
