import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright';

assert.equal(process.env.BAKATA_CI_FIXTURES, '1', 'Disposable CI only');
const base = new URL('http://localhost:8080/');
const reports = new URL('./reports/', import.meta.url);
await mkdir(reports, {recursive:true});
const browser = await chromium.launch();
const context = await browser.newContext({viewport:{width:375,height:900}});
const external = [];
await context.route('**/*', route => {
  const url = new URL(route.request().url());
  if (url.origin === base.origin) return route.continue();
  external.push(url.origin);
  return route.abort();
});
const page = await context.newPage();
const report = {budgets:{heroBytes:131072,themeCssBytes:98304}, pages:[]};
async function open(url) {
  const target = new URL(url,base);
  assert.equal(target.origin,base.origin);
  const response = await page.goto(target.href,{waitUntil:'load'});
  assert(response?.ok(),'Expected successful local document');
}
async function robots(label) {
  const tokens = await page.locator('meta[name="robots"]').evaluateAll(nodes =>
    nodes.flatMap(node => (node.content || '').toLowerCase().split(/[,\s]+/).filter(Boolean)));
  assert(tokens.includes('noindex'), label+' must emit noindex');
  assert(!tokens.includes('index'), label+' contains conflicting index directive');
  report.pages.push({label,noindex:true});
}
async function bytes(url) {
  const target = new URL(url,base);
  assert.equal(target.origin,base.origin,'Theme assets must be local');
  const response = await context.request.get(target.href);
  assert(response.ok(),'Theme resource unavailable: '+target.pathname);
  return (await response.body()).length;
}
try {
  await open(base.href);
  const hero = page.locator('.bk-hero__media img');
  assert.equal(await hero.getAttribute('fetchpriority'),'high');
  assert.equal(await hero.getAttribute('loading'),'eager');
  for (const attr of ['width','height']) assert(Number(await hero.getAttribute(attr))>0,'Hero intrinsic dimensions');
  const preload = page.locator('link[rel="preload"][as="font"][href$="/assets/fonts/inter.woff2"]');
  assert.equal(await preload.count(),1,'One local body font preload');
  assert.equal(await preload.getAttribute('crossorigin'),'anonymous');
  const heroBytes = await bytes(await hero.getAttribute('src'));
  const css = await page.locator('link[rel="stylesheet"]').evaluateAll(nodes =>
    [...new Set(nodes.map(node=>node.href).filter(href=>href.includes('/themes/bakata/assets/') && new URL(href).pathname.endsWith('.css')))]);
  assert(css.length>0,'Theme CSS loaded');
  let themeCssBytes = 0;
  for (const url of css) themeCssBytes += await bytes(url);
  report.measured={heroBytes,themeCssBytes,themeStylesheets:css.length};
  assert(heroBytes<=report.budgets.heroBytes,'Hero byte budget exceeded');
  assert(themeCssBytes<=report.budgets.themeCssBytes,'Theme stylesheet byte budget exceeded');
  const cartUrl = await page.locator('.bk-header-actions a[aria-label="Carrito"]').getAttribute('href');
  const accountUrl = await page.locator('.bk-header-account').getAttribute('href');
  await open(accountUrl);
  await robots('account');
  await open(cartUrl);
  await robots('cart');
  await open(base.href);
  const product = page.locator('.bk-product-card').filter({has:page.getByRole('heading',{name:'CI Featured Visible',exact:true})});
  await Promise.all([page.waitForURL(url=>url.href===new URL(cartUrl,base).href),product.getByRole('button',{name:'Añadir al carrito: CI Featured Visible',exact:true}).click()]);
  const checkout = page.locator('.wc-block-cart__submit-button');
  await checkout.waitFor({state:'visible'});
  await open(await checkout.getAttribute('href'));
  await robots('checkout');
  const search = new URL(base);
  search.searchParams.set('s','bakata-seo-no-match-9482');
  search.searchParams.set('post_type','product');
  await open(search.href);
  await robots('search');
  assert.equal(external.length,0,'Unexpected external resource: '+external.join(', '));
} finally {
  report.externalOrigins=[...new Set(external)];
  await writeFile(new URL('performance-seo.json',reports),JSON.stringify(report,null,2));
  await browser.close();
}
console.log(JSON.stringify(report));
