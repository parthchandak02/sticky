// Screenshot rendered Sticky screens at native panel size (1x) and export hotspots.
// Called by render_screens.py with a jobs.json path.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';

// Playwright from this project if installed, else from the cook repo (this machine's copy).
function loadPlaywright() {
  for (const base of [process.cwd() + '/', join(homedir(), 'projects/cook/')]) {
    try { return createRequire(base)('playwright'); } catch { /* next */ }
  }
  throw new Error('playwright not found: npm i -D playwright');
}
const { chromium } = loadPlaywright();

const jobs = JSON.parse(readFileSync(process.argv[2], 'utf8'));
import { existsSync, readdirSync } from 'node:fs';
// Fall back to any Chromium already on the machine when Playwright's pinned build is missing.
async function launch() {
  try { return await chromium.launch(); } catch (err) {
    const roots = [process.env.STICKY_CHROMIUM_DIR, '/opt/ms-playwright', '/opt/pw-browsers'].filter(Boolean);
    for (const r of roots) {
      if (!existsSync(r)) continue;
      for (const d of readdirSync(r).filter((n) => n.startsWith('chromium-')).sort().reverse()) {
        for (const sub of ['chrome-linux64/chrome', 'chrome-linux/chrome']) {
          const exe = join(r, d, sub);
          if (existsSync(exe)) return chromium.launch({ executablePath: exe });
        }
      }
    }
    throw err;
  }
}
const browser = await launch();
const out = {};
for (const j of jobs) {
  const page = await browser.newPage({ viewport: { width: j.w, height: j.h }, deviceScaleFactor: 1 });
  await page.goto('file://' + j.html);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(150);
  await page.screenshot({ path: j.png });
  out[j.id] = await page.evaluate(() =>
    [...document.querySelectorAll('[data-tap],[data-hold]')].map((el) => {
      const r = el.getBoundingClientRect();
      return {
        kind: el.dataset.hold ? 'hold' : 'tap',
        action: el.dataset.hold || el.dataset.tap,
        x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      };
    }));
  await page.close();
}
await browser.close();
writeFileSync(join(dirname(process.argv[2]), 'hotspots.new.json'), JSON.stringify(out));
