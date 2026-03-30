// Domain guard for preventing foreign fair contamination

// Whitelisted CDN/document hosting domains
const WHITELISTED_DOMAINS = [
  'cloudfront.net',
  's3.amazonaws.com',
  'blob.core.windows.net',
  'azureedge.net',
  'akamaized.net',
  'fastly.net',
  'cloudflare.com',
  'googleapis.com',
  'cdn.jsdelivr.net',
];

// Known third-party fair/exhibitor platforms (potentially problematic)
const THIRD_PARTY_FAIR_PLATFORMS = [
  'mapyourshow.com',
  'a2z.events',
  'a2zinc.net',
  'expocad.com',
  'gesevent.com',
  'expofp.com',
  'eventscribe.com',
  'map-dynamics.com',
  'smartcity.com',
];

// Patterns that indicate another fair's content
const FOREIGN_FAIR_PATTERNS = [
  /\bise\d{4}\b/i,
  /\bces\d{4}\b/i,
  /\bmwc\d{4}\b/i,
  /\bibc\d{4}\b/i,
];

export interface DomainCheckResult {
  allowed: boolean;
  reason: string;
  type: 'same-domain' | 'subdomain' | 'whitelisted-cdn' | 'third-party-platform' | 'foreign-fair' | 'external';
}

export function getDomain(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return '';
  }
}

export function getBaseDomain(hostname: string): string {
  // Extract base domain (e.g., "messe-frankfurt.com" from "service.messe-frankfurt.com")
  const parts = hostname.split('.');
  if (parts.length >= 2) {
    // Handle common TLDs
    const lastTwo = parts.slice(-2).join('.');
    const commonTLDs = ['.co.uk', '.com.au', '.co.jp', '.com.br'];
    if (commonTLDs.some(tld => hostname.endsWith(tld))) {
      return parts.slice(-3).join('.');
    }
    return lastTwo;
  }
  return hostname;
}

/**
 * Check if a fair name word appears as a meaningful segment in a URL.
 *
 * For short words (< 5 chars like "IRE", "ISE", "CES"), requires word-boundary
 * matching to prevent false positives (e.g., "ire" matching in "ge26ire" or "require").
 * For longer words, simple substring matching is used.
 *
 * A "word boundary" in URL context means: start/end of string, dots, hyphens,
 * underscores, slashes, or a letter→digit transition (for patterns like "ire2026").
 */
function fairNameInUrl(word: string, url: string): boolean {
  const w = word.toLowerCase();
  const u = url.toLowerCase();

  if (w.length >= 5) {
    // Long enough for safe substring matching
    return u.includes(w);
  }

  // Short word: require URL-segment boundaries
  // Matches: "ire-expo.com", "ire.mapyourshow.com", "ire2026", "/ire/"
  // Blocks: "ge26ire", "tire", "require", "fire"
  const escaped = w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`(?:^|[.\\-_/])${escaped}(?:$|[.\\-_/\\d])`, 'i');
  return pattern.test(u);
}

export function checkDomain(url: string, officialDomain: string, fairName: string): DomainCheckResult {
  const urlDomain = getDomain(url);
  const officialBase = getBaseDomain(officialDomain.toLowerCase());

  // Empty or invalid URL
  if (!urlDomain) {
    return { allowed: false, reason: 'Invalid URL', type: 'external' };
  }

  // Exact match
  if (urlDomain === officialDomain.toLowerCase()) {
    return { allowed: true, reason: 'Same domain', type: 'same-domain' };
  }

  // Subdomain match
  if (urlDomain.endsWith('.' + officialBase) || getBaseDomain(urlDomain) === officialBase) {
    return { allowed: true, reason: 'Subdomain of official domain', type: 'subdomain' };
  }

  // Whitelisted CDN domains
  for (const cdn of WHITELISTED_DOMAINS) {
    if (urlDomain.endsWith(cdn)) {
      return { allowed: true, reason: `Whitelisted CDN: ${cdn}`, type: 'whitelisted-cdn' };
    }
  }

  // Third-party fair platforms - allowed but flagged
  for (const platform of THIRD_PARTY_FAIR_PLATFORMS) {
    if (urlDomain.includes(platform)) {
      // Allow if URL contains fair name, using word-boundary matching for short names
      // to prevent false positives (e.g., "ire" in "ge26ire.mapyourshow.com")
      const urlLower = url.toLowerCase();
      const fairNameLower = fairName.toLowerCase().replace(/\s+/g, '');

      // Check full concatenated name (e.g., "ire2026")
      if (fairNameInUrl(fairNameLower, urlLower)) {
        return {
          allowed: true,
          reason: `Third-party platform (${platform}) with fair reference`,
          type: 'third-party-platform',
        };
      }

      // Check first word of fair name (e.g., "ire" from "IRE 2026")
      const firstWord = fairName.toLowerCase().split(' ')[0] ?? '';
      if (firstWord.length >= 3 && fairNameInUrl(firstWord, urlLower)) {
        return {
          allowed: true,
          reason: `Third-party platform (${platform}) with fair reference`,
          type: 'third-party-platform',
        };
      }

      return {
        allowed: false,
        reason: `Third-party platform (${platform}) without clear fair reference - potential foreign fair`,
        type: 'third-party-platform',
      };
    }
  }

  // Foreign fair pattern detection
  for (const pattern of FOREIGN_FAIR_PATTERNS) {
    if (pattern.test(url)) {
      // Check if this is the actual fair we're looking for
      const fairNameNormalized = fairName.toLowerCase().replace(/\s+/g, '');
      const checkSlice = fairNameNormalized.length >= 5 ? fairNameNormalized.slice(0, 5) : fairNameNormalized;
      if (!fairNameInUrl(checkSlice, url.toLowerCase())) {
        return {
          allowed: false,
          reason: `Matches foreign fair pattern: ${pattern.source}`,
          type: 'foreign-fair',
        };
      }
    }
  }

  // External domain - not allowed for primary results
  return {
    allowed: false,
    reason: `External domain: ${urlDomain} (official: ${officialDomain})`,
    type: 'external',
  };
}

export function isLikelyPdf(url: string): boolean {
  const lower = url.toLowerCase();
  return lower.endsWith('.pdf') || lower.includes('.pdf?') || lower.includes('/pdf/');
}

export function isLikelyDocument(url: string): boolean {
  const lower = url.toLowerCase();
  return (
    isLikelyPdf(url) ||
    lower.endsWith('.doc') ||
    lower.endsWith('.docx') ||
    lower.endsWith('.xls') ||
    lower.endsWith('.xlsx')
  );
}
