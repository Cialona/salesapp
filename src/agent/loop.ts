import {
  type DiscoveryOutput,
  type TestCaseInput,
  type FieldName,
  type BlockedUrl,
  FIELD_NAMES,
  createEmptyOutput,
} from '../schemas/output.js';
import { createLogger, type Logger } from '../utils/logger.js';
import { checkDomain, getDomain, isLikelyPdf } from '../guards/domain.js';
import {
  webSearch,
  generateSearchQueries,
  type SearchResult,
} from './tools/web-search.js';
import { openPage, closeBrowser, findHighValueLinks, type OpenPageResult } from './tools/open-page.js';
import { downloadFile, toDownloadedFile } from './tools/download-file.js';
import { parsePdf } from './tools/parse-pdf.js';
import { extractScheduleFromText, hasScheduleInfo } from './tools/extract-schedule.js';
import {
  scoreCandidate,
  selectBest,
  toOutputCandidates,
  type ScoredCandidate,
} from '../scoring/candidates.js';
import { matchesField, FIELD_KEYWORDS, extractSnippet } from '../utils/text-extract.js';

// Hard limits
const MAX_PAGE_OPENS = 30;
const MAX_DOWNLOADS = 15;
const MAX_RUNTIME_MS = 10 * 60 * 1000; // 10 minutes

type AgentState = 'SEARCH' | 'ENTRY' | 'DOWNLOADS' | 'PDF_PARSE' | 'SELECT' | 'DONE';

interface AgentContext {
  input: TestCaseInput;
  output: DiscoveryOutput;
  logger: Logger;
  startTime: number;

  // State tracking
  state: AgentState;
  pageOpens: number;
  downloads: number;

  // Discovered URLs
  officialUrl: string | null;
  officialDomain: string | null;
  entryPages: string[];
  downloadCenterUrl: string | null;
  pdfUrls: string[];

  // Candidates per field
  candidates: Record<FieldName, ScoredCandidate[]>;

  // Blocked URLs
  blockedUrls: BlockedUrl[];
}

export async function runDiscovery(input: TestCaseInput): Promise<DiscoveryOutput> {
  const ctx: AgentContext = {
    input,
    output: createEmptyOutput(input.fair_name),
    logger: createLogger(),
    startTime: Date.now(),

    state: 'SEARCH',
    pageOpens: 0,
    downloads: 0,

    officialUrl: null,
    officialDomain: null,
    entryPages: [],
    downloadCenterUrl: null,
    pdfUrls: [],

    candidates: {
      floorplan: [],
      exhibitor_manual: [],
      rules: [],
      schedule: [],
      exhibitor_directory: [],
    },

    blockedUrls: [],
  };

  // Set known values
  ctx.output.city = input.city;
  ctx.output.country = input.country;

  try {
    // Run state machine
    while (ctx.state !== 'DONE' && !isOverLimit(ctx)) {
      ctx.logger.note(`State: ${ctx.state}`);

      switch (ctx.state) {
        case 'SEARCH':
          await runSearchState(ctx);
          break;
        case 'ENTRY':
          await runEntryState(ctx);
          break;
        case 'DOWNLOADS':
          await runDownloadsState(ctx);
          break;
        case 'PDF_PARSE':
          await runPdfParseState(ctx);
          break;
        case 'SELECT':
          await runSelectState(ctx);
          break;
      }
    }
  } finally {
    await closeBrowser();
  }

  // Finalize output
  ctx.output.debug.action_log = ctx.logger.log;
  ctx.output.debug.notes = ctx.logger.notes;
  ctx.output.debug.blocked_urls = ctx.blockedUrls;

  // Generate email draft if needed
  ctx.output.email_draft_if_missing = generateEmailDraft(ctx.output);

  return ctx.output;
}

function isOverLimit(ctx: AgentContext): boolean {
  const elapsed = Date.now() - ctx.startTime;

  if (elapsed > MAX_RUNTIME_MS) {
    ctx.logger.note(`Runtime limit reached (${Math.round(elapsed / 1000)}s)`);
    return true;
  }

  if (ctx.pageOpens >= MAX_PAGE_OPENS) {
    ctx.logger.note(`Page opens limit reached (${ctx.pageOpens})`);
    return true;
  }

  if (ctx.downloads >= MAX_DOWNLOADS) {
    ctx.logger.note(`Downloads limit reached (${ctx.downloads})`);
    return true;
  }

  return false;
}

// ============================================================================
// STATE: SEARCH
// Find official URL and initial entry points
// ============================================================================

async function runSearchState(ctx: AgentContext): Promise<void> {
  // If known_url provided, verify it
  if (ctx.input.known_url) {
    ctx.logger.note(`Using known URL: ${ctx.input.known_url}`);
    const result = await openPage(ctx.input.known_url, { logger: ctx.logger });
    ctx.pageOpens++;
    ctx.output.debug.visited_urls.push(ctx.input.known_url);

    if (result.success && result.extracted) {
      // Verify it's the right fair by checking title/content
      const titleLower = result.extracted.title.toLowerCase();
      const fairNameLower = ctx.input.fair_name.toLowerCase();
      const fairNameFirst = fairNameLower.split(' ')[0] ?? fairNameLower;

      if (titleLower.includes(fairNameFirst) || titleLower.includes(fairNameLower)) {
        ctx.officialUrl = result.finalUrl;
        ctx.officialDomain = getDomain(result.finalUrl);
        ctx.output.official_url = ctx.officialUrl;
        ctx.output.official_domain = ctx.officialDomain;
        ctx.entryPages.push(result.finalUrl);

        // Extract high-value links
        const links = findHighValueLinks(result.extracted, ctx.officialDomain);
        ctx.entryPages.push(...links.exhibitorLinks.map(l => l.href).slice(0, 5));
        ctx.pdfUrls.push(...links.pdfLinks.map(l => l.href).slice(0, 5));

        if (links.downloadLinks.length > 0) {
          ctx.downloadCenterUrl = links.downloadLinks[0]!.href;
        }
      } else {
        ctx.logger.note(`Known URL title doesn't match fair name: "${result.extracted.title}"`);
      }
    } else {
      ctx.blockedUrls.push({
        url: ctx.input.known_url,
        status: result.status,
        reason: result.error ?? 'Failed to open',
      });
    }
  }

  // Generate search queries
  const queries = generateSearchQueries(ctx.input.fair_name, ctx.input.city ?? undefined, ctx.input.country ?? undefined);

  // If no official URL yet, search for it
  if (!ctx.officialUrl) {
    // Search for official site
    for (const query of queries.official ?? []) {
      const results = await webSearch(query, { logger: ctx.logger, maxResults: 5 });

      for (const result of results) {
        // Skip if already visited
        if (ctx.output.debug.visited_urls.includes(result.url)) continue;

        // Check if this looks like the official site
        const titleLower = result.title.toLowerCase();
        const fairNameFirst = ctx.input.fair_name.toLowerCase().split(' ')[0] ?? '';

        if (titleLower.includes(fairNameFirst)) {
          // Verify by opening
          const pageResult = await openPage(result.url, { logger: ctx.logger });
          ctx.pageOpens++;
          ctx.output.debug.visited_urls.push(result.url);

          if (pageResult.success) {
            ctx.officialUrl = pageResult.finalUrl;
            ctx.officialDomain = getDomain(pageResult.finalUrl);
            ctx.output.official_url = ctx.officialUrl;
            ctx.output.official_domain = ctx.officialDomain;
            ctx.entryPages.push(pageResult.finalUrl);

            if (pageResult.extracted) {
              const links = findHighValueLinks(pageResult.extracted, ctx.officialDomain);
              ctx.entryPages.push(...links.exhibitorLinks.map(l => l.href).slice(0, 5));
              ctx.pdfUrls.push(...links.pdfLinks.map(l => l.href).slice(0, 5));

              if (links.downloadLinks.length > 0) {
                ctx.downloadCenterUrl = links.downloadLinks[0]!.href;
              }
            }
            break;
          }
        }
      }

      if (ctx.officialUrl) break;
    }
  }

  // Also search for specific resources
  if (ctx.officialDomain) {
    const searchTerms = [
      { queries: queries.manual, field: 'exhibitor_manual' as FieldName },
      { queries: queries.downloads, field: 'exhibitor_manual' as FieldName },
      { queries: queries.floorplan, field: 'floorplan' as FieldName },
      { queries: queries.directory, field: 'exhibitor_directory' as FieldName },
    ];

    for (const { queries: qs, field } of searchTerms) {
      for (const query of qs ?? []) {
        const results = await webSearch(query, { logger: ctx.logger, maxResults: 3 });

        for (const result of results) {
          // Check domain
          const domainCheck = checkDomain(result.url, ctx.officialDomain, ctx.input.fair_name);
          if (!domainCheck.allowed) {
            if (domainCheck.type === 'foreign-fair') {
              ctx.blockedUrls.push({
                url: result.url,
                status: null,
                reason: domainCheck.reason,
              });
            }
            continue;
          }

          // Score as candidate
          const candidate: ScoredCandidate = scoreCandidate({
            url: result.url,
            title: result.title,
            contentSnippet: result.snippet,
            source: 'link',
          }, field);

          ctx.candidates[field].push(candidate);

          // If it's a PDF, add to download list
          if (isLikelyPdf(result.url)) {
            ctx.pdfUrls.push(result.url);
          }
        }
      }
    }
  }

  ctx.state = ctx.officialUrl ? 'ENTRY' : 'SELECT';
}

// ============================================================================
// STATE: ENTRY
// Explore entry pages to find exhibitor sections and download centers
// ============================================================================

async function runEntryState(ctx: AgentContext): Promise<void> {
  if (!ctx.officialDomain) {
    ctx.state = 'SELECT';
    return;
  }

  const pagesToVisit = [...new Set(ctx.entryPages)].slice(0, 5);

  for (const url of pagesToVisit) {
    if (isOverLimit(ctx)) break;
    if (ctx.output.debug.visited_urls.includes(url)) continue;

    const result = await openPage(url, { logger: ctx.logger });
    ctx.pageOpens++;
    ctx.output.debug.visited_urls.push(url);

    if (!result.success || !result.extracted) {
      if (result.status === 403 || result.status === 401) {
        ctx.blockedUrls.push({
          url,
          status: result.status,
          reason: 'Access denied',
        });
      }
      continue;
    }

    // Look for relevant links
    for (const link of result.extracted.links) {
      const domainCheck = checkDomain(link.href, ctx.officialDomain, ctx.input.fair_name);
      if (!domainCheck.allowed) continue;

      const linkLower = (link.text + ' ' + link.href).toLowerCase();

      // Detect download center
      if (matchesField(linkLower, 'downloads') && !ctx.downloadCenterUrl) {
        ctx.downloadCenterUrl = link.href;
        ctx.output.documents.downloads_overview_url = link.href;
      }

      // Detect exhibitor directory
      if (matchesField(linkLower, 'exhibitor_directory')) {
        const candidate = scoreCandidate({
          url: link.href,
          title: link.text,
          contentSnippet: link.context,
          source: 'link',
        }, 'exhibitor_directory');
        ctx.candidates.exhibitor_directory.push(candidate);
      }

      // Detect floorplan
      if (matchesField(linkLower, 'floorplan')) {
        const candidate = scoreCandidate({
          url: link.href,
          title: link.text,
          contentSnippet: link.context,
          source: 'link',
        }, 'floorplan');
        ctx.candidates.floorplan.push(candidate);
      }

      // Collect PDF links
      if (isLikelyPdf(link.href)) {
        ctx.pdfUrls.push(link.href);

        // Score based on link text
        for (const field of FIELD_NAMES) {
          if (field === 'schedule') continue; // Schedule from PDF content, not link

          if (matchesField(linkLower, field === 'exhibitor_manual' ? 'exhibitor_manual' : field)) {
            const candidate = scoreCandidate({
              url: link.href,
              title: link.text,
              contentSnippet: link.context,
              source: 'link',
            }, field);
            ctx.candidates[field].push(candidate);
          }
        }
      }
    }
  }

  ctx.state = 'DOWNLOADS';
}

// ============================================================================
// STATE: DOWNLOADS
// Visit download center and download PDFs
// ============================================================================

async function runDownloadsState(ctx: AgentContext): Promise<void> {
  if (!ctx.officialDomain) {
    ctx.state = 'SELECT';
    return;
  }

  // Visit download center if found
  if (ctx.downloadCenterUrl && !ctx.output.debug.visited_urls.includes(ctx.downloadCenterUrl)) {
    const result = await openPage(ctx.downloadCenterUrl, { logger: ctx.logger });
    ctx.pageOpens++;
    ctx.output.debug.visited_urls.push(ctx.downloadCenterUrl);

    if (result.success && result.extracted) {
      // Extract all PDF links from download center
      for (const link of result.extracted.links) {
        if (isLikelyPdf(link.href)) {
          const domainCheck = checkDomain(link.href, ctx.officialDomain, ctx.input.fair_name);
          if (domainCheck.allowed) {
            ctx.pdfUrls.push(link.href);

            // Pre-score based on link text
            const linkLower = link.text.toLowerCase();
            for (const field of FIELD_NAMES) {
              if (matchesField(linkLower, field === 'exhibitor_manual' ? 'exhibitor_manual' : field)) {
                const candidate = scoreCandidate({
                  url: link.href,
                  title: link.text,
                  contentSnippet: link.context,
                  source: 'link',
                }, field);
                ctx.candidates[field].push(candidate);
              }
            }
          }
        }
      }
    }
  }

  // Download PDFs (prioritize by potential relevance)
  const uniquePdfs = [...new Set(ctx.pdfUrls)];
  const toDownload = prioritizePdfs(uniquePdfs, ctx.candidates);

  for (const url of toDownload) {
    if (isOverLimit(ctx) || ctx.downloads >= MAX_DOWNLOADS) break;

    const result = await downloadFile(url, { logger: ctx.logger });
    ctx.downloads++;

    if (result.success && result.path) {
      const downloadedFile = toDownloadedFile(result);
      if (downloadedFile) {
        ctx.output.debug.downloaded_files.push(downloadedFile);
      }
    } else {
      ctx.blockedUrls.push({
        url,
        status: null,
        reason: result.error ?? 'Download failed',
      });
    }
  }

  ctx.state = 'PDF_PARSE';
}

// Prioritize PDFs that are likely to be valuable
function prioritizePdfs(urls: string[], candidates: Record<FieldName, ScoredCandidate[]>): string[] {
  const scored: Array<{ url: string; priority: number }> = [];

  // URLs that are already candidates get higher priority
  const candidateUrls = new Set(
    FIELD_NAMES.flatMap(f => candidates[f].map(c => c.url))
  );

  for (const url of urls) {
    let priority = 0;

    if (candidateUrls.has(url)) {
      priority += 100;
    }

    const urlLower = url.toLowerCase();

    // Keywords that indicate high-value PDFs
    if (/manual|handbook|guide/i.test(urlLower)) priority += 50;
    if (/regulation|guideline|rule/i.test(urlLower)) priority += 40;
    if (/exhibitor|aussteller/i.test(urlLower)) priority += 30;
    if (/floor|plan|hall/i.test(urlLower)) priority += 25;
    if (/schedule|time|datum/i.test(urlLower)) priority += 20;

    scored.push({ url, priority });
  }

  return scored
    .sort((a, b) => b.priority - a.priority)
    .slice(0, MAX_DOWNLOADS)
    .map(s => s.url);
}

// ============================================================================
// STATE: PDF_PARSE
// Parse downloaded PDFs and extract content
// ============================================================================

async function runPdfParseState(ctx: AgentContext): Promise<void> {
  for (const file of ctx.output.debug.downloaded_files) {
    if (!file.path.endsWith('.pdf')) continue;

    const parsed = await parsePdf(file.path, { logger: ctx.logger });
    if (!parsed.success) continue;

    // Score for each field based on content
    for (const field of FIELD_NAMES) {
      const keywords = FIELD_KEYWORDS[field === 'exhibitor_manual' ? 'exhibitor_manual' : field];
      const hasMatch = keywords.some(kw => parsed.text.toLowerCase().includes(kw.toLowerCase()));

      if (hasMatch) {
        const snippet = extractSnippet(parsed.text, keywords, 500);

        const candidate = scoreCandidate({
          url: file.url,
          title: parsed.title ?? file.url.split('/').pop(),
          contentSnippet: snippet ?? parsed.text.slice(0, 500),
          source: 'pdf',
        }, field);

        // Boost PDF candidates since they have actual content
        candidate.score += 20;

        ctx.candidates[field].push(candidate);
      }
    }

    // Special handling for schedule: extract actual dates/times
    if (hasScheduleInfo(parsed.text)) {
      const scheduleData = extractScheduleFromText(parsed.text, file.url, { logger: ctx.logger });

      // Merge schedule entries
      for (const entry of scheduleData.build_up) {
        if (!ctx.output.schedule.build_up.some(e => e.date === entry.date && e.time === entry.time)) {
          ctx.output.schedule.build_up.push(entry);
        }
      }

      for (const entry of scheduleData.tear_down) {
        if (!ctx.output.schedule.tear_down.some(e => e.date === entry.date && e.time === entry.time)) {
          ctx.output.schedule.tear_down.push(entry);
        }
      }

      // Mark this PDF as schedule candidate
      const snippet = scheduleData.rawMatches.slice(0, 2).map(m => m.context).join(' | ');
      const candidate = scoreCandidate({
        url: file.url,
        title: parsed.title ?? 'Schedule info from PDF',
        contentSnippet: snippet,
        source: 'pdf',
      }, 'schedule');
      candidate.score += 30; // Bonus for having actual schedule data
      ctx.candidates.schedule.push(candidate);
    }
  }

  ctx.state = 'SELECT';
}

// ============================================================================
// STATE: SELECT
// Select best candidates for each field
// ============================================================================

async function runSelectState(ctx: AgentContext): Promise<void> {
  // Select best for each field
  for (const field of FIELD_NAMES) {
    const candidates = ctx.candidates[field];
    const result = selectBest(candidates, field);

    // Update output
    if (field === 'floorplan') {
      ctx.output.documents.floorplan_url = result.url;
    } else if (field === 'exhibitor_manual') {
      ctx.output.documents.exhibitor_manual_url = result.url;
    } else if (field === 'rules') {
      ctx.output.documents.rules_url = result.url;
    } else if (field === 'schedule') {
      // Schedule URL only if no schedule entries found
      if (ctx.output.schedule.build_up.length === 0 && ctx.output.schedule.tear_down.length === 0) {
        ctx.output.documents.schedule_page_url = result.url;
      }
    } else if (field === 'exhibitor_directory') {
      ctx.output.documents.exhibitor_directory_url = result.url;
    }

    ctx.output.quality[field] = result.quality;
    ctx.output.primary_reasoning[field] = result.reasoning;
    ctx.output.evidence[field] = result.evidence;

    // Store top 3 candidates in debug
    ctx.output.debug.candidates[field] = toOutputCandidates(
      candidates.sort((a, b) => b.score - a.score).slice(0, 3)
    );
  }

  // Special: if schedule has entries, mark as strong/weak based on completeness
  if (ctx.output.schedule.build_up.length > 0 || ctx.output.schedule.tear_down.length > 0) {
    const hasDates = ctx.output.schedule.build_up.some(e => e.date) ||
      ctx.output.schedule.tear_down.some(e => e.date);

    ctx.output.quality.schedule = hasDates ? 'strong' : 'weak';
    ctx.output.primary_reasoning.schedule =
      `Found ${ctx.output.schedule.build_up.length} build-up and ${ctx.output.schedule.tear_down.length} tear-down entries. ` +
      (hasDates ? 'Dates extracted.' : 'No specific dates found.');
  }

  ctx.state = 'DONE';
}

// ============================================================================
// EMAIL DRAFT GENERATION
// ============================================================================

function generateEmailDraft(output: DiscoveryOutput): DiscoveryOutput['email_draft_if_missing'] {
  const needed: Array<'manual' | 'rules' | 'schedule' | 'floorplan' | 'directory'> = [];

  if (output.quality.exhibitor_manual === 'missing') needed.push('manual');
  if (output.quality.rules === 'missing') needed.push('rules');
  if (output.quality.schedule === 'missing') needed.push('schedule');
  if (output.quality.floorplan === 'missing') needed.push('floorplan');
  if (output.quality.exhibitor_directory === 'missing') needed.push('directory');

  if (needed.length === 0) return null;

  // Detect language from country
  const germanCountries = ['germany', 'austria', 'switzerland', 'deutschland', 'österreich', 'schweiz'];
  const isGerman = germanCountries.some(c =>
    output.country?.toLowerCase().includes(c)
  );

  const language = isGerman ? 'German' : 'English';

  const neededItems = needed.map(n => {
    switch (n) {
      case 'manual': return isGerman ? 'Ausstellerhandbuch' : 'Exhibitor Manual/Handbook';
      case 'rules': return isGerman ? 'Technische Richtlinien' : 'Technical Guidelines/Regulations';
      case 'schedule': return isGerman ? 'Aufbau- und Abbauzeiten' : 'Build-up and tear-down schedule';
      case 'floorplan': return isGerman ? 'Hallenplan' : 'Floor plan/Hall plan';
      case 'directory': return isGerman ? 'Ausstellerverzeichnis' : 'Exhibitor directory';
    }
  });

  if (isGerman) {
    return {
      needed,
      language,
      subject: `Anfrage: Ausstellerunterlagen für ${output.fair_name}`,
      body: `Sehr geehrte Damen und Herren,

wir bereiten unsere Teilnahme an der ${output.fair_name} vor und benötigen folgende Unterlagen:

${neededItems.map(item => `- ${item}`).join('\n')}

Könnten Sie uns diese Dokumente bitte per E-Mail zusenden oder uns mitteilen, wo wir diese herunterladen können?

Vielen Dank im Voraus.

Mit freundlichen Grüßen`,
    };
  }

  return {
    needed,
    language,
    subject: `Request: Exhibitor documents for ${output.fair_name}`,
    body: `Dear Sir or Madam,

We are preparing for our participation in ${output.fair_name} and require the following documents:

${neededItems.map(item => `- ${item}`).join('\n')}

Could you please send us these documents by email or let us know where we can download them?

Thank you in advance.

Best regards`,
  };
}
