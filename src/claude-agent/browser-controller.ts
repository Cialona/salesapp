/**
 * Browser Controller for Claude Computer Use
 *
 * This module provides a browser interface that Claude can control
 * via screenshots and mouse/keyboard actions.
 */

import { chromium, type Browser, type Page } from 'playwright';
import * as fs from 'node:fs';
import * as path from 'node:path';

export interface ScreenshotResult {
  base64: string;
  width: number;
  height: number;
}

export interface BrowserState {
  url: string;
  title: string;
}

export interface DownloadedFile {
  originalUrl: string;
  localPath: string;
  filename: string;
}

export class BrowserController {
  private browser: Browser | null = null;
  private page: Page | null = null;
  private width: number;
  private height: number;
  private downloadDir: string;
  private downloads: DownloadedFile[] = [];

  constructor(width = 1280, height = 800) {
    this.width = width;
    this.height = height;
    this.downloadDir = path.join(process.cwd(), '.cache', 'downloads');

    // Ensure download directory exists
    if (!fs.existsSync(this.downloadDir)) {
      fs.mkdirSync(this.downloadDir, { recursive: true });
    }
  }

  async launch(): Promise<void> {
    this.browser = await chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });

    const context = await this.browser.newContext({
      viewport: { width: this.width, height: this.height },
      acceptDownloads: true,
    });

    this.page = await context.newPage();

    // Handle downloads - track original URL and local path
    this.page.on('download', async (download) => {
      const filename = download.suggestedFilename();
      const filepath = path.join(this.downloadDir, filename);
      const originalUrl = download.url();

      await download.saveAs(filepath);

      // Store download info with original URL
      this.downloads.push({
        originalUrl,
        localPath: filepath,
        filename,
      });

      console.log(`[DOWNLOAD] Saved: ${filename}`);
      console.log(`[DOWNLOAD] Original URL: ${originalUrl}`);
    });
  }

  async close(): Promise<void> {
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
      this.page = null;
    }
  }

  async screenshot(): Promise<ScreenshotResult> {
    if (!this.page) throw new Error('Browser not launched');

    const buffer = await this.page.screenshot({ type: 'png' });
    const base64 = buffer.toString('base64');

    return {
      base64,
      width: this.width,
      height: this.height,
    };
  }

  async getState(): Promise<BrowserState> {
    if (!this.page) throw new Error('Browser not launched');

    return {
      url: this.page.url(),
      title: await this.page.title(),
    };
  }

  // Computer Use Actions

  async click(x: number, y: number): Promise<void> {
    if (!this.page) throw new Error('Browser not launched');
    await this.page.mouse.click(x, y);
    await this.page.waitForTimeout(500); // Wait for any navigation/animation
  }

  async doubleClick(x: number, y: number): Promise<void> {
    if (!this.page) throw new Error('Browser not launched');
    await this.page.mouse.dblclick(x, y);
    await this.page.waitForTimeout(500);
  }

  async rightClick(x: number, y: number): Promise<void> {
    if (!this.page) throw new Error('Browser not launched');
    await this.page.mouse.click(x, y, { button: 'right' });
    await this.page.waitForTimeout(300);
  }

  async moveMouse(x: number, y: number): Promise<void> {
    if (!this.page) throw new Error('Browser not launched');
    await this.page.mouse.move(x, y);
  }

  async drag(startX: number, startY: number, endX: number, endY: number): Promise<void> {
    if (!this.page) throw new Error('Browser not launched');
    await this.page.mouse.move(startX, startY);
    await this.page.mouse.down();
    await this.page.mouse.move(endX, endY);
    await this.page.mouse.up();
  }

  async type(text: string): Promise<void> {
    if (!this.page) throw new Error('Browser not launched');
    await this.page.keyboard.type(text, { delay: 50 });
  }

  async pressKey(key: string): Promise<void> {
    if (!this.page) throw new Error('Browser not launched');
    // Map common key names
    const keyMap: Record<string, string> = {
      'enter': 'Enter',
      'return': 'Enter',
      'tab': 'Tab',
      'escape': 'Escape',
      'esc': 'Escape',
      'backspace': 'Backspace',
      'delete': 'Delete',
      'up': 'ArrowUp',
      'down': 'ArrowDown',
      'left': 'ArrowLeft',
      'right': 'ArrowRight',
      'home': 'Home',
      'end': 'End',
      'pageup': 'PageUp',
      'pagedown': 'PageDown',
      'space': ' ',
    };

    const mappedKey = keyMap[key.toLowerCase()] || key;
    await this.page.keyboard.press(mappedKey);
  }

  async hotkey(...keys: string[]): Promise<void> {
    if (!this.page) throw new Error('Browser not launched');
    // Press all modifier keys, then the final key
    const modifiers = keys.slice(0, -1);
    const finalKey = keys[keys.length - 1] || '';

    for (const mod of modifiers) {
      await this.page.keyboard.down(mod);
    }
    await this.page.keyboard.press(finalKey);
    for (const mod of modifiers.reverse()) {
      await this.page.keyboard.up(mod);
    }
  }

  async scroll(x: number, y: number, deltaX: number, deltaY: number): Promise<void> {
    if (!this.page) throw new Error('Browser not launched');
    await this.page.mouse.move(x, y);
    await this.page.mouse.wheel(deltaX, deltaY);
    await this.page.waitForTimeout(300);
  }

  async goto(url: string): Promise<void> {
    if (!this.page) throw new Error('Browser not launched');
    await this.page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await this.page.waitForTimeout(1000); // Extra wait for dynamic content
  }

  async waitForNavigation(timeout = 10000): Promise<void> {
    if (!this.page) throw new Error('Browser not launched');
    try {
      await this.page.waitForNavigation({ timeout });
    } catch {
      // Timeout is ok - page might not navigate
    }
  }

  // Get downloaded files with their original URLs
  getDownloadedFiles(): DownloadedFile[] {
    return this.downloads;
  }

  // Clear download tracking (for reuse)
  clearDownloads(): void {
    this.downloads = [];
  }

  // Get current page content (for PDF detection, etc.)
  async getPageContent(): Promise<string> {
    if (!this.page) throw new Error('Browser not launched');
    return await this.page.content();
  }

  // Check if current page is a PDF
  async isPdfPage(): Promise<boolean> {
    if (!this.page) throw new Error('Browser not launched');
    const url = this.page.url();
    return url.toLowerCase().endsWith('.pdf') || url.includes('/pdf/');
  }

  getDisplaySize(): { width: number; height: number } {
    return { width: this.width, height: this.height };
  }
}
