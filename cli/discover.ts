#!/usr/bin/env node

import { program } from 'commander';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { runDiscovery } from '../src/agent/loop.js';
import { TestCaseInput, DiscoveryOutput } from '../src/schemas/output.js';

program
  .name('discover')
  .description('Trade Fair Discovery - Agentic information discovery tool')
  .version('1.0.0');

program
  .option('-n, --name <name>', 'Fair name (required)')
  .option('-u, --url <url>', 'Known URL (optional)')
  .option('-c, --city <city>', 'City (optional)')
  .option('-C, --country <country>', 'Country (optional)')
  .option('-o, --output <path>', 'Output JSON file path')
  .option('-r, --report <path>', 'Output markdown report path')
  .option('--json', 'Output JSON to stdout')
  .action(async (options) => {
    if (!options.name) {
      console.error('Error: --name is required');
      process.exit(1);
    }

    // Create input
    const input: TestCaseInput = {
      id: `cli-${Date.now()}`,
      fair_name: options.name,
      known_url: options.url || null,
      city: options.city || null,
      country: options.country || null,
      expected: {},
    };

    console.log(`\n🔍 Starting discovery for: ${input.fair_name}`);
    console.log(`   URL: ${input.known_url || '(will search)'}`);
    console.log(`   Location: ${[input.city, input.country].filter(Boolean).join(', ') || '(unknown)'}`);
    console.log('');

    try {
      const startTime = Date.now();
      const output = await runDiscovery(input);
      const elapsed = Math.round((Date.now() - startTime) / 1000);

      console.log(`\n✅ Discovery completed in ${elapsed}s\n`);

      // Print summary
      printSummary(output);

      // Save JSON output
      if (options.output) {
        const outputPath = path.resolve(options.output);
        fs.mkdirSync(path.dirname(outputPath), { recursive: true });
        fs.writeFileSync(outputPath, JSON.stringify(output, null, 2));
        console.log(`\n📄 JSON saved to: ${outputPath}`);
      }

      // Save markdown report
      if (options.report) {
        const reportPath = path.resolve(options.report);
        fs.mkdirSync(path.dirname(reportPath), { recursive: true });
        const report = generateMarkdownReport(output);
        fs.writeFileSync(reportPath, report);
        console.log(`📝 Report saved to: ${reportPath}`);
      }

      // Output JSON to stdout if requested
      if (options.json) {
        console.log('\n--- JSON OUTPUT ---');
        console.log(JSON.stringify(output, null, 2));
      }
    } catch (error) {
      console.error('\n❌ Discovery failed:', error);
      process.exit(1);
    }
  });

program.parse();

function printSummary(output: DiscoveryOutput): void {
  console.log('═══════════════════════════════════════════════════════════════');
  console.log(`  ${output.fair_name}`);
  console.log('═══════════════════════════════════════════════════════════════');
  console.log(`  Official URL: ${output.official_url || '(not found)'}`);
  console.log(`  Domain: ${output.official_domain || '(unknown)'}`);
  console.log('');

  console.log('  Quality Summary:');
  const qualityEmoji = { strong: '✅', weak: '⚠️', missing: '❌' };
  for (const [field, quality] of Object.entries(output.quality)) {
    const emoji = qualityEmoji[quality as keyof typeof qualityEmoji];
    const url = getUrlForField(output, field);
    console.log(`    ${emoji} ${field}: ${quality}${url ? ` → ${url.slice(0, 60)}...` : ''}`);
  }
  console.log('');

  if (output.schedule.build_up.length > 0 || output.schedule.tear_down.length > 0) {
    console.log('  Schedule:');
    if (output.schedule.build_up.length > 0) {
      console.log(`    Build-up: ${output.schedule.build_up.length} entries`);
      for (const entry of output.schedule.build_up.slice(0, 3)) {
        console.log(`      - ${entry.date || '(no date)'} ${entry.time || ''}: ${entry.description.slice(0, 50)}...`);
      }
    }
    if (output.schedule.tear_down.length > 0) {
      console.log(`    Tear-down: ${output.schedule.tear_down.length} entries`);
      for (const entry of output.schedule.tear_down.slice(0, 3)) {
        console.log(`      - ${entry.date || '(no date)'} ${entry.time || ''}: ${entry.description.slice(0, 50)}...`);
      }
    }
    console.log('');
  }

  console.log('  Debug Stats:');
  console.log(`    Pages visited: ${output.debug.visited_urls.length}`);
  console.log(`    Files downloaded: ${output.debug.downloaded_files.length}`);
  console.log(`    Blocked URLs: ${output.debug.blocked_urls.length}`);
  console.log('═══════════════════════════════════════════════════════════════');
}

function getUrlForField(output: DiscoveryOutput, field: string): string | null {
  switch (field) {
    case 'floorplan': return output.documents.floorplan_url;
    case 'exhibitor_manual': return output.documents.exhibitor_manual_url;
    case 'rules': return output.documents.rules_url;
    case 'schedule': return output.documents.schedule_page_url;
    case 'exhibitor_directory': return output.documents.exhibitor_directory_url;
    default: return null;
  }
}

function generateMarkdownReport(output: DiscoveryOutput): string {
  const lines: string[] = [];

  lines.push(`# ${output.fair_name} - Discovery Report`);
  lines.push('');
  lines.push(`**Generated:** ${new Date().toISOString()}`);
  lines.push('');

  // Basic info
  lines.push('## Basic Information');
  lines.push('');
  lines.push(`| Field | Value |`);
  lines.push(`|-------|-------|`);
  lines.push(`| Official URL | ${output.official_url || '(not found)'} |`);
  lines.push(`| Domain | ${output.official_domain || '(unknown)'} |`);
  lines.push(`| City | ${output.city || '(unknown)'} |`);
  lines.push(`| Country | ${output.country || '(unknown)'} |`);
  lines.push(`| Venue | ${output.venue || '(unknown)'} |`);
  lines.push('');

  // Documents
  lines.push('## Documents Found');
  lines.push('');
  lines.push(`| Document | Quality | URL |`);
  lines.push(`|----------|---------|-----|`);

  const fields = [
    { key: 'floorplan', name: 'Floor Plan', url: output.documents.floorplan_url },
    { key: 'exhibitor_manual', name: 'Exhibitor Manual', url: output.documents.exhibitor_manual_url },
    { key: 'rules', name: 'Rules/Regulations', url: output.documents.rules_url },
    { key: 'schedule', name: 'Schedule', url: output.documents.schedule_page_url },
    { key: 'exhibitor_directory', name: 'Exhibitor Directory', url: output.documents.exhibitor_directory_url },
  ] as const;

  for (const field of fields) {
    const quality = output.quality[field.key];
    const emoji = quality === 'strong' ? '✅' : quality === 'weak' ? '⚠️' : '❌';
    lines.push(`| ${field.name} | ${emoji} ${quality} | ${field.url || '-'} |`);
  }
  lines.push('');

  // Evidence
  lines.push('## Evidence');
  lines.push('');
  for (const field of fields) {
    const evidence = output.evidence[field.key];
    const reasoning = output.primary_reasoning[field.key];
    lines.push(`### ${field.name}`);
    lines.push('');
    lines.push(`**Reasoning:** ${reasoning}`);
    lines.push('');
    if (evidence.title) {
      lines.push(`**Title:** ${evidence.title}`);
      lines.push('');
    }
    if (evidence.snippet) {
      lines.push(`**Snippet:**`);
      lines.push('```');
      lines.push(evidence.snippet);
      lines.push('```');
      lines.push('');
    }
  }

  // Schedule
  if (output.schedule.build_up.length > 0 || output.schedule.tear_down.length > 0) {
    lines.push('## Schedule');
    lines.push('');

    if (output.schedule.build_up.length > 0) {
      lines.push('### Build-up');
      lines.push('');
      lines.push('| Date | Time | Description | Source |');
      lines.push('|------|------|-------------|--------|');
      for (const entry of output.schedule.build_up) {
        lines.push(`| ${entry.date || '-'} | ${entry.time || '-'} | ${entry.description.slice(0, 50)} | [link](${entry.source_url}) |`);
      }
      lines.push('');
    }

    if (output.schedule.tear_down.length > 0) {
      lines.push('### Tear-down');
      lines.push('');
      lines.push('| Date | Time | Description | Source |');
      lines.push('|------|------|-------------|--------|');
      for (const entry of output.schedule.tear_down) {
        lines.push(`| ${entry.date || '-'} | ${entry.time || '-'} | ${entry.description?.slice(0, 50) || '-'} | [link](${entry.source_url}) |`);
      }
      lines.push('');
    }
  }

  // Debug summary
  lines.push('## Debug Summary');
  lines.push('');
  lines.push(`- **Pages visited:** ${output.debug.visited_urls.length}`);
  lines.push(`- **Files downloaded:** ${output.debug.downloaded_files.length}`);
  lines.push(`- **Blocked URLs:** ${output.debug.blocked_urls.length}`);
  lines.push('');

  if (output.debug.blocked_urls.length > 0) {
    lines.push('### Blocked URLs');
    lines.push('');
    for (const blocked of output.debug.blocked_urls) {
      lines.push(`- \`${blocked.url}\` - ${blocked.reason} (status: ${blocked.status || 'N/A'})`);
    }
    lines.push('');
  }

  // Action log (summarized)
  lines.push('### Action Log (last 20)');
  lines.push('');
  lines.push('```');
  for (const action of output.debug.action_log.slice(-20)) {
    lines.push(`[${action.step}] ${action.input} → ${action.output || '(no output)'} (${action.ms}ms)`);
  }
  lines.push('```');
  lines.push('');

  // Email draft
  if (output.email_draft_if_missing) {
    lines.push('## Email Draft (for missing info)');
    lines.push('');
    lines.push(`**Missing:** ${output.email_draft_if_missing.needed.join(', ')}`);
    lines.push(`**Language:** ${output.email_draft_if_missing.language}`);
    lines.push('');
    lines.push(`**Subject:** ${output.email_draft_if_missing.subject}`);
    lines.push('');
    lines.push('```');
    lines.push(output.email_draft_if_missing.body);
    lines.push('```');
    lines.push('');
  }

  return lines.join('\n');
}
