import * as cheerio from 'cheerio';

export interface ExtractedLink {
  href: string;
  text: string;
  context: string;
}

export interface ExtractedPage {
  title: string;
  text: string;
  links: ExtractedLink[];
}

export function extractFromHtml(html: string, baseUrl: string): ExtractedPage {
  const $ = cheerio.load(html);

  // Remove scripts, styles, and hidden elements
  $('script, style, noscript, iframe, svg').remove();
  $('[style*="display:none"], [style*="display: none"], .hidden, [hidden]').remove();

  // Get title
  const title = $('title').text().trim() ||
    $('h1').first().text().trim() ||
    $('meta[property="og:title"]').attr('content') ||
    '';

  // Get main text content
  const textParts: string[] = [];
  $('body').find('p, h1, h2, h3, h4, h5, h6, li, td, th, span, div').each((_, el) => {
    const text = $(el).clone().children().remove().end().text().trim();
    if (text && text.length > 2) {
      textParts.push(text);
    }
  });
  const text = textParts.join(' ').replace(/\s+/g, ' ').slice(0, 50000);

  // Extract links with context
  const links: ExtractedLink[] = [];
  const seenHrefs = new Set<string>();

  $('a[href]').each((_, el) => {
    const $el = $(el);
    const href = $el.attr('href');
    if (!href) return;

    // Resolve relative URLs
    let absoluteUrl: string;
    try {
      absoluteUrl = new URL(href, baseUrl).href;
    } catch {
      return;
    }

    // Skip non-http URLs, anchors, and duplicates
    if (!absoluteUrl.startsWith('http')) return;
    if (seenHrefs.has(absoluteUrl)) return;
    seenHrefs.add(absoluteUrl);

    const linkText = $el.text().trim();
    const parent = $el.parent();
    const context = parent.text().trim().slice(0, 200);

    links.push({
      href: absoluteUrl,
      text: linkText,
      context,
    });
  });

  return { title, text, links };
}

// Keywords for different field types
export const FIELD_KEYWORDS = {
  floorplan: [
    'floor plan', 'floorplan', 'hall plan', 'hallenplan', 'plattegrond',
    'site map', 'venue map', 'layout', 'stand location', 'exhibition layout',
  ],
  exhibitor_manual: [
    'exhibitor manual', 'exhibitor handbook', 'exhibitor guide', 'service manual',
    'technical manual', 'ausstellerhandbuch', 'exhibitor kit', 'participation guide',
    'technical handbook', 'exhibitor information',
  ],
  rules: [
    'regulations', 'rules', 'guidelines', 'technical guidelines', 'construction rules',
    'stand construction', 'technical regulations', 'safety regulations', 'exhibitor rules',
    'richtlinien', 'vorschriften', 'terms and conditions',
  ],
  schedule: [
    'build-up', 'buildup', 'set-up', 'setup', 'move-in', 'move in', 'installation',
    'tear-down', 'teardown', 'dismantling', 'move-out', 'move out', 'removal',
    'aufbau', 'abbau', 'aufbauzeit', 'abbauzeit', 'opbouw', 'afbouw',
    'montage', 'démontage', 'opening hours', 'schedule', 'timetable', 'timing',
  ],
  exhibitor_directory: [
    'exhibitor list', 'exhibitor directory', 'exhibitor search', 'find exhibitor',
    'exhibitors', 'list of exhibitors', 'ausstellerliste', 'aussteller suchen',
    'company directory', 'exhibitor catalogue', 'exhibitor catalog', 'who exhibits',
  ],
  downloads: [
    'download', 'downloads', 'download center', 'download centre', 'documents',
    'document center', 'document centre', 'files', 'resources', 'media center',
    'press kit', 'materialien', 'unterlagen',
  ],
};

export function matchesField(text: string, field: keyof typeof FIELD_KEYWORDS): boolean {
  const lowerText = text.toLowerCase();
  return FIELD_KEYWORDS[field].some(kw => lowerText.includes(kw.toLowerCase()));
}

export function scoreTextForField(text: string, field: keyof typeof FIELD_KEYWORDS): number {
  const lowerText = text.toLowerCase();
  let score = 0;

  for (const keyword of FIELD_KEYWORDS[field]) {
    if (lowerText.includes(keyword.toLowerCase())) {
      score += 10;
      // Bonus for exact phrase match
      if (lowerText.includes(keyword.toLowerCase())) {
        score += 5;
      }
    }
  }

  return Math.min(score, 100);
}

// Extract snippet around a keyword match
export function extractSnippet(text: string, keywords: string[], maxLength = 300): string | null {
  const lowerText = text.toLowerCase();

  for (const keyword of keywords) {
    const index = lowerText.indexOf(keyword.toLowerCase());
    if (index !== -1) {
      const start = Math.max(0, index - 100);
      const end = Math.min(text.length, index + keyword.length + 200);
      let snippet = text.slice(start, end).trim();

      if (start > 0) snippet = '...' + snippet;
      if (end < text.length) snippet = snippet + '...';

      return snippet.replace(/\s+/g, ' ').slice(0, maxLength);
    }
  }

  return null;
}
