import * as fs from 'node:fs';
import * as path from 'node:path';
import * as crypto from 'node:crypto';

const CACHE_DIR = '.cache';
const PAGE_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours
const DOWNLOAD_TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

interface CacheMetadata {
  url: string;
  timestamp: number;
  status?: number;
  contentType?: string;
  size?: number;
}

function ensureDir(dir: string): void {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function urlHash(url: string): string {
  return crypto.createHash('sha256').update(url).digest('hex').slice(0, 16);
}

function getDomain(url: string): string {
  return new URL(url).hostname.replace(/[^a-z0-9.-]/gi, '_');
}

export class CacheManager {
  private baseDir: string;

  constructor(baseDir: string = CACHE_DIR) {
    this.baseDir = baseDir;
    ensureDir(this.baseDir);
    ensureDir(path.join(this.baseDir, 'pages'));
    ensureDir(path.join(this.baseDir, 'downloads'));
    ensureDir(path.join(this.baseDir, 'metadata'));
  }

  // Page cache
  getPagePath(url: string): string {
    const domain = getDomain(url);
    const hash = urlHash(url);
    return path.join(this.baseDir, 'pages', domain, `${hash}.html`);
  }

  hasValidPageCache(url: string): boolean {
    const pagePath = this.getPagePath(url);
    const metaPath = this.getMetadataPath(url);

    if (!fs.existsSync(pagePath) || !fs.existsSync(metaPath)) {
      return false;
    }

    try {
      const meta: CacheMetadata = JSON.parse(fs.readFileSync(metaPath, 'utf-8'));
      return Date.now() - meta.timestamp < PAGE_TTL_MS;
    } catch {
      return false;
    }
  }

  getCachedPage(url: string): string | null {
    if (!this.hasValidPageCache(url)) {
      return null;
    }
    return fs.readFileSync(this.getPagePath(url), 'utf-8');
  }

  savePage(url: string, html: string, status = 200): void {
    const pagePath = this.getPagePath(url);
    ensureDir(path.dirname(pagePath));
    fs.writeFileSync(pagePath, html);
    this.saveMetadata(url, { status, contentType: 'text/html', size: html.length });
  }

  // Download cache
  getDownloadPath(url: string, originalFilename?: string): string {
    const domain = getDomain(url);
    const ext = originalFilename
      ? path.extname(originalFilename)
      : path.extname(new URL(url).pathname) || '.bin';
    const hash = urlHash(url);
    return path.join(this.baseDir, 'downloads', domain, `${hash}${ext}`);
  }

  hasValidDownloadCache(url: string): boolean {
    // For downloads, we check any file matching the hash pattern
    const domain = getDomain(url);
    const hash = urlHash(url);
    const downloadDir = path.join(this.baseDir, 'downloads', domain);

    if (!fs.existsSync(downloadDir)) {
      return false;
    }

    const files = fs.readdirSync(downloadDir);
    const matchingFile = files.find(f => f.startsWith(hash));

    if (!matchingFile) {
      return false;
    }

    const metaPath = this.getMetadataPath(url);
    if (!fs.existsSync(metaPath)) {
      return false;
    }

    try {
      const meta: CacheMetadata = JSON.parse(fs.readFileSync(metaPath, 'utf-8'));
      return Date.now() - meta.timestamp < DOWNLOAD_TTL_MS;
    } catch {
      return false;
    }
  }

  getCachedDownloadPath(url: string): string | null {
    const domain = getDomain(url);
    const hash = urlHash(url);
    const downloadDir = path.join(this.baseDir, 'downloads', domain);

    if (!fs.existsSync(downloadDir)) {
      return null;
    }

    const files = fs.readdirSync(downloadDir);
    const matchingFile = files.find(f => f.startsWith(hash));

    if (!matchingFile) {
      return null;
    }

    return path.join(downloadDir, matchingFile);
  }

  saveDownload(url: string, data: Buffer, contentType: string | null, originalFilename?: string): string {
    const downloadPath = this.getDownloadPath(url, originalFilename);
    ensureDir(path.dirname(downloadPath));
    fs.writeFileSync(downloadPath, data);
    this.saveMetadata(url, { status: 200, contentType: contentType ?? undefined, size: data.length });
    return downloadPath;
  }

  // Metadata
  private getMetadataPath(url: string): string {
    const hash = urlHash(url);
    return path.join(this.baseDir, 'metadata', `${hash}.json`);
  }

  private saveMetadata(url: string, extra: Partial<CacheMetadata>): void {
    const metaPath = this.getMetadataPath(url);
    ensureDir(path.dirname(metaPath));
    const metadata: CacheMetadata = {
      url,
      timestamp: Date.now(),
      ...extra,
    };
    fs.writeFileSync(metaPath, JSON.stringify(metadata, null, 2));
  }

  getMetadata(url: string): CacheMetadata | null {
    const metaPath = this.getMetadataPath(url);
    if (!fs.existsSync(metaPath)) {
      return null;
    }
    try {
      return JSON.parse(fs.readFileSync(metaPath, 'utf-8'));
    } catch {
      return null;
    }
  }

  // Utility
  clear(): void {
    if (fs.existsSync(this.baseDir)) {
      fs.rmSync(this.baseDir, { recursive: true });
    }
    ensureDir(this.baseDir);
  }
}

// Default singleton instance
export const cache = new CacheManager();
