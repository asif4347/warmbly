// Local only: interactive captures of the seeded sandbox for the demo film.
import { chromium, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { ensureSession } from "../lib/auth.ts";
import { env, assertLocal } from "../lib/env.ts";

const OUT = process.argv[2];
const only = process.argv.slice(3);
assertLocal(env.webURL);
mkdirSync(OUT, { recursive: true });
const boxes: Record<string, unknown> = {};

const state = await ensureSession({ email: "sandbox@warmbly.test", password: "password123" });
const browser = await chromium.launch({ channel: "chrome" });
const ctx = await browser.newContext({ storageState: state, viewport: { width: 1920, height: 1080 }, deviceScaleFactor: Number(process.env.DSF ?? 1), colorScheme: "light" });
const page = await ctx.newPage();

async function go(path: string) {
  await page.goto(env.webURL + path, { waitUntil: "networkidle" }).catch(() => {});
  await page.waitForTimeout(1800);
  const skip = page.getByRole("button", { name: /skip tour/i }).first();
  if (await skip.isVisible().catch(() => false)) { await skip.click(); await page.waitForTimeout(800); }
}
async function shot(name: string) {
  await page.mouse.move(1919, 1079);
  await page.waitForTimeout(900);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log("shot", name, page.url());
}
async function box(name: string, loc: ReturnType<Page["locator"]>) {
  const b = await loc.first().boundingBox().catch(() => null);
  if (b) boxes[name] = b;
}

const steps: Record<string, () => Promise<void>> = {
  async mailbox() {
    await go("/app/emails");
    await page.getByText("elena.voss@sunrise.test").first().click();
    await page.waitForTimeout(2500);
    await shot("mailbox");
  },
  async addaccount() {
    await go("/app/emails");
    await page.getByRole("button", { name: /add account/i }).first().click();
    await page.waitForTimeout(1500);
    await shot("add-account");
  },
  async thread() {
    await go("/app/unibox/all");
    await page.getByText(/Eli Grant/).first().click().catch(async () => {
      await page.locator("[data-thread-id], li, [role=row]").nth(2).click();
    });
    await page.waitForTimeout(2500);
    await shot("thread");
  },
  async molty() {
    await go("/app/campaigns");
    const btn = page.getByRole("button", { name: /molty/i }).first();
    if (await btn.isVisible().catch(() => false)) await btn.click();
    else await page.mouse.click(1890, 1050);
    await page.waitForTimeout(2000);
    await shot("molty");
  },
  async dealsboard() {
    await go("/app/crm/deals");
    const b = page.getByRole("button", { name: /^board$/i }).first();
    if (await b.isVisible().catch(() => false)) { await b.click(); await page.waitForTimeout(1500); }
    await shot("deals-board");
  },
  async placement() {
    await go("/app/placement");
    await shot("placement");
    const row = page.getByText("elena.voss@sunrise.test").first();
    if (await row.isVisible().catch(() => false)) { await row.click(); await page.waitForTimeout(2500); await shot("placement-test"); }
  },
  async meetings() {
    await go("/app/crm/meetings");
    await shot("meetings");
  },
  async emails() {
    await go("/app/emails");
    await page.waitForTimeout(4000);
    await shot("emails");
  },
  async tour() {
    await page.goto(env.webURL + "/app/emails", { waitUntil: "networkidle" }).catch(() => {});
    await page.waitForTimeout(2500);
    const start = page.getByRole("button", { name: /show me around/i }).first();
    if (!(await start.isVisible().catch(() => false))) {
      await page.getByText("Sunny Sandbox").first().click();
      await page.waitForTimeout(800);
      await page.getByText(/tour/i).last().click();
      await page.waitForTimeout(2000);
    }
    await start.click();
    for (let i = 2; i <= 21; i++) {
      await page.waitForTimeout(1600);
      const title = (await page.locator("h2, h3").filter({ hasText: /\./ }).first().textContent().catch(() => "")) ?? "";
      if (/Ask about anything|let it do the work|any channel|with the team/i.test(title)) await shot(`tour-${i}`);
      const next = page.getByRole("button", { name: /^(next|continue)/i }).first();
      if (!(await next.isVisible().catch(() => false))) { await page.keyboard.press("ArrowRight"); continue; }
      await next.click();
    }
  },
};

for (const [name, fn] of Object.entries(steps)) {
  if (only.length && !only.includes(name)) continue;
  try { await fn(); } catch (e) { console.log("fail", name, String(e).slice(0, 200)); }
}
writeFileSync(`${OUT}/boxes.json`, JSON.stringify(boxes, null, 2));
await browser.close();
