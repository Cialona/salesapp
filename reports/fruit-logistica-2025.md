# Fruit Logistica - Test Report

**Test ID:** fruit-logistica-2025
**Status:** ❌ FAILED
**Runtime:** 0s
**Generated:** 2026-02-03T16:49:42.407Z

## Failures

- ❌ Expected official domain fruitlogistica.com, got null
- ❌ Expected exhibitor manual, but quality is missing
- ❌ Expected schedule data, but none found

## Warnings

- ⚠️ Expected at least 2 schedule entries, got 0

## Input

```json
{
  "id": "fruit-logistica-2025",
  "fair_name": "Fruit Logistica",
  "known_url": "https://www.fruitlogistica.com",
  "city": "Berlin",
  "country": "Germany",
  "expected": {
    "official_domain": "fruitlogistica.com",
    "has_manual": true,
    "has_schedule": true,
    "schedule_in_pdf": true,
    "min_schedule_entries": 2
  }
}
```

## Results

| Field | Quality | URL |
|-------|---------|-----|
| Official | - | - |
| Floorplan | missing | - |
| Manual | missing | - |
| Rules | missing | - |
| Schedule | missing | - |
| Directory | missing | - |

## Schedule Entries

- Build-up: 0 entries
- Tear-down: 0 entries

## Debug Stats

- Pages visited: 1
- Files downloaded: 0
- Blocked URLs: 1
- Action log entries: 3

### Blocked URLs

- https://www.fruitlogistica.com: browserType.launch: Executable doesn't exist at /root/.cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell
╔═════════════════════════════════════════════════════════════════════════╗
║ Looks like Playwright Test or Playwright was just installed or updated. ║
║ Please run the following command to download new browsers:              ║
║                                                                         ║
║     pnpm exec playwright install                                        ║
║                                                                         ║
║ <3 Playwright Team                                                      ║
╚═════════════════════════════════════════════════════════════════════════╝

## Evidence

### floorplan

**Reasoning:** No candidates found


### exhibitor_manual

**Reasoning:** No candidates found


### rules

**Reasoning:** No candidates found


### schedule

**Reasoning:** No candidates found


### exhibitor_directory

**Reasoning:** No candidates found

