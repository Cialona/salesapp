import { z } from 'zod';

// Quality levels
export const QualityLevel = z.enum(['strong', 'weak', 'missing']);
export type QualityLevel = z.infer<typeof QualityLevel>;

// Schedule entry
export const ScheduleEntry = z.object({
  date: z.string().nullable(), // YYYY-MM-DD format or null
  time: z.string().nullable(),
  description: z.string(),
  source_url: z.string(),
});
export type ScheduleEntry = z.infer<typeof ScheduleEntry>;

// Documents section
export const Documents = z.object({
  downloads_overview_url: z.string().nullable(),
  floorplan_url: z.string().nullable(),
  exhibitor_manual_url: z.string().nullable(),
  rules_url: z.string().nullable(),
  schedule_page_url: z.string().nullable(),
  exhibitor_directory_url: z.string().nullable(),
});
export type Documents = z.infer<typeof Documents>;

// Schedule section
export const Schedule = z.object({
  build_up: z.array(ScheduleEntry),
  tear_down: z.array(ScheduleEntry),
});
export type Schedule = z.infer<typeof Schedule>;

// Quality per field
export const Quality = z.object({
  floorplan: QualityLevel,
  exhibitor_manual: QualityLevel,
  rules: QualityLevel,
  schedule: QualityLevel,
  exhibitor_directory: QualityLevel,
});
export type Quality = z.infer<typeof Quality>;

// Reasoning per field
export const PrimaryReasoning = z.object({
  floorplan: z.string(),
  exhibitor_manual: z.string(),
  rules: z.string(),
  schedule: z.string(),
  exhibitor_directory: z.string(),
});
export type PrimaryReasoning = z.infer<typeof PrimaryReasoning>;

// Evidence item
export const EvidenceItem = z.object({
  title: z.string().nullable(),
  snippet: z.string().nullable(),
});
export type EvidenceItem = z.infer<typeof EvidenceItem>;

// Evidence per field
export const Evidence = z.object({
  floorplan: EvidenceItem,
  exhibitor_manual: EvidenceItem,
  rules: EvidenceItem,
  schedule: EvidenceItem,
  exhibitor_directory: EvidenceItem,
});
export type Evidence = z.infer<typeof Evidence>;

// Action log entry
export const ActionLogEntry = z.object({
  step: z.enum(['search', 'open', 'download', 'parse', 'select', 'guard']),
  input: z.string(),
  output: z.string().nullable(),
  ms: z.number().nullable(),
});
export type ActionLogEntry = z.infer<typeof ActionLogEntry>;

// Downloaded file info
export const DownloadedFile = z.object({
  url: z.string(),
  path: z.string(),
  content_type: z.string().nullable(),
  bytes: z.number().nullable(),
});
export type DownloadedFile = z.infer<typeof DownloadedFile>;

// Blocked URL info
export const BlockedUrl = z.object({
  url: z.string(),
  status: z.number().nullable(),
  reason: z.string(),
});
export type BlockedUrl = z.infer<typeof BlockedUrl>;

// Candidate with score
export const Candidate = z.object({
  url: z.string(),
  score: z.number(),
  why: z.string(),
});
export type Candidate = z.infer<typeof Candidate>;

// Candidates per field
export const Candidates = z.object({
  floorplan: z.array(Candidate),
  exhibitor_manual: z.array(Candidate),
  rules: z.array(Candidate),
  schedule: z.array(Candidate),
  exhibitor_directory: z.array(Candidate),
});
export type Candidates = z.infer<typeof Candidates>;

// Debug section
export const Debug = z.object({
  action_log: z.array(ActionLogEntry),
  visited_urls: z.array(z.string()),
  downloaded_files: z.array(DownloadedFile),
  blocked_urls: z.array(BlockedUrl),
  candidates: Candidates,
  notes: z.array(z.string()),
});
export type Debug = z.infer<typeof Debug>;

// Email draft for missing info
export const EmailDraft = z.object({
  needed: z.array(z.enum(['manual', 'rules', 'schedule', 'floorplan', 'directory'])),
  language: z.string(),
  subject: z.string(),
  body: z.string(),
});
export type EmailDraft = z.infer<typeof EmailDraft>;

// Main output schema
export const DiscoveryOutput = z.object({
  fair_name: z.string(),
  official_url: z.string().nullable(),
  official_domain: z.string().nullable(),
  country: z.string().nullable(),
  city: z.string().nullable(),
  venue: z.string().nullable(),
  documents: Documents,
  schedule: Schedule,
  quality: Quality,
  primary_reasoning: PrimaryReasoning,
  evidence: Evidence,
  debug: Debug,
  email_draft_if_missing: EmailDraft.nullable(),
});
export type DiscoveryOutput = z.infer<typeof DiscoveryOutput>;

// Input schema for test cases
export const TestCaseInput = z.object({
  id: z.string(),
  fair_name: z.string(),
  known_url: z.string().nullable(),
  city: z.string().nullable(),
  country: z.string().nullable(),
  expected: z.object({
    official_domain: z.string().optional(),
    has_floorplan: z.boolean().optional(),
    has_manual: z.boolean().optional(),
    has_rules: z.boolean().optional(),
    has_schedule: z.boolean().optional(),
    has_directory: z.boolean().optional(),
    schedule_in_pdf: z.boolean().optional(),
    min_schedule_entries: z.number().optional(),
  }),
});
export type TestCaseInput = z.infer<typeof TestCaseInput>;

// Create empty output template
export function createEmptyOutput(fairName: string): DiscoveryOutput {
  return {
    fair_name: fairName,
    official_url: null,
    official_domain: null,
    country: null,
    city: null,
    venue: null,
    documents: {
      downloads_overview_url: null,
      floorplan_url: null,
      exhibitor_manual_url: null,
      rules_url: null,
      schedule_page_url: null,
      exhibitor_directory_url: null,
    },
    schedule: {
      build_up: [],
      tear_down: [],
    },
    quality: {
      floorplan: 'missing',
      exhibitor_manual: 'missing',
      rules: 'missing',
      schedule: 'missing',
      exhibitor_directory: 'missing',
    },
    primary_reasoning: {
      floorplan: 'Not found',
      exhibitor_manual: 'Not found',
      rules: 'Not found',
      schedule: 'Not found',
      exhibitor_directory: 'Not found',
    },
    evidence: {
      floorplan: { title: null, snippet: null },
      exhibitor_manual: { title: null, snippet: null },
      rules: { title: null, snippet: null },
      schedule: { title: null, snippet: null },
      exhibitor_directory: { title: null, snippet: null },
    },
    debug: {
      action_log: [],
      visited_urls: [],
      downloaded_files: [],
      blocked_urls: [],
      candidates: {
        floorplan: [],
        exhibitor_manual: [],
        rules: [],
        schedule: [],
        exhibitor_directory: [],
      },
      notes: [],
    },
    email_draft_if_missing: null,
  };
}

// Field names type
export type FieldName = 'floorplan' | 'exhibitor_manual' | 'rules' | 'schedule' | 'exhibitor_directory';
export const FIELD_NAMES: FieldName[] = ['floorplan', 'exhibitor_manual', 'rules', 'schedule', 'exhibitor_directory'];
