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
    const cards = page.locator('.bk-shop ul.products li.product');
    assert.equal(await cards.count(),12,'Native first page size');
    assert.equal(await page.locator('.bk-shop main').count(),0,'No nested main');
    assert.equal(await page.locator('main h1').count(),1,'Catalog H1');
    const category = page.locator('.bk-shop-categories').getByRole('link',{name:'CI QA Shop Beta',exact:true});
    await category.click();
    await page.locator('.bk-shop-categories a[aria-current=page]').filter({hasText:'CI QA Shop Beta'}).waitFor();
    assert.equal(await cards.count(),12);
    assert(await page.locator('.woocommerce-pagination').isVisible(),'Pagination required');
    const page2 = page.locator('.woocommerce-pagination a.page-numbers').filter({hasText:/^2$/});
    await page2.click();
    await page.locator('.woocommerce-pagination .current').filter({hasText:/^2$/}).waitFor();
    assert.equal(await cards.count(),1,'Remaining category products');
    await page.locator('.bk-shop-categories').getByRole('link',{name:'CI QA Shop Beta',exact:true}).click();
    await page.locator('.bk-shop-price-form input[name=min_price]').fill('20000');
    await page.locator('.bk-shop-price-form input[name=max_price]').fill('40000');
    await Promise.all([page.waitForURL(u=>u.searchParams.get('min_price')==='20000'&&u.searchParams.get('max_price')==='40000'),page.getByRole('button',{name:'Filtrar por precio',exact:true}).click()]);
    assert.equal(await cards.count(),3,'Filtered category count');
    const titles = () => cards.locator('.woocommerce-loop-product__title').allTextContents();
    assert.deepEqual((await titles()).map(s=>s.trim()).sort(),['CI QA Shop 02','CI QA Shop 03','CI QA Shop 04']);
    const order = new URL(page.url());
    order.searchParams.set('orderby','price-desc');
    await page.goto(order.href);
    assert.deepEqual((await titles()).map(s=>s.trim()),['CI QA Shop 04','CI QA Shop 03','CI QA Shop 02']);
    await page.screenshot({path:output('shop-filtered-'+width+'.png'),fullPage:true});
    await page.getByRole('link',{name:'Limpiar filtros',exact:true}).click();
    assert.equal(await cards.count(),12,'Reset returns to category');
    const overflow = await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
    assert(overflow<=1,'Horizontal overflow: '+overflow);
    await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
    const axe=await page.evaluate(()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}}));
    await writeFile(output('axe-shop-'+width+'.json'),JSON.stringify(axe,null,2));
    assert.equal(axe.violations.length,0,JSON.stringify(axe.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))));
    await page.screenshot({path:output('shop-'+width+'.png'),fullPage:true});
    results.push({width,passed:true});
  } catch(error) {
    failures.push({width,error:String(error)});
    await page.screenshot({path:output('failure-shop-'+width+'.png'),fullPage:true}).catch(()=>{});
  } finally { await context.close(); }
}
try { for(const width of [320,768,1440]) await run(width); }
finally { await browser.close(); await writeFile(output('summary-shop.json'),JSON.stringify({results,failures},null,2)); }
console.log(JSON.stringify({results,failures}));
if(failures.length) process.exitCode=1;
