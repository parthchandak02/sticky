// Drive the prototype like a person: tap, hold, swipe, buttons, rotate. Checks each step
// lands on the expected frame, and records a video of the whole run.
//   node scripts/proto_test.mjs http://127.0.0.1:8786/prototype/ out_dir
import { mkdirSync, readdirSync, existsSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { join } from 'node:path';

function loadPlaywright() {
  for (const base of [process.cwd() + '/', join(homedir(), 'projects/cook/')]) {
    try { return createRequire(base)('playwright'); } catch { /* next */ }
  }
  throw new Error('playwright not found');
}
const { chromium } = loadPlaywright();
async function launch() {
  try { return await chromium.launch(); } catch (err) {
    for (const r of ['/opt/ms-playwright', '/opt/pw-browsers']) {
      if (!existsSync(r)) continue;
      for (const d of readdirSync(r).filter((n) => n.startsWith('chromium-')).sort().reverse()) {
        const exe = join(r, d, 'chrome-linux64/chrome');
        if (existsSync(exe)) return chromium.launch({ executablePath: exe });
      }
    }
    throw err;
  }
}

const url = process.argv[2], out = process.argv[3] || 'cook/stills/proto';
mkdirSync(out, { recursive: true });
const browser = await launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
// Record with the DevTools screencast (frames + timestamps); ffmpeg joins them afterwards.
mkdirSync(`${out}/frames`, { recursive: true });
const cdp = await ctx.newCDPSession(page);
const shots = [];
cdp.on('Page.screencastFrame', async (f) => {
  const file = `${out}/frames/f${String(shots.length).padStart(5, '0')}.jpg`;
  shots.push({ file, t: f.metadata.timestamp });
  writeFileSync(file, Buffer.from(f.data, 'base64'));
  await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
});
await page.goto(url);
await page.waitForFunction(() => window.sticky && document.getElementById('touch').innerHTML.length > 0);
await page.waitForTimeout(600);
await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 85, maxWidth: 1440, maxHeight: 900 });
await page.waitForTimeout(800);

const cur = () => page.evaluate(() => window.sticky.cur);
const idle = () => page.waitForFunction(() => !window.sticky.busy);
async function glassPoint(fx, fy) {
  return page.evaluate(([fx, fy]) => {
    const r = document.getElementById('touch').getBoundingClientRect();
    return { x: r.left + fx * r.width, y: r.top + fy * r.height };
  }, [fx, fy]);
}
async function tapFrame(fx, fy) { const p = await glassPoint(fx, fy); await page.mouse.move(p.x, p.y); await page.mouse.down(); await page.waitForTimeout(90); await page.mouse.up(); }
async function holdFrame(fx, fy, ms) { const p = await glassPoint(fx, fy); await page.mouse.move(p.x, p.y); await page.mouse.down(); await page.waitForTimeout(ms); await page.mouse.up(); }
async function swipe(dir) {
  const a = await glassPoint(0.5, 0.5);
  const d = { left: [-260, 0], right: [260, 0], up: [0, -200], down: [0, 200] }[dir];
  await page.mouse.move(a.x, a.y); await page.mouse.down();
  for (let i = 1; i <= 8; i++) { await page.mouse.move(a.x + d[0] * i / 8, a.y + d[1] * i / 8); await page.waitForTimeout(16); }
  await page.mouse.up();
}

const results = [];
let n = 0;
async function step(name, fn, expect) {
  await fn();
  await page.waitForTimeout(400); await idle(); await page.waitForTimeout(300);
  const got = await cur();
  const ok = got === expect;
  results.push(`${ok ? 'ok  ' : 'FAIL'} ${name}: ${got}${ok ? '' : ' (wanted ' + expect + ')'}`);
  n++; await page.screenshot({ path: `${out}/P${String(n).padStart(2, '0')}-${expect}.png` });
}

// Board: tap the waiting card opens the permission screen
await step('tap waiting card', () => tapFrame(0.55, 0.30), 'approve');
await step('release hold early', () => holdFrame(0.814, 0.375, 350), 'approve');
await step('hold the dial 1.3 s', () => holdFrame(0.814, 0.375, 1300), 'board_allowed');
await step('swipe left', () => swipe('left'), 'today');
await step('swipe left', () => swipe('left'), 'countdown');
await step('page down button', () => page.click('#k-down'), 'photo');
await step('tap heart', () => tapFrame(0.9375, 0.896), 'photo_hearted');
await step('swipe up for more', () => swipe('up'), 'onthisday');
await step('swipe left', () => swipe('left'), 'note');
await step('swipe right', () => swipe('right'), 'photo');
await step('turn it', () => page.click('#b-rotate'), 'reader_1');
await step('tap right edge', () => tapFrame(0.8, 0.5), 'reader_2');
await step('swipe down', () => swipe('down'), 'reader_1');
await step('turn back', () => page.click('#b-rotate'), 'board');
// AI button: hold to talk, let go to send
const ai = await page.locator('#k-ai').boundingBox();
await step('hold talk button', async () => { await page.mouse.move(ai.x + ai.width / 2, ai.y + 6); await page.mouse.down(); await page.waitForTimeout(1600); }, 'listening');
await step('let go', async () => { await page.mouse.up(); await page.waitForTimeout(1600); }, 'voice_result');
await step('tap done', () => tapFrame(0.9, 0.57), 'board');
await step('leave it alone', () => page.click('#b-sleep'), 'art');
await step('press up to wake', () => page.click('#k-up'), 'board');

await page.waitForTimeout(800);
await cdp.send('Page.stopScreencast');
const list = shots.map((s, i) => `file '${s.file.split('/').pop()}'\nduration ${((shots[i + 1]?.t ?? s.t + 1) - s.t).toFixed(3)}`).join('\n');
writeFileSync(`${out}/frames/list.txt`, list + `\nfile '${shots.at(-1).file.split('/').pop()}'\n`);
await ctx.close(); await browser.close();
console.log(results.join('\n'));
