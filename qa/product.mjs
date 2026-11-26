import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { chromium } from 'playwright';
const require = createRequire(import.meta.url);
assert.equal(process.env.BAKATA_CI_FIXTURES,'1');
const base = new URL('http://localhost:8080/');
const reports = new URL('./reports/',import.meta.url);
await mkdir(reports,{recursive:true});
const out = name => new URL(name,reports).pathname;
const browser = await chromium.launch();
const results = [], failures = [];
const tags = ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'];
async function contextFor(width) {
  const context = await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
  await context.route('**/*',route => new URL(route.request().url()).origin === base.origin ? route.continue() : route.abort());
  return context;
}
async function open(page, slug, name) {
  const response=await page.goto(new URL('product/'+slug+'/',base).href,{waitUntil:'load'});
  assert(response?.ok(),'Product request failed');
  await page.locator('.bk-product-detail .product_title').waitFor({state:'visible'});
  assert.equal(await page.locator('.product_title').innerText(),name);
  assert.equal(await page.getByRole('main').count(),1,'One main landmark');
  assert.equal(await page.locator('main h1').count(),1,'One product H1');
  await page.evaluate(()=>document.fonts.ready);
}
async function layout(width, slug, name) {
  const context=await contextFor(width);
  const page=await context.newPage();
  try {
    await open(page,slug,name);
    const gallery=page.locator('.bk-product-detail .woocommerce-product-gallery');
    await gallery.waitFor({state:'visible'});
    await page.waitForFunction(()=>Array.from(document.querySelectorAll('.woocommerce-product-gallery__image img')).some(img=>img.complete&&img.naturalWidth>0));
    assert.equal(await page.locator('.summary form.cart').count(),1);
    await page.locator('.summary .single_add_to_cart_button').waitFor({state:'visible'});
    assert.equal(await page.locator('.bk-product-service a').count(),1,'Only published CI shipping policy');
    assert.equal(await page.locator('.bk-product-service a').first().innerText(),'Información de envíos');
    assert(await page.locator('.woocommerce-tabs').isVisible(),'Native details tabs');
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
    assert(overflow<=1,'Horizontal overflow: '+overflow);
    await page.screenshot({path:out('product-'+slug+'-'+width+'.png'),fullPage:true});
    await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
    const axe=await page.evaluate(tags=>window.axe.run(document,{runOnly:{type:'tag',values:tags}}),tags);
    await writeFile(out('axe-product-'+slug+'-'+width+'.json'),JSON.stringify(axe,null,2));
    assert.equal(axe.violations.length,0,JSON.stringify(axe.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))));
    results.push({width,slug,layout:'passed'});
  } catch(error) {
    failures.push({width,slug,error:String(error),url:page.url()});
    await page.screenshot({path:out('failure-product-'+slug+'-'+width+'.png'),fullPage:true}).catch(()=>{});
  } finally { await context.close(); }
}
async function readCart(page) {
  return page.evaluate(async()=>{
    const link=document.querySelector('link[rel="https://api.w.org/"]')?.href;
    const url=link?new URL(link):new URL('/wp-json/',location.origin);
    if(url.origin!==location.origin) throw Error('Unexpected API origin');
    if(url.searchParams.has('rest_route')) url.searchParams.set('rest_route','/wc/store/v1/cart');
    else url.pathname=url.pathname.replace(/\/?$/,'/')+'wc/store/v1/cart';
    const response=await fetch(url,{credentials:'same-origin'});
    if(!response.ok) throw Error('Store API: '+response.status);
    return response.json();
  });
}
async function buy(slug,name,variable=false) {
  const context=await contextFor(375);
  const page=await context.newPage();
  try {
    await open(page,slug,name);
    const form=page.locator('.summary form.cart');
    const button=form.locator('.single_add_to_cart_button');
    let expectedId;
    if(variable) {
      const select=form.locator('select[name=attribute_color]');
      await select.waitFor({state:'visible'});
      assert(await button.evaluate(el=>el.classList.contains('disabled')||el.disabled),'Variation initially not selected');
      await select.selectOption({label:'Verde'});
      await page.waitForFunction(()=>Number(document.querySelector('input[name=variation_id]')?.value)>0&&!document.querySelector('.single_add_to_cart_button')?.classList.contains('disabled'));
      expectedId=Number(await form.locator('input[name=variation_id]').inputValue());
    } else {
      expectedId=Number(await form.locator('[name=add-to-cart]').getAttribute('value'));
      assert(await page.locator('.summary .price del').isVisible(),'Regular price shown with sale');
      assert(await page.locator('.summary .price ins').isVisible(),'Sale price shown');
    }
    assert(expectedId>0);
    await form.locator('input.qty').fill('2');
    const [response]=await Promise.all([
      page.waitForResponse(r=>r.request().method()==='POST'&&r.request().isNavigationRequest()&&new URL(r.url()).origin===base.origin),
      button.click()
    ]);
    assert(response.status()<400,'Native add-to-cart POST failed');
    await page.waitForLoadState('load');
    const cart=await readCart(page);
    const item=cart.items.find(i=>i.id===expectedId);
    assert(item,'Expected product/variation missing from cart');
    assert.equal(item.quantity,2,'Cart quantity');
    if(variable) assert(item.variation.some(v=>String(v.value).toLowerCase()==='verde'),'Selected variation missing');
    results.push({slug,purchase:'passed',quantity:item.quantity,variation:variable});
  } catch(error) {
    failures.push({slug,purchase:String(error),url:page.url()});
    await page.screenshot({path:out('failure-buy-'+slug+'.png'),fullPage:true}).catch(()=>{});
  } finally { await context.close(); }
}
async function soldOut() {
  const context=await contextFor(375);
  const page=await context.newPage();
  try {
    await open(page,'ci-pdp-sold-out','CI PDP Sold Out');
    await page.locator('.summary .stock.out-of-stock').waitFor({state:'visible'});
    assert.equal(await page.locator('.summary .single_add_to_cart_button').count(),0,'Sold-out product cannot be bought');
    results.push({soldOut:'passed'});
  } catch(error) { failures.push({soldOut:String(error),url:page.url()}); }
  finally { await context.close(); }
}
try {
  for(const width of [320,768,1440]) {
    await layout(width,'ci-pdp-simple','CI PDP Simple');
    await layout(width,'ci-pdp-variable','CI PDP Variable');
  }
  await buy('ci-pdp-simple','CI PDP Simple');
  await buy('ci-pdp-variable','CI PDP Variable',true);
  await soldOut();
} finally {
  await browser.close();
  await writeFile(out('summary-product.json'),JSON.stringify({results,failures},null,2));
}
console.log(JSON.stringify({results,failures}));
if(failures.length)process.exitCode=1;
