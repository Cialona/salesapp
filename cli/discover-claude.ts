#!/usr/bin/env node

/**
 * Trade Fair Discovery CLI - Claude Computer Use Version
 *
 * Uses Claude's Computer Use API to navigate websites like a human agent.
 */

import { program } from 'commander';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { ClaudeAgent } from '../src/claude-agent/claude-agent.js';
import { TestCaseInput, DiscoveryOutput } from '../src/schemas/output.js';

program
  .name('discover-claude')
  .description('Trade Fair Discovery using Claude Computer Use API')
  .version('1.0.0');

program
  .option('-n, --name <name>', 'Fair name (required)')
  .option('-u, --url <url>', 'Known URL (optional)')
  .option('-c, --city <city>', 'City (optional)')
  .option('-C, --country <country>', 'Country (optional)')
  .option('-o, --output <path>', 'Output JSON file path')
  .option('-r, --report <path>', 'Output markdown report path')
  .option('--json', 'Output JSON to stdout')
  .option('--debug', 'Enable debug logging')
  .option('--max-iterations <n>', 'Maximum agent iterations (default: 50)', '50')
  .action(async (options) => {
    if (!options.name) {
      console.error('Error: --name is required');
      process.exit(1);
    }

    // Check for API key
    if (!process.env['ANTHROPIC_API_KEY']) {
      console.error('Error: ANTHROPIC_API_KEY environment variable is required');
      console.error('');
      console.error('Get your API key from: https://console.anthropic.com/');
      console.error('Then set it:');
      console.error('  export ANTHROPIC_API_KEY=sk-ant-...');
      process.exit(1);
    }

    // Create input
    const input: TestCaseInput = {
      id: `claude-${Date.now()}`,
      fair_name: options.name,
      known_url: options.url || null,
      city: options.city || null,
      country: options.country || null,
      expected: {},
    };

    console.log('');
    console.log('╔═══════════════════════════════════════════════════════════════╗');
    console.log('║      Trade Fair Discovery - Claude Computer Use Agent         ║');
    console.log('╚═══════════════════════════════════════════════════════════════╝');
    console.log('');
    console.log(`  Fair: ${input.fair_name}`);
    console.log(`  URL: ${input.known_url || '(will search)'}`);
    console.log(`  Location: ${[input.city, input.country].filter(Boolean).join(', ') || '(unknown)'}`);
    console.log('');
    console.log('  Claude is now browsing the website like a human agent...');
    console.log('  This may take 1-3 minutes.');
    console.log('');

    try {
      const startTime = Date.now();

      const agent = new ClaudeAgent({
        debug: options.debug,
        maxIterations: parseInt(options.maxIterations, 10),
      });

      const output = await agent.run(input);
      const elapsed = Math.round((Date.now() - startTime) / 1000);

      console.log('');
      console.log(`✅ Discovery completed in ${elapsed}s`);
      console.log('');

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
  console.log('');

  console.log('  Documents Found:');
  const qualityEmoji = { strong: '✅', weak: '⚠️', missing: '❌' };

  const docs = [
    { name: 'Floor Plan', quality: output.quality.floorplan, url: output.documents.floorplan_url },
    { name: 'Exhibitor Manual', quality: output.quality.exhibitor_manual, url: output.documents.exhibitor_manual_url },
    { name: 'Rules/Guidelines', quality: output.quality.rules, url: output.documents.rules_url },
    { name: 'Schedule', quality: output.quality.schedule, url: output.documents.schedule_page_url },
    { name: 'Exhibitor Directory', quality: output.quality.exhibitor_directory, url: output.documents.exhibitor_directory_url },
  ];

  for (const doc of docs) {
    const emoji = qualityEmoji[doc.quality];
    const urlShort = doc.url ? doc.url.slice(0, 55) + (doc.url.length > 55 ? '...' : '') : '(not found)';
    console.log(`    ${emoji} ${doc.name.padEnd(18)} ${urlShort}`);
  }

  console.log('');

  if (output.schedule.build_up.length > 0 || output.schedule.tear_down.length > 0) {
    console.log('  Schedule:');
    if (output.schedule.build_up.length > 0) {
      console.log(`    Build-up (${output.schedule.build_up.length} entries):`);
      for (const entry of output.schedule.build_up.slice(0, 3)) {
        console.log(`      • ${entry.date || '?'} ${entry.time || ''}`);
      }
      if (output.schedule.build_up.length > 3) {
        console.log(`      ... and ${output.schedule.build_up.length - 3} more`);
      }
    }
    if (output.schedule.tear_down.length > 0) {
      console.log(`    Tear-down (${output.schedule.tear_down.length} entries):`);
      for (const entry of output.schedule.tear_down.slice(0, 3)) {
        console.log(`      • ${entry.date || '?'} ${entry.time || ''}`);
      }
      if (output.schedule.tear_down.length > 3) {
        console.log(`      ... and ${output.schedule.tear_down.length - 3} more`);
      }
    }
    console.log('');
  }

  console.log('═══════════════════════════════════════════════════════════════');
}

function generateMarkdownReport(output: DiscoveryOutput): string {
  const lines: string[] = [];

  lines.push(`# ${output.fair_name} - Claude Agent Discovery Report`);
  lines.push('');
  lines.push(`**Generated:** ${new Date().toISOString()}`);
  lines.push(`**Method:** Claude Computer Use API`);
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

  // Schedule
  if (output.schedule.build_up.length > 0 || output.schedule.tear_down.length > 0) {
    lines.push('## Schedule');
    lines.push('');

    if (output.schedule.build_up.length > 0) {
      lines.push('### Build-up');
      lines.push('');
      lines.push('| Date | Time | Description |');
      lines.push('|------|------|-------------|');
      for (const entry of output.schedule.build_up) {
        lines.push(`| ${entry.date || '-'} | ${entry.time || '-'} | ${entry.description.slice(0, 50)} |`);
      }
      lines.push('');
    }

    if (output.schedule.tear_down.length > 0) {
      lines.push('### Tear-down');
      lines.push('');
      lines.push('| Date | Time | Description |');
      lines.push('|------|------|-------------|');
      for (const entry of output.schedule.tear_down) {
        lines.push(`| ${entry.date || '-'} | ${entry.time || '-'} | ${entry.description?.slice(0, 50) || '-'} |`);
      }
      lines.push('');
    }
  }

  // Agent notes
  if (output.debug.notes.length > 0) {
    lines.push('## Agent Notes');
    lines.push('');
    for (const note of output.debug.notes) {
      lines.push(`- ${note}`);
    }
    lines.push('');
  }

  return lines.join('\n');
}
