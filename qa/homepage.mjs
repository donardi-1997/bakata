import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { chromium } from 'playwright';

const require = createRequire(import.meta.url);
const base = new URL('http://localhost:8080/');
const mode = process.argv[2] ?? 'populated';
assert(['empty', 'populated'].includes(mode));
assert.equal(process.env.BAKATA_CI_FIXTURES, '1', 'Use only disposable local QA data');
const reportDir = new URL('./reports/', import.meta.url);
await mkdir(reportDir, { recursive: true });
const output = (name) => new URL(name, reportDir).pathname;
const browser = await chromium.launch({ headless: true });
const widths = mode === 'empty' ? [375, 1440] : [320, 375, 576, 768, 1024, 1440, 1920];
const results = [];
const failures = [];
const tags = ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'];

async function openHome(page) {
  const response = await page.goto(base.href, { waitUntil: 'load' });
  assert(response?.ok(), 'Homepage request failed');
  await page.evaluate(() => document.fonts.ready);
}
async function visible(locator, message) {
  await locator.waitFor({ state: 'visible', timeout: 10000 });
  assert(await locator.isVisible(), message);
}
async function localContext(width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce', locale: 'es-CO' });
  // The QA browser cannot make requests to suppliers, payment systems, or CDNs.
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    return url.origin === base.origin ? route.continue() : route.abort();
  });
  return context;
}

async function checkLayout(width) {
  const context = await localContext(width);
  const page = await context.newPage();
  const errors = [];
  const localFailures = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('response', response => {
    if (new URL(response.url()).origin === base.origin && response.status() >= 400)
      localFailures.push(response.status() + ' ' + new URL(response.url()).pathname);
  });
  try {
    await openHome(page);
    for (const selector of ['.bk-store-header','.bk-hero','.bk-trust','.bk-categories','.bk-featured','.bk-store-footer']) {
      await visible(page.locator(selector), selector);
    }
    assert.equal(await page.locator('main h1').count(), 1, 'One main H1 required');
    assert.equal(await page.locator('.bk-product-card').count(), mode === 'empty' ? 0 : 2);
    assert.equal(await page.locator('.bk-catalog-empty').count(), mode === 'empty' ? 2 : 0);
    await page.locator('.bk-store-footer').scrollIntoViewIfNeeded();
    await page.locator('.bk-hero').scrollIntoViewIfNeeded();
    const layout = await page.evaluate(() => {
      const root = document.documentElement;
      const fonts = ['Inter','Plus Jakarta Sans'].map(f => ({
        name: f,
        loaded: [...document.fonts].some(face => face.family.replace(/['"]/g, '') === f && face.status === 'loaded')
      }));
      const img = document.querySelector('.bk-hero__media img');
      return { viewport: root.clientWidth, scrollWidth: root.scrollWidth, fonts,
        imageLoaded: !!img?.complete && img.naturalWidth > 0 };
    });
    assert(layout.scrollWidth <= layout.viewport + 1, 'Horizontal overflow: ' + JSON.stringify(layout));
    assert(layout.fonts.every(f => f.loaded), 'Local fonts did not load: ' + JSON.stringify(layout.fonts));
    assert(layout.imageLoaded, 'Hero image did not load');
    const menu = page.locator('.bk-header-menu summary');
    if (width < 1024) {
      await visible(menu, 'Mobile menu');
      // Tab navigation must actually reach the disclosure.
      let reached = false;
      for (let i = 0; i < 18; i++) {
        await page.keyboard.press('Tab');
        if (await menu.evaluate(el => el === document.activeElement)) { reached = true; break; }
      }
      assert(reached, 'Mobile menu not keyboard reachable');
      await page.keyboard.press('Enter');
      await visible(page.locator('.bk-header-mobile-nav'), 'Open mobile navigation');
      assert(await menu.evaluate(el => getComputedStyle(el).outlineStyle !== 'none'), 'Menu focus indicator missing');
      await page.keyboard.press('Enter');
      assert(!(await page.locator('.bk-header-menu').evaluate(el => el.open)), 'Disclosure did not close');
    } else {
      await visible(page.locator('.bk-header-desktop-nav'), 'Desktop navigation');
      assert(!(await menu.isVisible()), 'Mobile navigation visible on desktop');
    }
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0,0); });
    await page.screenshot({ path: output(mode + '-' + width + '.png'), fullPage: true, animations: 'disabled' });
    await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
    const axe = await page.evaluate(async tags => window.axe.run(document, {runOnly:{type:'tag',values:tags}}), tags);
    await writeFile(output('axe-' + mode + '-' + width + '.json'), JSON.stringify(axe, null, 2));
    const violations = axe.violations.map(v => ({id:v.id, impact:v.impact, nodes:v.nodes.map(n => n.target)}));
    results.push({ mode, width, layout, violations, errors, localFailures });
    assert.equal(errors.length, 0, 'JavaScript errors: ' + errors.join('; '));
    assert.equal(localFailures.length, 0, 'Local HTTP failures: ' + localFailures.join('; '));
    assert.equal(violations.length, 0, 'WCAG axe violations: ' + JSON.stringify(violations));
  } catch (error) {
    failures.push({width, error: String(error)});
    await page.screenshot({path: output('failure-' + mode + '-' + width + '.png'), fullPage: true}).catch(() => {});
  } finally {
    await context.close();
  }
}

async function checkShopping() {
  const context = await localContext(1440);
  const page = await context.newPage();
  try {
    await openHome(page);
    const shop = page.locator('.bk-hero__cta');
    const shopUrl = new URL(await shop.getAttribute('href'), base);
    assert.equal(shopUrl.origin, base.origin);
    const shopResponse = await page.goto(shopUrl.href, {waitUntil:'load'});
    assert(shopResponse?.ok(), 'Shop link failed');
    await openHome(page);
    const productLink = page.locator('.bk-product-title a').filter({hasText:'CI Featured Visible'});
    const productUrl = new URL(await productLink.getAttribute('href'), base);
    assert.equal(productUrl.origin, base.origin);
    const search = page.locator('.bk-header-search input[type=search]');
    // Multiple matches must remain a product search; catalog-only and hidden products must not leak.
    await search.fill('CI Featured');
    await Promise.all([
      page.waitForURL(url => url.searchParams.get('s') === 'CI Featured' && url.searchParams.get('post_type') === 'product'),
      search.press('Enter')
    ]);
    for (const name of ['CI Featured Visible','CI Featured Search Only']) {
      await visible(page.locator('main').getByRole('link',{name,exact:true}).first(), 'Expected search result: ' + name);
    }
    for (const name of ['CI Featured Catalog Only','CI Featured Hidden','CI Featured Draft']) {
      assert.equal(await page.locator('main').getByRole('link',{name,exact:true}).count(),0,'Non-searchable product leaked: '+name);
    }
    await openHome(page);
    // WooCommerce may redirect an exact single-result search to its canonical product page.
    const exact = page.locator('.bk-header-search input[type=search]');
    await exact.fill('CI Featured Visible');
    const [searchResponse] = await Promise.all([
      page.waitForResponse(response => {
        const url = new URL(response.url());
        return response.request().isNavigationRequest() && url.origin === base.origin
          && url.searchParams.get('s') === 'CI Featured Visible' && url.searchParams.get('post_type') === 'product';
      }),
      exact.press('Enter')
    ]);
    assert([200,301,302,303,307,308].includes(searchResponse.status()), 'Exact search HTTP failure');
    await page.waitForURL(url => url.href === productUrl.href || (url.origin === base.origin && url.searchParams.get('s') === 'CI Featured Visible' && url.searchParams.get('post_type') === 'product'));
    if (new URL(page.url()).href === productUrl.href) {
      await visible(page.locator('main').getByRole('heading',{name:'CI Featured Visible',exact:true}).first(), 'Expected single-result product');
    } else {
      await visible(page.locator('main').getByRole('link',{name:'CI Featured Visible',exact:true}).first(), 'Expected exact search result');
    }
    await openHome(page);
    const card = page.locator('.bk-product-card').filter({has:page.getByRole('heading',{name:'CI Featured Visible',exact:true})});
    const action = card.locator('form');
    const cartUrl = new URL(await action.getAttribute('action'), base);
    assert.equal(cartUrl.origin, base.origin);
    const button = card.getByRole('button',{name:'Añadir al carrito: CI Featured Visible',exact:true});
    await visible(button, 'Accessible purchase button');
    await Promise.all([
      page.waitForURL(url => url.origin === cartUrl.origin && url.pathname === cartUrl.pathname && (!cartUrl.search || url.searchParams.get('page_id') === cartUrl.searchParams.get('page_id'))),
      button.click()
    ]);
    await visible(page.getByText('CI Featured Visible',{exact:true}).first(), 'Fixture product missing from cart');
    // Native Store API confirms cart contents, independent of visible labels.
    const cart = await page.evaluate(async () => {
      const link = document.querySelector('link[rel="https://api.w.org/"]')?.href;
      const url = link ? new URL(link) : new URL('/wp-json/', location.origin);
      if (url.origin !== location.origin) throw new Error('Unexpected API origin');
      if (url.searchParams.has('rest_route')) url.searchParams.set('rest_route','/wc/store/v1/cart');
      else url.pathname = url.pathname.replace(/\/?$/, '/') + 'wc/store/v1/cart';
      const response = await fetch(url, {credentials:'same-origin'});
      if (!response.ok) throw new Error('Store API: ' + response.status);
      return response.json();
    });
    assert(cart.items.some(item => item.name === 'CI Featured Visible' && item.quantity === 1), 'Cart item/quantity mismatch');
    await page.screenshot({path:output('cart-fixture.png'),fullPage:true});
    results.push({shopping:'passed', cartQuantity:1});
  } catch (error) {
    failures.push({shopping:String(error)});
    await page.screenshot({path:output('failure-cart.png'),fullPage:true}).catch(() => {});
  } finally { await context.close(); }
}

try {
  for (const width of widths) await checkLayout(width);
  if (mode === 'populated') await checkShopping();
} finally {
  await browser.close();
  await writeFile(output('summary-' + mode + '.json'), JSON.stringify({mode, results, failures}, null, 2));
}
for (const result of results) console.log(JSON.stringify(result));
if (failures.length) {
  console.error(JSON.stringify(failures, null, 2));
  process.exitCode = 1;
}
