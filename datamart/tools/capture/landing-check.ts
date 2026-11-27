// Local only: renders the landing page from disk and screenshots it at desktop and phone widths.
import { chromium } from "@playwright/test";
const [file, out] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "chrome" });
for (const [name, w, h, cs] of [["desk", 1440, 900, "light"], ["phone", 390, 844, "light"], ["dark", 1440, 900, "dark"]] as const) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1, colorScheme: cs });
  const page = await ctx.newPage();
  const errs: string[] = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  page.on("requestfailed", (r) => errs.push("failed " + r.url()));
  await page.goto(file.startsWith("http") ? file : "file://" + file);
  await page.evaluate(() => document.querySelectorAll(".reveal").forEach((e) => e.classList.add("in")));
  await page.evaluate(async () => { for (const i of Array.from(document.images)) { i.loading = "eager"; } });
  await page.waitForTimeout(1500);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  console.log(name, "overflow", overflow, "errors", errs);
  await page.locator("#product").screenshot({ path: `${out}/${name}-product.png` });
  await page.locator("#tour").screenshot({ path: `${out}/${name}-tour.png` });
  await page.locator("#more").screenshot({ path: `${out}/${name}-more.png` });
  if (name === "desk") {
    await page.click("#tab-molty");
    await page.waitForTimeout(500);
    await page.locator("#product").screenshot({ path: `${out}/${name}-product-molty.png` });
    await page.focus("#tab-molty"); await page.keyboard.press("ArrowRight");
    console.log("after ArrowRight selected:", await page.evaluate(() => document.querySelector('[aria-selected="true"]')?.id));
    await page.click('#tour-chapters button[data-t="136.0"]');
    await page.waitForTimeout(2500);
    console.log("video t", await page.evaluate(() => (document.getElementById("tour-video") as HTMLVideoElement).currentTime),
      "current chapter", await page.evaluate(() => document.querySelector('#tour-chapters [aria-current="true"]')?.textContent));
    await page.locator("#tour").screenshot({ path: `${out}/${name}-tour-playing.png` });
    await page.screenshot({ path: `${out}/${name}-hero.png` });
  }
  await ctx.close();
}
await browser.close();
