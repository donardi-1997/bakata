import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { chromium } from 'playwright';
const require = createRequire(import.meta.url);
assert.equal(process.env.BAKATA_CI_FIXTURES,'1');
const base = new URL('http://localhost:8080/');
const reportDir = new URL('./reports/',import.meta.url);
await mkdir(reportDir,{recursive:true});
const browser = await chromium.launch();
const results = [];
const failures = [];
const output = name => new URL(name,reportDir).pathname;
const cardSelector = '.bk-shop ul.products li.product';
async function waitForCards(page, expected, message) {
  await page.waitForFunction(({selector, count}) =>
    document.querySelectorAll(selector).length === count,
    {selector:cardSelector,count:expected},{timeout:10000});
  assert.equal(await page.locator(cardSelector).count(),expected,message);
}
async function followLink(page, link) {
  const target = new URL(await link.getAttribute('href'),page.url());
  assert.equal(target.origin,base.origin);
  await Promise.all([
    page.waitForURL(url=>url.href===target.href,{waitUntil:'load',timeout:15000}),
    link.click()
  ]);
  await page.locator('.bk-shop-filters').waitFor({state:'visible'});
}
async function run(width) {
  const context = await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
  await context.route('**/*',route => new URL(route.request().url()).origin === base.origin ? route.continue() : route.abort());
  const page = await context.newPage();
  try {
    await page.goto(base.href);
    const shopUrl = new URL(await page.locator('.bk-hero__cta').getAttribute('href'),base);
    assert.equal(shopUrl.origin,base.origin);
    await page.goto(shopUrl.href);
    await page.locator('.bk-shop-filters').waitFor({state:'visible'});
    const cards = page.locator(cardSelector);
    await waitForCards(page,12,'Native first page size');
    assert.equal(await page.locator('.bk-shop main').count(),0,'No nested main');
    assert.equal(await page.getByRole('main').count(),1,'Exactly one main landmark');
    assert.equal(await page.locator('main.bk-shop .bk-shop-filters').count(),1,'Filters inside main');
    assert.equal(await page.locator('main h1').count(),1,'Catalog H1');
    const category = page.locator('.bk-shop-categories').getByRole('link',{name:'CI QA Shop Beta',exact:true});
    await followLink(page,category);
    await page.locator('.bk-shop-categories a[aria-current=page]').filter({hasText:'CI QA Shop Beta'}).waitFor();
    await waitForCards(page,12,'First category page');
    assert(await page.locator('.woocommerce-pagination').isVisible(),'Pagination required');
    const page2 = page.locator('.woocommerce-pagination a.page-numbers').filter({hasText:/^2$/});
    await followLink(page,page2);
    await page.locator('.woocommerce-pagination .current').filter({hasText:/^2$/}).waitFor();
    await waitForCards(page,1,'Remaining category products');
    await followLink(page,page.locator('.bk-shop-categories').getByRole('link',{name:'CI QA Shop Beta',exact:true}));
    await waitForCards(page,12,'Return to first category page');
    await page.locator('.bk-shop-price-form input[name=min_price]').fill('20000');
    await page.locator('.bk-shop-price-form input[name=max_price]').fill('40000');
    await Promise.all([page.waitForURL(u=>u.searchParams.get('min_price')==='20000'&&u.searchParams.get('max_price')==='40000'),page.getByRole('button',{name:'Filtrar por precio',exact:true}).click()]);
    await waitForCards(page,3,'Filtered category count');
    const titles = () => cards.locator('.woocommerce-loop-product__title').allTextContents();
    assert.deepEqual((await titles()).map(s=>s.trim()).sort(),['CI QA Shop 02','CI QA Shop 03','CI QA Shop 04']);
    const order = new URL(page.url());
    order.searchParams.set('orderby','price-desc');
    await page.goto(order.href,{waitUntil:'load'});
    await waitForCards(page,3,'Sorted category count');
    assert.deepEqual((await titles()).map(s=>s.trim()),['CI QA Shop 04','CI QA Shop 03','CI QA Shop 02']);
    await page.screenshot({path:output('shop-filtered-'+width+'.png'),fullPage:true});
    await followLink(page,page.getByRole('link',{name:'Limpiar filtros',exact:true}));
    await waitForCards(page,12,'Reset returns to category');
    assert.equal(await page.locator('.bk-shop-price-form input[name=min_price]').inputValue(),'','Minimum price cleared');
    assert.equal(await page.locator('.bk-shop-price-form input[name=max_price]').inputValue(),'','Maximum price cleared');
    const resetUrl = new URL(page.url());
    for (const param of ['min_price','max_price','orderby','paged']) {
      assert(!resetUrl.searchParams.has(param),'Reset must remove '+param);
    }
    await page.locator('.bk-shop-categories a[aria-current=page]').filter({hasText:'CI QA Shop Beta'}).waitFor();
    const overflow = await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
    assert(overflow<=1,'Horizontal overflow: '+overflow);
    await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
    const axe=await page.evaluate(()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}}));
    await writeFile(output('axe-shop-'+width+'.json'),JSON.stringify(axe,null,2));
    assert.equal(axe.violations.length,0,JSON.stringify(axe.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))));
    await page.screenshot({path:output('shop-'+width+'.png'),fullPage:true});
    results.push({width,passed:true});
  } catch(error) {
    failures.push({width,error:String(error),url:page.url(),mainText:(await page.locator('main').first().innerText({timeout:2000}).catch(()=>'' )).slice(0,1800)});
    await page.screenshot({path:output('failure-shop-'+width+'.png'),fullPage:true}).catch(()=>{});
  } finally { await context.close(); }
}
try { for(const width of [320,768,1440]) await run(width); }
finally { await browser.close(); await writeFile(output('summary-shop.json'),JSON.stringify({results,failures},null,2)); }
console.log(JSON.stringify({results,failures}));
if(failures.length) process.exitCode=1;
