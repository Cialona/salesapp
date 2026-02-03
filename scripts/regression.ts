#!/usr/bin/env node

/**
 * Regression Runner for Trade Fair Discovery
 *
 * Runs all testcases and generates:
 * - Individual JSON outputs in /outputs/
 * - Individual markdown reports in /reports/
 * - Summary scorecard in /reports/summary.md
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import { runDiscovery } from '../src/agent/loop.js';
import { TestCaseInput, DiscoveryOutput } from '../src/schemas/output.js';

const INPUTS_DIR = 'inputs';
const OUTPUTS_DIR = 'outputs';
const REPORTS_DIR = 'reports';

interface TestResult {
  id: string;
  fair_name: string;
  passed: boolean;
  failures: string[];
  warnings: string[];
  output: DiscoveryOutput;
  elapsed_ms: number;
}

async function main() {
  console.log('═══════════════════════════════════════════════════════════════');
  console.log('  Trade Fair Discovery - Regression Runner');
  console.log('═══════════════════════════════════════════════════════════════\n');

  // Ensure directories exist
  fs.mkdirSync(OUTPUTS_DIR, { recursive: true });
  fs.mkdirSync(REPORTS_DIR, { recursive: true });

  // Load testcases
  const testcasesPath = path.join(INPUTS_DIR, 'testcases.json');
  if (!fs.existsSync(testcasesPath)) {
    console.error(`Error: ${testcasesPath} not found`);
    process.exit(1);
  }

  const testcases: TestCaseInput[] = JSON.parse(fs.readFileSync(testcasesPath, 'utf-8'));
  console.log(`Loaded ${testcases.length} testcases\n`);

  // Check if running specific test
  const specificTest = process.argv[2];
  const casesToRun = specificTest
    ? testcases.filter(tc => tc.id === specificTest || tc.fair_name.toLowerCase().includes(specificTest.toLowerCase()))
    : testcases;

  if (casesToRun.length === 0) {
    console.error(`No testcases match: ${specificTest}`);
    process.exit(1);
  }

  console.log(`Running ${casesToRun.length} testcase(s)...\n`);

  const results: TestResult[] = [];

  for (let i = 0; i < casesToRun.length; i++) {
    const testcase = casesToRun[i]!;
    console.log(`\n[${ i + 1}/${casesToRun.length}] ${testcase.fair_name} (${testcase.id})`);
    console.log('─'.repeat(60));

    const startTime = Date.now();

    try {
      const output = await runDiscovery(testcase);
      const elapsed = Date.now() - startTime;

      // Run assertions
      const { passed, failures, warnings } = runAssertions(testcase, output);

      const result: TestResult = {
        id: testcase.id,
        fair_name: testcase.fair_name,
        passed,
        failures,
        warnings,
        output,
        elapsed_ms: elapsed,
      };

      results.push(result);

      // Save individual output
      const outputPath = path.join(OUTPUTS_DIR, `${testcase.id}.json`);
      fs.writeFileSync(outputPath, JSON.stringify(output, null, 2));

      // Save individual report
      const reportPath = path.join(REPORTS_DIR, `${testcase.id}.md`);
      fs.writeFileSync(reportPath, generateReport(testcase, result));

      // Print result
      const status = passed ? '✅ PASS' : '❌ FAIL';
      console.log(`\n${status} (${Math.round(elapsed / 1000)}s)`);

      if (failures.length > 0) {
        console.log('Failures:');
        failures.forEach(f => console.log(`  - ${f}`));
      }

      if (warnings.length > 0) {
        console.log('Warnings:');
        warnings.forEach(w => console.log(`  - ${w}`));
      }
    } catch (error) {
      const elapsed = Date.now() - startTime;
      console.error(`\n❌ ERROR: ${error}`);

      results.push({
        id: testcase.id,
        fair_name: testcase.fair_name,
        passed: false,
        failures: [`Runtime error: ${error}`],
        warnings: [],
        output: {} as DiscoveryOutput,
        elapsed_ms: elapsed,
      });
    }
  }

  // Generate summary
  const summaryPath = path.join(REPORTS_DIR, 'summary.md');
  fs.writeFileSync(summaryPath, generateSummary(results));
  console.log(`\n\n📊 Summary saved to: ${summaryPath}`);

  // Print final summary
  console.log('\n═══════════════════════════════════════════════════════════════');
  console.log('  FINAL RESULTS');
  console.log('═══════════════════════════════════════════════════════════════\n');

  const passed = results.filter(r => r.passed).length;
  const failed = results.filter(r => !r.passed).length;

  console.log(`  Total: ${results.length}`);
  console.log(`  Passed: ${passed} ✅`);
  console.log(`  Failed: ${failed} ❌`);
  console.log(`  Pass rate: ${Math.round((passed / results.length) * 100)}%`);
  console.log('');

  // Exit with error code if any failed
  process.exit(failed > 0 ? 1 : 0);
}

function runAssertions(
  testcase: TestCaseInput,
  output: DiscoveryOutput
): { passed: boolean; failures: string[]; warnings: string[] } {
  const failures: string[] = [];
  const warnings: string[] = [];
  const expected = testcase.expected;

  // Check official domain
  if (expected.official_domain) {
    if (!output.official_domain) {
      failures.push(`Expected official domain ${expected.official_domain}, got null`);
    } else if (!output.official_domain.includes(expected.official_domain)) {
      failures.push(`Expected official domain containing ${expected.official_domain}, got ${output.official_domain}`);
    }
  }

  // Check documents
  if (expected.has_floorplan && !output.documents.floorplan_url) {
    if (output.quality.floorplan === 'missing') {
      failures.push('Expected floorplan, but quality is missing');
    } else {
      warnings.push('Floorplan quality not missing but URL is null');
    }
  }

  if (expected.has_manual && !output.documents.exhibitor_manual_url) {
    if (output.quality.exhibitor_manual === 'missing') {
      failures.push('Expected exhibitor manual, but quality is missing');
    } else {
      warnings.push('Manual quality not missing but URL is null');
    }
  }

  if (expected.has_rules && !output.documents.rules_url) {
    if (output.quality.rules === 'missing') {
      failures.push('Expected rules, but quality is missing');
    } else {
      warnings.push('Rules quality not missing but URL is null');
    }
  }

  if (expected.has_directory && !output.documents.exhibitor_directory_url) {
    if (output.quality.exhibitor_directory === 'missing') {
      failures.push('Expected exhibitor directory, but quality is missing');
    } else {
      warnings.push('Directory quality not missing but URL is null');
    }
  }

  // Check schedule
  if (expected.has_schedule) {
    const totalEntries = output.schedule.build_up.length + output.schedule.tear_down.length;
    if (totalEntries === 0 && output.quality.schedule === 'missing') {
      failures.push('Expected schedule data, but none found');
    }
  }

  if (expected.min_schedule_entries) {
    const totalEntries = output.schedule.build_up.length + output.schedule.tear_down.length;
    if (totalEntries < expected.min_schedule_entries) {
      warnings.push(`Expected at least ${expected.min_schedule_entries} schedule entries, got ${totalEntries}`);
    }
  }

  // Schedule in PDF check
  if (expected.schedule_in_pdf) {
    const scheduleFromPdf = output.schedule.build_up.some(e => e.source_url.endsWith('.pdf')) ||
      output.schedule.tear_down.some(e => e.source_url.endsWith('.pdf'));
    if (!scheduleFromPdf && output.schedule.build_up.length + output.schedule.tear_down.length > 0) {
      warnings.push('Expected schedule from PDF, but source URLs are not PDFs');
    }
  }

  // Check for blocked URLs (informational)
  if (output.debug.blocked_urls.length > 3) {
    warnings.push(`High number of blocked URLs: ${output.debug.blocked_urls.length}`);
  }

  return {
    passed: failures.length === 0,
    failures,
    warnings,
  };
}

function generateReport(testcase: TestCaseInput, result: TestResult): string {
  const lines: string[] = [];
  const output = result.output;

  lines.push(`# ${testcase.fair_name} - Test Report`);
  lines.push('');
  lines.push(`**Test ID:** ${testcase.id}`);
  lines.push(`**Status:** ${result.passed ? '✅ PASSED' : '❌ FAILED'}`);
  lines.push(`**Runtime:** ${Math.round(result.elapsed_ms / 1000)}s`);
  lines.push(`**Generated:** ${new Date().toISOString()}`);
  lines.push('');

  if (result.failures.length > 0) {
    lines.push('## Failures');
    lines.push('');
    result.failures.forEach(f => lines.push(`- ❌ ${f}`));
    lines.push('');
  }

  if (result.warnings.length > 0) {
    lines.push('## Warnings');
    lines.push('');
    result.warnings.forEach(w => lines.push(`- ⚠️ ${w}`));
    lines.push('');
  }

  lines.push('## Input');
  lines.push('');
  lines.push('```json');
  lines.push(JSON.stringify(testcase, null, 2));
  lines.push('```');
  lines.push('');

  lines.push('## Results');
  lines.push('');
  lines.push(`| Field | Quality | URL |`);
  lines.push(`|-------|---------|-----|`);
  lines.push(`| Official | - | ${output.official_url || '-'} |`);
  lines.push(`| Floorplan | ${output.quality.floorplan} | ${output.documents.floorplan_url || '-'} |`);
  lines.push(`| Manual | ${output.quality.exhibitor_manual} | ${output.documents.exhibitor_manual_url || '-'} |`);
  lines.push(`| Rules | ${output.quality.rules} | ${output.documents.rules_url || '-'} |`);
  lines.push(`| Schedule | ${output.quality.schedule} | ${output.documents.schedule_page_url || '-'} |`);
  lines.push(`| Directory | ${output.quality.exhibitor_directory} | ${output.documents.exhibitor_directory_url || '-'} |`);
  lines.push('');

  lines.push('## Schedule Entries');
  lines.push('');
  lines.push(`- Build-up: ${output.schedule.build_up.length} entries`);
  lines.push(`- Tear-down: ${output.schedule.tear_down.length} entries`);
  lines.push('');

  if (output.schedule.build_up.length > 0) {
    lines.push('### Build-up');
    lines.push('');
    for (const entry of output.schedule.build_up) {
      lines.push(`- ${entry.date || '?'} ${entry.time || ''}: ${entry.description.slice(0, 100)}`);
    }
    lines.push('');
  }

  if (output.schedule.tear_down.length > 0) {
    lines.push('### Tear-down');
    lines.push('');
    for (const entry of output.schedule.tear_down) {
      lines.push(`- ${entry.date || '?'} ${entry.time || ''}: ${entry.description?.slice(0, 100) || '-'}`);
    }
    lines.push('');
  }

  lines.push('## Debug Stats');
  lines.push('');
  lines.push(`- Pages visited: ${output.debug.visited_urls.length}`);
  lines.push(`- Files downloaded: ${output.debug.downloaded_files.length}`);
  lines.push(`- Blocked URLs: ${output.debug.blocked_urls.length}`);
  lines.push(`- Action log entries: ${output.debug.action_log.length}`);
  lines.push('');

  if (output.debug.blocked_urls.length > 0) {
    lines.push('### Blocked URLs');
    lines.push('');
    for (const blocked of output.debug.blocked_urls.slice(0, 10)) {
      lines.push(`- ${blocked.url}: ${blocked.reason}`);
    }
    lines.push('');
  }

  lines.push('## Evidence');
  lines.push('');
  for (const field of ['floorplan', 'exhibitor_manual', 'rules', 'schedule', 'exhibitor_directory'] as const) {
    lines.push(`### ${field}`);
    lines.push('');
    lines.push(`**Reasoning:** ${output.primary_reasoning[field]}`);
    lines.push('');
    const evidence = output.evidence[field];
    if (evidence.title) lines.push(`**Title:** ${evidence.title}`);
    if (evidence.snippet) {
      lines.push('');
      lines.push('**Snippet:**');
      lines.push('```');
      lines.push(evidence.snippet.slice(0, 500));
      lines.push('```');
    }
    lines.push('');
  }

  return lines.join('\n');
}

function generateSummary(results: TestResult[]): string {
  const lines: string[] = [];

  lines.push('# Trade Fair Discovery - Regression Summary');
  lines.push('');
  lines.push(`**Generated:** ${new Date().toISOString()}`);
  lines.push('');

  const passed = results.filter(r => r.passed).length;
  const failed = results.filter(r => !r.passed).length;

  lines.push('## Overall Results');
  lines.push('');
  lines.push(`| Metric | Value |`);
  lines.push(`|--------|-------|`);
  lines.push(`| Total tests | ${results.length} |`);
  lines.push(`| Passed | ${passed} ✅ |`);
  lines.push(`| Failed | ${failed} ❌ |`);
  lines.push(`| Pass rate | ${Math.round((passed / results.length) * 100)}% |`);
  lines.push('');

  lines.push('## Scorecard');
  lines.push('');
  lines.push('| ID | Fair | Official URL | Floorplan | Manual | Rules | Schedule | Directory | Schedule# | Blocked | Result |');
  lines.push('|----|------|--------------|-----------|--------|-------|----------|-----------|-----------|---------|--------|');

  for (const result of results) {
    const o = result.output;
    const q = (field: string) => {
      const quality = (o.quality as Record<string, string>)[field];
      if (quality === 'strong') return '✅';
      if (quality === 'weak') return '⚠️';
      return '❌';
    };

    const scheduleCount = (o.schedule?.build_up?.length || 0) + (o.schedule?.tear_down?.length || 0);
    const blockedCount = o.debug?.blocked_urls?.length || 0;
    const status = result.passed ? '✅ PASS' : '❌ FAIL';

    const officialUrl = o.official_url ? `[link](${o.official_url})` : '-';

    lines.push(`| ${result.id} | ${result.fair_name} | ${officialUrl} | ${q('floorplan')} | ${q('exhibitor_manual')} | ${q('rules')} | ${q('schedule')} | ${q('exhibitor_directory')} | ${scheduleCount} | ${blockedCount} | ${status} |`);
  }
  lines.push('');

  // Failed tests details
  const failedTests = results.filter(r => !r.passed);
  if (failedTests.length > 0) {
    lines.push('## Failed Tests Details');
    lines.push('');
    for (const result of failedTests) {
      lines.push(`### ${result.fair_name} (${result.id})`);
      lines.push('');
      lines.push('**Failures:**');
      for (const f of result.failures) {
        lines.push(`- ${f}`);
      }
      lines.push('');
    }
  }

  // Quality distribution
  lines.push('## Quality Distribution');
  lines.push('');

  const fields = ['floorplan', 'exhibitor_manual', 'rules', 'schedule', 'exhibitor_directory'];
  for (const field of fields) {
    const strong = results.filter(r => (r.output.quality as Record<string, string>)[field] === 'strong').length;
    const weak = results.filter(r => (r.output.quality as Record<string, string>)[field] === 'weak').length;
    const missing = results.filter(r => (r.output.quality as Record<string, string>)[field] === 'missing').length;

    lines.push(`### ${field}`);
    lines.push(`- Strong: ${strong} (${Math.round((strong / results.length) * 100)}%)`);
    lines.push(`- Weak: ${weak} (${Math.round((weak / results.length) * 100)}%)`);
    lines.push(`- Missing: ${missing} (${Math.round((missing / results.length) * 100)}%)`);
    lines.push('');
  }

  return lines.join('\n');
}

main().catch(console.error);
