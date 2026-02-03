import type { ActionLogEntry } from '../schemas/output.js';

export interface Logger {
  log: ActionLogEntry[];
  add(step: ActionLogEntry['step'], input: string, output: string | null, ms?: number): void;
  note(message: string): void;
  notes: string[];
}

export function createLogger(): Logger {
  const log: ActionLogEntry[] = [];
  const notes: string[] = [];

  return {
    log,
    notes,
    add(step, input, output, ms) {
      log.push({ step, input, output, ms: ms ?? null });
      const timestamp = new Date().toISOString().slice(11, 19);
      const msStr = ms !== undefined ? ` (${ms}ms)` : '';
      console.log(`[${timestamp}] ${step.toUpperCase()}: ${input}${msStr}`);
      if (output && output.length < 200) {
        console.log(`  → ${output}`);
      }
    },
    note(message) {
      notes.push(message);
      console.log(`[NOTE] ${message}`);
    },
  };
}
