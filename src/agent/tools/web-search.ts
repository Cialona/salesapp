import type { Logger } from '../../utils/logger.js';

export interface SearchResult {
  url: string;
  title: string;
  snippet: string;
}

export interface WebSearchOptions {
  maxResults?: number;
  logger?: Logger;
}

// Simple web search using DuckDuckGo HTML (no API key needed)
// In production, you'd use a proper search API
export async function webSearch(
  query: string,
  options: WebSearchOptions = {}
): Promise<SearchResult[]> {
  const { maxResults = 10, logger } = options;
  const startTime = Date.now();

  try {
    // Use DuckDuckGo HTML search (more reliable than Lite)
    const encodedQuery = encodeURIComponent(query);
    const url = `https://html.duckduckgo.com/html/?q=${encodedQuery}`;

    const response = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
      },
    });

    if (!response.ok) {
      logger?.add('search', query, `HTTP ${response.status}`, Date.now() - startTime);
      return [];
    }

    const html = await response.text();
    const results = parseSearchResults(html, maxResults);

    logger?.add('search', query, `Found ${results.length} results`, Date.now() - startTime);
    return results;
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : 'Unknown error';
    logger?.add('search', query, `Error: ${errorMsg}`, Date.now() - startTime);
    return [];
  }
}

function parseSearchResults(html: string, maxResults: number): SearchResult[] {
  const results: SearchResult[] = [];

  // DuckDuckGo HTML format: results are in <a class="result__a"> tags
  // with snippet in <a class="result__snippet">
  const resultPattern = /<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)<\/a>/gi;
  const snippetPattern = /<a[^>]*class="result__snippet"[^>]*>([^<]*(?:<[^>]*>[^<]*)*)<\/a>/gi;

  let match;
  const urls: string[] = [];
  const titles: string[] = [];

  while ((match = resultPattern.exec(html)) !== null) {
    let url = match[1] ?? '';
    const title = match[2]?.trim() ?? '';

    // DuckDuckGo wraps URLs in redirect
    if (url.includes('uddg=')) {
      const decoded = decodeURIComponent(url.split('uddg=')[1] ?? '');
      url = decoded.split('&')[0] ?? url;
    }

    // Skip ads and invalid URLs
    if (!url.startsWith('http') || url.includes('duckduckgo.com')) {
      continue;
    }

    urls.push(url);
    titles.push(title);
  }

  // Extract snippets
  const snippets: string[] = [];
  while ((match = snippetPattern.exec(html)) !== null) {
    const snippet = (match[1] ?? '')
      .replace(/<[^>]*>/g, '')
      .replace(/&[^;]+;/g, ' ')
      .trim();
    snippets.push(snippet);
  }

  // Combine results
  for (let i = 0; i < Math.min(urls.length, maxResults); i++) {
    results.push({
      url: urls[i]!,
      title: titles[i] ?? '',
      snippet: snippets[i] ?? '',
    });
  }

  return results;
}

// Generate search queries for different fields
export function generateSearchQueries(fairName: string, city?: string, country?: string): Record<string, string[]> {
  const location = [city, country].filter(Boolean).join(' ');
  const base = location ? `"${fairName}" ${location}` : `"${fairName}"`;

  return {
    official: [
      `${base} official website`,
      `${base} messe fair exhibition`,
    ],
    exhibitor: [
      `${base} exhibitor information`,
      `${base} for exhibitors`,
    ],
    manual: [
      `${base} exhibitor manual PDF`,
      `${base} exhibitor handbook download`,
    ],
    downloads: [
      `${base} download center documents`,
      `${base} exhibitor downloads PDF`,
    ],
    floorplan: [
      `${base} floor plan hall plan`,
      `${base} venue map layout`,
    ],
    schedule: [
      `${base} build-up tear-down schedule`,
      `${base} setup dismantling times`,
    ],
    directory: [
      `${base} exhibitor list directory`,
      `${base} exhibitors search`,
    ],
  };
}
