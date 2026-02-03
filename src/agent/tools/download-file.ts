import { cache } from '../../cache/manager.js';
import { rateLimitedWait } from '../../utils/rate-limit.js';
import type { Logger } from '../../utils/logger.js';
import type { DownloadedFile } from '../../schemas/output.js';

export interface DownloadResult {
  success: boolean;
  url: string;
  path: string | null;
  contentType: string | null;
  bytes: number;
  error?: string;
  fromCache: boolean;
}

export interface DownloadOptions {
  logger?: Logger;
  useCache?: boolean;
  timeout?: number;
  maxSize?: number; // Max file size in bytes
}

const DEFAULT_MAX_SIZE = 50 * 1024 * 1024; // 50MB

export async function downloadFile(
  url: string,
  options: DownloadOptions = {}
): Promise<DownloadResult> {
  const {
    logger,
    useCache = true,
    timeout = 60000,
    maxSize = DEFAULT_MAX_SIZE,
  } = options;
  const startTime = Date.now();

  // Check cache first
  if (useCache && cache.hasValidDownloadCache(url)) {
    const cachedPath = cache.getCachedDownloadPath(url);
    const metadata = cache.getMetadata(url);

    if (cachedPath) {
      logger?.add('download', url, 'From cache', Date.now() - startTime);
      return {
        success: true,
        url,
        path: cachedPath,
        contentType: metadata?.contentType ?? null,
        bytes: metadata?.size ?? 0,
        fromCache: true,
      };
    }
  }

  // Rate limit before request
  await rateLimitedWait(url);

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    const response = await fetch(url, {
      signal: controller.signal,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
      },
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      logger?.add('download', url, `HTTP ${response.status}`, Date.now() - startTime);
      return {
        success: false,
        url,
        path: null,
        contentType: null,
        bytes: 0,
        error: `HTTP ${response.status}`,
        fromCache: false,
      };
    }

    // Check content length before downloading
    const contentLength = parseInt(response.headers.get('content-length') ?? '0', 10);
    if (contentLength > maxSize) {
      logger?.add('download', url, `Too large: ${contentLength} bytes`, Date.now() - startTime);
      return {
        success: false,
        url,
        path: null,
        contentType: null,
        bytes: 0,
        error: `File too large: ${contentLength} bytes`,
        fromCache: false,
      };
    }

    const contentType = response.headers.get('content-type');

    // Get filename from content-disposition or URL
    const contentDisposition = response.headers.get('content-disposition');
    let filename: string | undefined;
    if (contentDisposition) {
      const match = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
      if (match?.[1]) {
        filename = match[1].replace(/['"]/g, '');
      }
    }

    // Download content
    const buffer = Buffer.from(await response.arrayBuffer());

    // Verify size
    if (buffer.length > maxSize) {
      logger?.add('download', url, `Too large: ${buffer.length} bytes`, Date.now() - startTime);
      return {
        success: false,
        url,
        path: null,
        contentType,
        bytes: 0,
        error: `File too large: ${buffer.length} bytes`,
        fromCache: false,
      };
    }

    // Save to cache
    const savedPath = cache.saveDownload(url, buffer, contentType, filename);

    logger?.add('download', url, `OK (${buffer.length} bytes)`, Date.now() - startTime);

    return {
      success: true,
      url,
      path: savedPath,
      contentType,
      bytes: buffer.length,
      fromCache: false,
    };
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : 'Unknown error';
    logger?.add('download', url, `Error: ${errorMsg}`, Date.now() - startTime);

    return {
      success: false,
      url,
      path: null,
      contentType: null,
      bytes: 0,
      error: errorMsg,
      fromCache: false,
    };
  }
}

// Convert download result to output format
export function toDownloadedFile(result: DownloadResult): DownloadedFile | null {
  if (!result.success || !result.path) {
    return null;
  }

  return {
    url: result.url,
    path: result.path,
    content_type: result.contentType,
    bytes: result.bytes,
  };
}
