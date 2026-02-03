const lastRequestByHost = new Map<string, number>();

const MIN_DELAY_MS = 700;
const MAX_DELAY_MS = 1200;

function randomDelay(): number {
  return MIN_DELAY_MS + Math.random() * (MAX_DELAY_MS - MIN_DELAY_MS);
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export async function rateLimitedWait(url: string): Promise<void> {
  const host = new URL(url).hostname;
  const lastRequest = lastRequestByHost.get(host) || 0;
  const now = Date.now();
  const elapsed = now - lastRequest;
  const requiredDelay = randomDelay();

  if (elapsed < requiredDelay) {
    const waitTime = requiredDelay - elapsed;
    await sleep(waitTime);
  }

  lastRequestByHost.set(host, Date.now());
}

export function clearRateLimits(): void {
  lastRequestByHost.clear();
}
