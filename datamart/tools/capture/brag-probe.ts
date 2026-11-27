// Local only: signs in to the seeded sandbox workspace and screenshots each route for the demo film.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { ensureSession } from "../lib/auth.ts";
import { env, assertLocal } from "../lib/env.ts";

const OUT = process.argv[2];
const routes = process.argv.slice(3);
assertLocal(env.webURL);
mkdirSync(OUT, { recursive: true });

const state = await ensureSession({ email: "sandbox@warmbly.test", password: "password123" });
const browser = await chromium.launch({ channel: "chrome" });
const ctx = await browser.newContext({ storageState: state, viewport: { width: 1920, height: 1080 }, deviceScaleFactor: Number(process.env.DSF ?? 1), colorScheme: "light" });
const page = await ctx.newPage();
for (const r of routes) {
  const [path, name] = r.split("=");
  await page.goto(env.webURL + path, { waitUntil: "networkidle" }).catch(() => {});
  await page.waitForTimeout(2000);
  const skip = page.getByRole("button", { name: /skip tour/i }).first();
  if (await skip.isVisible().catch(() => false)) { await skip.click(); await page.waitForTimeout(800); }
  await page.mouse.move(1919, 1079);
  await page.waitForTimeout(700);
  const file = `${OUT}/${name ?? path.replace(/\W+/g, "_")}.png`;
  await page.screenshot({ path: file });
  console.log(file, page.url());
}
await browser.close();
