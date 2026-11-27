import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

assert.equal(process.env.BAKATA_CI_FIXTURES, '1');
const base = new URL(process.env.BAKATA_QA_URL || 'http://localhost:8080/');
assert(base.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(base.hostname));
const reports = new URL('./reports/', import.meta.url);
await mkdir(reports, { recursive: true });
const results = [], failures = [];
const browser = await chromium.launch();
for (const test of [
  { name: 'simple-stock', slug: 'ci-pdp-simple', quantity: '6' },
  { name: 'variable-stock', slug: 'ci-pdp-variable', quantity: '6', color: 'Verde' },
  { name: 'variable-missing-selection', slug: 'ci-pdp-variable', quantity: '2' },
]) {
  const context = await browser.newContext();
  await context.route('**/*', route => new URL(route.request().url()).origin === base.origin ? route.continue() : route.abort());
  const page = await context.newPage();
  try {
    await page.goto(new URL('product/' + test.slug + '/', base).href, { waitUntil: 'load' });
    const form = page.locator('.summary form.cart');
    if (test.color) {
      await page.waitForFunction(() => document.querySelector('.summary .single_add_to_cart_button')?.classList.contains('wc-variation-selection-needed'));
      await form.locator('select[name=attribute_color]').selectOption({ label: test.color });
      await page.waitForFunction(() => Number(document.querySelector('.summary input[name=variation_id]')?.value) > 0);
    }
    // Bypass client-side quantity/variation validation to exercise Woo's server validation.
    const [post] = await Promise.all([
      page.waitForResponse(r => r.request().isNavigationRequest() && r.request().method() === 'POST'),
      form.evaluate((element, quantity) => {
        element.querySelector('input.qty').value = quantity;
        const button = element.querySelector('.single_add_to_cart_button');
        if (button.name && !element.querySelector('input[name="add-to-cart"]')) {
          const field = document.createElement('input');
          field.type = 'hidden'; field.name = button.name; field.value = button.value;
          element.append(field);
        }
        HTMLFormElement.prototype.submit.call(element);
      }, test.quantity)
    ]);
    await page.waitForLoadState('load');
    assert.equal(post.status(), 200, 'Invalid submission must not trigger success redirect');
    await page.locator('.woocommerce-error, .wc-block-components-notice-banner.is-error').first().waitFor({ state: 'visible' });
    const items = await page.evaluate(async () => {
      const url = new URL(document.querySelector('link[rel="https://api.w.org/"]')?.href || '/wp-json/', location.href);
      if (url.origin !== location.origin) throw Error('Unexpected API origin');
      if (url.searchParams.has('rest_route')) url.searchParams.set('rest_route', '/wc/store/v1/cart');
      else url.pathname = url.pathname.replace(/\/?$/, '/') + 'wc/store/v1/cart';
      const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) throw Error('Store API ' + response.status);
      return (await response.json()).items;
    });
    assert.deepEqual(items, [], 'Rejected add must not change cart');
    results.push({ name: test.name, status: post.status(), cartItems: items.length });
  } catch (error) {
    failures.push({ name: test.name, error: String(error), url: page.url() });
    await page.screenshot({ path: fileURLToPath(new URL('failure-product-validation-' + test.name + '.png', reports)), fullPage: true }).catch(() => {});
  } finally {
    await context.close();
  }
}
await browser.close();
await writeFile(fileURLToPath(new URL('summary-product-validation.json', reports)), JSON.stringify({ results, failures }, null, 2));
console.log(JSON.stringify({ results, failures }));
if (failures.length) process.exitCode = 1;
