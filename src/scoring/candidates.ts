import type { Candidate, QualityLevel, FieldName, EvidenceItem } from '../schemas/output.js';
import { FIELD_KEYWORDS, extractSnippet } from '../utils/text-extract.js';

export interface ScoredCandidate extends Candidate {
  title?: string;
  contentSnippet?: string;
  source: 'pdf' | 'page' | 'link';
}

export interface SelectionResult {
  url: string | null;
  quality: QualityLevel;
  reasoning: string;
  evidence: EvidenceItem;
}

// Score thresholds
const STRONG_THRESHOLD = 70;
const WEAK_THRESHOLD = 40;

// Scoring weights
const WEIGHTS = {
  urlMatch: 20,
  titleMatch: 30,
  contentMatch: 40,
  freshness: 10,
};

export function scoreUrlForField(url: string, field: FieldName): number {
  const lowerUrl = url.toLowerCase();
  const keywords = FIELD_KEYWORDS[field === 'exhibitor_manual' ? 'exhibitor_manual' : field];
  let score = 0;

  // URL contains relevant keywords
  for (const keyword of keywords) {
    const keywordLower = keyword.toLowerCase().replace(/\s+/g, '[-_]?');
    const regex = new RegExp(keywordLower, 'i');
    if (regex.test(lowerUrl)) {
      score += 10;
    }
  }

  // Bonus for PDF (good for manuals, rules)
  if (field === 'exhibitor_manual' || field === 'rules') {
    if (lowerUrl.endsWith('.pdf')) {
      score += 10;
    }
  }

  return Math.min(score, WEIGHTS.urlMatch);
}

export function scoreTitleForField(title: string | undefined, field: FieldName): number {
  if (!title) return 0;

  const lowerTitle = title.toLowerCase();
  const keywords = FIELD_KEYWORDS[field === 'exhibitor_manual' ? 'exhibitor_manual' : field];
  let score = 0;

  for (const keyword of keywords) {
    if (lowerTitle.includes(keyword.toLowerCase())) {
      score += 15;
    }
  }

  return Math.min(score, WEIGHTS.titleMatch);
}

export function scoreContentForField(content: string | undefined, field: FieldName): number {
  if (!content) return 0;

  const lowerContent = content.toLowerCase();
  const keywords = FIELD_KEYWORDS[field === 'exhibitor_manual' ? 'exhibitor_manual' : field];
  let score = 0;

  // Count keyword matches
  let matchCount = 0;
  for (const keyword of keywords) {
    const regex = new RegExp(keyword.toLowerCase(), 'gi');
    const matches = lowerContent.match(regex);
    if (matches) {
      matchCount += matches.length;
    }
  }

  // Bonus for multiple matches
  if (matchCount >= 3) score += 20;
  else if (matchCount >= 1) score += 10;

  // For schedule, look for specific patterns
  if (field === 'schedule') {
    // Date patterns
    const datePattern = /\d{1,2}[./-]\d{1,2}[./-]\d{2,4}/g;
    const timePattern = /\d{1,2}:\d{2}/g;

    if (datePattern.test(lowerContent)) score += 10;
    if (timePattern.test(lowerContent)) score += 10;

    // Build-up/tear-down specific
    if (/build[- ]?up|aufbau|move[- ]?in|set[- ]?up/i.test(lowerContent)) score += 10;
    if (/tear[- ]?down|abbau|move[- ]?out|dismantl/i.test(lowerContent)) score += 10;
  }

  return Math.min(score, WEIGHTS.contentMatch);
}

export function scoreFreshness(url: string, content?: string): number {
  const currentYear = new Date().getFullYear();
  const yearPattern = new RegExp(`(${currentYear}|${currentYear + 1})`, 'g');

  let score = 0;

  // Check URL for year
  if (yearPattern.test(url)) {
    score += 5;
  }

  // Check content for year
  if (content && yearPattern.test(content)) {
    score += 5;
  }

  return Math.min(score, WEIGHTS.freshness);
}

export function scoreCandidate(
  candidate: Partial<ScoredCandidate>,
  field: FieldName
): ScoredCandidate {
  const url = candidate.url ?? '';
  const title = candidate.title;
  const content = candidate.contentSnippet;

  const urlScore = scoreUrlForField(url, field);
  const titleScore = scoreTitleForField(title, field);
  const contentScore = scoreContentForField(content, field);
  const freshnessScore = scoreFreshness(url, content);

  const totalScore = urlScore + titleScore + contentScore + freshnessScore;

  // Build reasoning
  const reasons: string[] = [];
  if (urlScore > 0) reasons.push(`URL match (+${urlScore})`);
  if (titleScore > 0) reasons.push(`Title match (+${titleScore})`);
  if (contentScore > 0) reasons.push(`Content match (+${contentScore})`);
  if (freshnessScore > 0) reasons.push(`Fresh year (+${freshnessScore})`);

  return {
    url,
    score: totalScore,
    why: reasons.length > 0 ? reasons.join(', ') : 'No strong matches',
    title,
    contentSnippet: content,
    source: candidate.source ?? 'link',
  };
}

export function rankCandidates(
  candidates: ScoredCandidate[],
  field: FieldName
): ScoredCandidate[] {
  return [...candidates]
    .sort((a, b) => b.score - a.score)
    .slice(0, 3); // Keep top 3
}

export function selectBest(
  candidates: ScoredCandidate[],
  field: FieldName
): SelectionResult {
  if (candidates.length === 0) {
    return {
      url: null,
      quality: 'missing',
      reasoning: 'No candidates found',
      evidence: { title: null, snippet: null },
    };
  }

  const ranked = rankCandidates(candidates, field);
  const best = ranked[0]!;

  // Determine quality based on score and evidence
  let quality: QualityLevel;
  let reasoning: string;

  if (best.score >= STRONG_THRESHOLD && best.contentSnippet) {
    quality = 'strong';
    reasoning = `Strong match: ${best.why}. Content verified.`;
  } else if (best.score >= WEAK_THRESHOLD) {
    quality = 'weak';
    reasoning = `Weak match: ${best.why}. Limited content verification.`;
  } else {
    quality = 'missing';
    reasoning = `Low confidence: ${best.why}. Score below threshold.`;
  }

  // Extract evidence
  const keywords = FIELD_KEYWORDS[field === 'exhibitor_manual' ? 'exhibitor_manual' : field];
  const snippet = best.contentSnippet
    ? extractSnippet(best.contentSnippet, keywords) ?? best.contentSnippet.slice(0, 200)
    : null;

  return {
    url: quality !== 'missing' ? best.url : null,
    quality,
    reasoning,
    evidence: {
      title: best.title ?? null,
      snippet,
    },
  };
}

// Convert basic candidates to scored candidates for output
export function toOutputCandidates(scored: ScoredCandidate[]): Candidate[] {
  return scored.map(c => ({
    url: c.url,
    score: c.score,
    why: c.why,
  }));
}
