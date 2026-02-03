import type { ScheduleEntry } from '../../schemas/output.js';
import type { Logger } from '../../utils/logger.js';

// Multi-language keywords for build-up and tear-down
const BUILD_UP_KEYWORDS = [
  // English
  'build-up', 'build up', 'buildup', 'set-up', 'set up', 'setup',
  'move-in', 'move in', 'movein', 'installation', 'assembly',
  'construction period', 'stand construction',
  // German
  'aufbau', 'aufbauzeit', 'aufbautage', 'einrichtung',
  // Dutch
  'opbouw', 'opbouwdagen',
  // French
  'montage', 'installation',
];

const TEAR_DOWN_KEYWORDS = [
  // English
  'tear-down', 'tear down', 'teardown', 'dismantling', 'dismantle',
  'move-out', 'move out', 'moveout', 'removal', 'breakdown',
  'stand removal',
  // German
  'abbau', 'abbauzeit', 'abbautage',
  // Dutch
  'afbouw', 'afbouwdagen',
  // French
  'démontage',
];

// Date patterns (multi-format)
const DATE_PATTERNS = [
  // DD.MM.YYYY or DD/MM/YYYY or DD-MM-YYYY
  /(\d{1,2})[./-](\d{1,2})[./-](\d{4})/g,
  // YYYY-MM-DD (ISO)
  /(\d{4})-(\d{2})-(\d{2})/g,
  // Month DD, YYYY (English)
  /(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})/gi,
  // DD Month YYYY (European)
  /(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})/gi,
];

// Time patterns
const TIME_PATTERNS = [
  // HH:MM or H:MM
  /(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)?/g,
  // HH.MM (German style)
  /(\d{1,2})\.(\d{2})\s*(Uhr|h)?/g,
  // H am/pm
  /(\d{1,2})\s*(am|pm|AM|PM)/g,
];

const MONTH_MAP: Record<string, string> = {
  january: '01', february: '02', march: '03', april: '04',
  may: '05', june: '06', july: '07', august: '08',
  september: '09', october: '10', november: '11', december: '12',
};

export interface ScheduleExtractionResult {
  build_up: ScheduleEntry[];
  tear_down: ScheduleEntry[];
  rawMatches: Array<{
    type: 'build_up' | 'tear_down';
    context: string;
    date?: string;
    time?: string;
  }>;
}

export function extractScheduleFromText(
  text: string,
  sourceUrl: string,
  options?: { logger?: Logger }
): ScheduleExtractionResult {
  const { logger } = options ?? {};
  const startTime = Date.now();

  const buildUpEntries: ScheduleEntry[] = [];
  const tearDownEntries: ScheduleEntry[] = [];
  const rawMatches: ScheduleExtractionResult['rawMatches'] = [];

  // Normalize text
  const normalizedText = text.replace(/\r\n/g, '\n').replace(/\s+/g, ' ');

  // Find build-up mentions
  for (const keyword of BUILD_UP_KEYWORDS) {
    const keywordLower = keyword.toLowerCase();
    const regex = new RegExp(`.{0,150}${escapeRegex(keywordLower)}.{0,150}`, 'gi');
    const matches = normalizedText.matchAll(regex);

    for (const match of matches) {
      const context = match[0].trim();
      const extracted = extractDateTimeFromContext(context);

      rawMatches.push({
        type: 'build_up',
        context,
        date: extracted.date ?? undefined,
        time: extracted.time ?? undefined,
      });

      // Deduplicate by date
      if (extracted.date && !buildUpEntries.some(e => e.date === extracted.date)) {
        buildUpEntries.push({
          date: extracted.date,
          time: extracted.time,
          description: context.slice(0, 200),
          source_url: sourceUrl,
        });
      } else if (!extracted.date && buildUpEntries.length === 0) {
        // Add at least one entry even without date
        buildUpEntries.push({
          date: null,
          time: extracted.time,
          description: context.slice(0, 200),
          source_url: sourceUrl,
        });
      }
    }
  }

  // Find tear-down mentions
  for (const keyword of TEAR_DOWN_KEYWORDS) {
    const keywordLower = keyword.toLowerCase();
    const regex = new RegExp(`.{0,150}${escapeRegex(keywordLower)}.{0,150}`, 'gi');
    const matches = normalizedText.matchAll(regex);

    for (const match of matches) {
      const context = match[0].trim();
      const extracted = extractDateTimeFromContext(context);

      rawMatches.push({
        type: 'tear_down',
        context,
        date: extracted.date ?? undefined,
        time: extracted.time ?? undefined,
      });

      // Deduplicate by date
      if (extracted.date && !tearDownEntries.some(e => e.date === extracted.date)) {
        tearDownEntries.push({
          date: extracted.date,
          time: extracted.time,
          description: context.slice(0, 200),
          source_url: sourceUrl,
        });
      } else if (!extracted.date && tearDownEntries.length === 0) {
        // Add at least one entry even without date
        tearDownEntries.push({
          date: null,
          time: extracted.time,
          description: context.slice(0, 200),
          source_url: sourceUrl,
        });
      }
    }
  }

  // Sort by date
  buildUpEntries.sort((a, b) => (a.date ?? '').localeCompare(b.date ?? ''));
  tearDownEntries.sort((a, b) => (a.date ?? '').localeCompare(b.date ?? ''));

  logger?.add(
    'parse',
    'extract-schedule',
    `Found ${buildUpEntries.length} build-up, ${tearDownEntries.length} tear-down entries`,
    Date.now() - startTime
  );

  return {
    build_up: buildUpEntries,
    tear_down: tearDownEntries,
    rawMatches,
  };
}

function extractDateTimeFromContext(context: string): { date: string | null; time: string | null } {
  let date: string | null = null;
  let time: string | null = null;

  // Try to extract date
  for (const pattern of DATE_PATTERNS) {
    pattern.lastIndex = 0;
    const match = pattern.exec(context);
    if (match) {
      date = parseDate(match);
      break;
    }
  }

  // Try to extract time
  for (const pattern of TIME_PATTERNS) {
    pattern.lastIndex = 0;
    const match = pattern.exec(context);
    if (match) {
      time = parseTime(match);
      break;
    }
  }

  return { date, time };
}

function parseDate(match: RegExpExecArray): string | null {
  const fullMatch = match[0];

  // ISO format YYYY-MM-DD
  if (/^\d{4}-\d{2}-\d{2}/.test(fullMatch)) {
    return fullMatch.slice(0, 10);
  }

  // DD.MM.YYYY or DD/MM/YYYY
  if (/^\d{1,2}[./-]\d{1,2}[./-]\d{4}/.test(fullMatch)) {
    const parts = fullMatch.split(/[./-]/);
    if (parts.length >= 3) {
      const day = parts[0]!.padStart(2, '0');
      const month = parts[1]!.padStart(2, '0');
      const year = parts[2]!;
      return `${year}-${month}-${day}`;
    }
  }

  // Month DD, YYYY
  const monthFirst = /^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})/i.exec(fullMatch);
  if (monthFirst) {
    const month = MONTH_MAP[monthFirst[1]!.toLowerCase()];
    const day = monthFirst[2]!.padStart(2, '0');
    const year = monthFirst[3]!;
    return `${year}-${month}-${day}`;
  }

  // DD Month YYYY
  const dayFirst = /^(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})/i.exec(fullMatch);
  if (dayFirst) {
    const day = dayFirst[1]!.padStart(2, '0');
    const month = MONTH_MAP[dayFirst[2]!.toLowerCase()];
    const year = dayFirst[3]!;
    return `${year}-${month}-${day}`;
  }

  return null;
}

function parseTime(match: RegExpExecArray): string | null {
  const fullMatch = match[0];

  // HH:MM format
  const colonFormat = /(\d{1,2}):(\d{2})\s*(am|pm)?/i.exec(fullMatch);
  if (colonFormat) {
    let hours = parseInt(colonFormat[1]!, 10);
    const minutes = colonFormat[2]!;
    const ampm = colonFormat[3]?.toLowerCase();

    if (ampm === 'pm' && hours < 12) hours += 12;
    if (ampm === 'am' && hours === 12) hours = 0;

    return `${hours.toString().padStart(2, '0')}:${minutes}`;
  }

  // HH.MM format (German)
  const dotFormat = /(\d{1,2})\.(\d{2})\s*(Uhr|h)?/i.exec(fullMatch);
  if (dotFormat) {
    const hours = dotFormat[1]!.padStart(2, '0');
    const minutes = dotFormat[2]!;
    return `${hours}:${minutes}`;
  }

  return null;
}

function escapeRegex(string: string): string {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Check if text likely contains schedule information
export function hasScheduleInfo(text: string): boolean {
  const lowerText = text.toLowerCase();

  const hasBuildUp = BUILD_UP_KEYWORDS.some(kw => lowerText.includes(kw.toLowerCase()));
  const hasTearDown = TEAR_DOWN_KEYWORDS.some(kw => lowerText.includes(kw.toLowerCase()));
  const hasDate = DATE_PATTERNS.some(pattern => {
    pattern.lastIndex = 0;
    return pattern.test(text);
  });

  return (hasBuildUp || hasTearDown) && hasDate;
}
