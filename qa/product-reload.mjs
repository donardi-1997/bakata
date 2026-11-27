import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

assert.equal(process.env.BAKATA_CI_FIXTURES, '1', 'Disposable fixtures required');
const base = new URL(process.env.BAKATA_QA_URL || 'http://localhost:8080/');
assert(['localhost', '127.0.0.1'].includes(base.hostname) && base.protocol === 'http:', 'Only local HTTP fixtures are allowed');
const expectCart = process.env.BAKATA_EXPECT_CART_REDIRECT === '1';
const cartPath = process.env.BAKATA_EXPECT_CART_PATH || '/cart/';
assert(cartPath.startsWith('/') && !cartPath.startsWith('//') && !cartPath.includes('?') && !cartPath.includes('#'), 'Cart path must be local');
const reports = new URL('./reports/', import.meta.url);
await mkdir(reports, { recursive: true });
const results = [], failures = [];
const browser = await chromium.launch();

async function cart(page) {
  return page.evaluate(async () => {
    const url = new URL(document.querySelector('link[rel="https://api.w.org/"]')?.href || '/wp-json/', location.href);
    if (url.origin !== location.origin) throw Error('Unexpected API origin');
    if (url.searchParams.has('rest_route')) url.searchParams.set('rest_route', '/wc/store/v1/cart');
    else url.pathname = url.pathname.replace(/\/?$/, '/') + 'wc/store/v1/cart';
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw Error('Store API: ' + response.status);
    const data = await response.json();
    return data.items.map(({ id, quantity, variation }) => ({ id, quantity, variation }));
  });
}

async function run(slug, variable) {
  const context = await browser.newContext({ viewport: { width: 375, height: 900 } });
  await context.route('**/*', route => new URL(route.request().url()).origin === base.origin ? route.continue() : route.abort());
  const page = await context.newPage();
  let phase = 'open';
  const navigation = [];
  page.on('request', request => {
    if (request.isNavigationRequest() && request.frame() === page.mainFrame()) {
      const url = new URL(request.url());
      navigation.push({ method: request.method(), path: url.pathname + url.search });
    }
  });
  try {
    const response = await page.goto(new URL('product/' + slug + '/', base).href, { waitUntil: 'load' });
    assert(response?.ok(), 'Product page failed');
    assert.deepEqual(await cart(page), [], 'New browser context must have an empty cart');
    const form = page.locator('.summary form.cart');
    let id;
    if (variable) {
      const select = form.locator('select[name=attribute_color]');
      await page.waitForFunction(() => document.querySelector('.summary .single_add_to_cart_button')?.classList.contains('wc-variation-selection-needed'));
      await select.selectOption({ label: 'Verde' });
      await page.waitForFunction(() => Number(document.querySelector('.summary input[name=variation_id]')?.value) > 0 && !document.querySelector('.summary .single_add_to_cart_button')?.classList.contains('disabled'));
      id = Number(await form.locator('input[name=variation_id]').inputValue());
    } else {
      id = Number(await form.locator('[name=add-to-cart]').getAttribute('value'));
    }
    assert(id > 0, 'Expected fixture ID');
    await form.locator('input.qty').fill('2');
    phase = 'add';
    const [post, destination] = await Promise.all([
      page.waitForResponse(r => r.request().isNavigationRequest() && r.request().method() === 'POST' && new URL(r.url()).origin === base.origin),
      page.waitForResponse(r => r.request().isNavigationRequest() && r.request().method() === 'GET' && r.request().redirectedFrom()?.method() === 'POST'),
      form.locator('.single_add_to_cart_button').click()
    ]);
    await page.waitForLoadState('load');
    assert(destination.ok(), 'Redirect destination succeeded');
    assert.equal(destination.request().redirectedFrom(), post.request(), 'GET follows the actual add POST');
    assert.equal(new URL(destination.url()).origin, base.origin, 'Redirect remains local');
    if (expectCart) assert.equal(new URL(destination.url()).pathname.replace(/\/$/, ''), cartPath.replace(/\/$/, ''), 'Configured cart destination');
    else assert.equal(new URL(destination.url()).pathname, new URL('product/' + slug + '/', base).pathname, 'Product destination');
    const before = await cart(page);
    assert.equal(before.length, 1, 'Exactly one cart line');
    assert.equal(before[0].id, id, 'Store API product or variation ID');
    assert.equal(before[0].quantity, 2, 'Store API quantity before reload');
    if (variable) assert(before[0].variation.some(v => String(v.value).toLowerCase() === 'verde'), 'Store API selected variation');
    else assert.deepEqual(before[0].variation, [], 'Simple product has no variation');
    const postIndex = navigation.findIndex(n => n.method === 'POST');
    assert(postIndex >= 0, 'Native add uses POST');
    assert([302, 303].includes(post.status()), 'POST must redirect safely, got ' + post.status());
    assert.equal(navigation[postIndex + 1]?.method, 'GET', 'POST must redirect to a GET document');
    phase = 'reload';
    const beforeReloadCount = navigation.length;
    const reload = await page.reload({ waitUntil: 'load' });
    assert(reload?.ok(), 'Reload succeeded');
    assert.equal(reload.request().method(), 'GET', 'Reload must not replay POST');
    assert(navigation.slice(beforeReloadCount).every(n => n.method === 'GET'), 'Reload navigation must use only GET');
    const after = await cart(page);
    assert.deepEqual(after, before, 'ID, variation and quantity survive reload unchanged');
    results.push({ slug, id, before, after, postStatus: post.status(), navigation });
  } catch (error) {
    failures.push({ slug, phase, error: String(error), navigation });
    await page.screenshot({ path: fileURLToPath(new URL('failure-product-reload-' + slug + '.png', reports)), fullPage: true }).catch(() => {});
  } finally {
    await context.close();
  }
}

try {
  await run('ci-pdp-simple', false);
  await run('ci-pdp-variable', true);
} finally {
  await browser.close();
  await writeFile(fileURLToPath(new URL('summary-product-reload.json', reports)), JSON.stringify({ results, failures }, null, 2));
}
console.log(JSON.stringify({ results, failures }));
if (failures.length) process.exitCode = 1;
