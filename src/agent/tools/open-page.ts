import { chromium, type Browser, type Page } from 'playwright';
import { cache } from '../../cache/manager.js';
import { rateLimitedWait } from '../../utils/rate-limit.js';
import { extractFromHtml, type ExtractedPage } from '../../utils/text-extract.js';
import type { Logger } from '../../utils/logger.js';

let browser: Browser | null = null;

export interface OpenPageResult {
  success: boolean;
  url: string;
  finalUrl: string;
  status: number;
  extracted: ExtractedPage | null;
  html: string | null;
  error?: string;
  fromCache: boolean;
}

export interface OpenPageOptions {
  logger?: Logger;
  useCache?: boolean;
  timeout?: number;
}

async function ensureBrowser(): Promise<Browser> {
  if (!browser) {
    browser = await chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });
  }
  return browser;
}

export async function closeBrowser(): Promise<void> {
  if (browser) {
    await browser.close();
    browser = null;
  }
}

export async function openPage(
  url: string,
  options: OpenPageOptions = {}
): Promise<OpenPageResult> {
  const { logger, useCache = true, timeout = 30000 } = options;
  const startTime = Date.now();

  // Check cache first
  if (useCache) {
    const cached = cache.getCachedPage(url);
    if (cached) {
      const extracted = extractFromHtml(cached, url);
      logger?.add('open', url, 'From cache', Date.now() - startTime);
      return {
        success: true,
        url,
        finalUrl: url,
        status: 200,
        extracted,
        html: cached,
        fromCache: true,
      };
    }
  }

  // Rate limit before request
  await rateLimitedWait(url);

  let page: Page | null = null;

  try {
    const browserInstance = await ensureBrowser();
    page = await browserInstance.newPage();

    // Set reasonable viewport and user agent
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.setExtraHTTPHeaders({
      'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',
    });

    // Navigate with timeout
    const response = await page.goto(url, {
      waitUntil: 'domcontentloaded',
      timeout,
    });

    const status = response?.status() ?? 0;
    const finalUrl = page.url();

    // Check for blocked/error status
    if (status >= 400) {
      logger?.add('open', url, `HTTP ${status}`, Date.now() - startTime);
      return {
        success: false,
        url,
        finalUrl,
        status,
        extracted: null,
        html: null,
        error: `HTTP ${status}`,
        fromCache: false,
      };
    }

    // Wait a bit for dynamic content
    await page.waitForTimeout(1000);

    // Get HTML content
    const html = await page.content();

    // Extract useful content
    const extracted = extractFromHtml(html, finalUrl);

    // Cache the result
    if (useCache && status === 200) {
      cache.savePage(url, html, status);
    }

    logger?.add('open', url, `OK (${extracted.links.length} links)`, Date.now() - startTime);

    return {
      success: true,
      url,
      finalUrl,
      status,
      extracted,
      html,
      fromCache: false,
    };
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : 'Unknown error';

    // Detect bot protection patterns
    let reason = errorMsg;
    if (errorMsg.includes('timeout')) {
      reason = 'Timeout - possible bot protection';
    } else if (errorMsg.includes('net::ERR_')) {
      reason = 'Network error';
    }

    logger?.add('open', url, `Error: ${reason}`, Date.now() - startTime);

    return {
      success: false,
      url,
      finalUrl: url,
      status: 0,
      extracted: null,
      html: null,
      error: reason,
      fromCache: false,
    };
  } finally {
    if (page) {
      await page.close().catch(() => {});
    }
  }
}

// Find high-value links on a page
export function findHighValueLinks(
  extracted: ExtractedPage,
  officialDomain: string
): {
  exhibitorLinks: Array<{ href: string; text: string }>;
  downloadLinks: Array<{ href: string; text: string }>;
  pdfLinks: Array<{ href: string; text: string }>;
} {
  const exhibitorKeywords = ['exhibitor', 'aussteller', 'for exhibitors', 'services', 'teilnehmer'];
  const downloadKeywords = ['download', 'documents', 'dokumente', 'materialien', 'files', 'resources'];

  const exhibitorLinks: Array<{ href: string; text: string }> = [];
  const downloadLinks: Array<{ href: string; text: string }> = [];
  const pdfLinks: Array<{ href: string; text: string }> = [];

  for (const link of extracted.links) {
    const lowerText = link.text.toLowerCase();
    const lowerHref = link.href.toLowerCase();

    // Check if on same domain or subdomain
    try {
      const linkDomain = new URL(link.href).hostname;
      const isOnDomain = linkDomain === officialDomain ||
        linkDomain.endsWith('.' + officialDomain);

      if (!isOnDomain) continue;
    } catch {
      continue;
    }

    // Categorize links
    if (lowerHref.endsWith('.pdf')) {
      pdfLinks.push({ href: link.href, text: link.text });
    }

    if (exhibitorKeywords.some(kw => lowerText.includes(kw) || lowerHref.includes(kw))) {
      exhibitorLinks.push({ href: link.href, text: link.text });
    }

    if (downloadKeywords.some(kw => lowerText.includes(kw) || lowerHref.includes(kw))) {
      downloadLinks.push({ href: link.href, text: link.text });
    }
  }

  return { exhibitorLinks, downloadLinks, pdfLinks };
}
