import * as fs from 'node:fs';
import pdf from 'pdf-parse';
import type { Logger } from '../../utils/logger.js';

export interface ParsedPdf {
  success: boolean;
  path: string;
  text: string;
  numPages: number;
  title?: string;
  error?: string;
}

export interface ParsePdfOptions {
  logger?: Logger;
  maxPages?: number;
}

export async function parsePdf(
  filePath: string,
  options: ParsePdfOptions = {}
): Promise<ParsedPdf> {
  const { logger, maxPages = 50 } = options;
  const startTime = Date.now();

  if (!fs.existsSync(filePath)) {
    logger?.add('parse', filePath, 'File not found', Date.now() - startTime);
    return {
      success: false,
      path: filePath,
      text: '',
      numPages: 0,
      error: 'File not found',
    };
  }

  try {
    const dataBuffer = fs.readFileSync(filePath);

    // Parse PDF with page limit
    const data = await pdf(dataBuffer, {
      max: maxPages,
    });

    const text = data.text
      .replace(/\r\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();

    // Try to extract title from metadata or first line
    let title = data.info?.Title as string | undefined;
    if (!title) {
      const firstLine = text.split('\n')[0]?.trim();
      if (firstLine && firstLine.length < 100) {
        title = firstLine;
      }
    }

    logger?.add('parse', filePath, `OK (${data.numpages} pages, ${text.length} chars)`, Date.now() - startTime);

    return {
      success: true,
      path: filePath,
      text,
      numPages: data.numpages,
      title,
    };
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : 'Unknown error';
    logger?.add('parse', filePath, `Error: ${errorMsg}`, Date.now() - startTime);

    return {
      success: false,
      path: filePath,
      text: '',
      numPages: 0,
      error: errorMsg,
    };
  }
}

// Check if file is likely a PDF
export function isPdfFile(filePath: string): boolean {
  if (!fs.existsSync(filePath)) {
    return false;
  }

  // Check magic bytes
  const buffer = Buffer.alloc(5);
  const fd = fs.openSync(filePath, 'r');
  fs.readSync(fd, buffer, 0, 5, 0);
  fs.closeSync(fd);

  return buffer.toString('ascii') === '%PDF-';
}
