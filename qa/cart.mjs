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
const coupon = 'ci-bakata-cart-5000';
async function readCart(page) {
  return page.evaluate(async()=>{
    const link=document.querySelector('link[rel="https://api.w.org/"]')?.href;
    const url=link?new URL(link):new URL('/wp-json/',location.origin);
    if(url.origin!==location.origin) throw Error('Unexpected API origin');
    if(url.searchParams.has('rest_route')) url.searchParams.set('rest_route','/wc/store/v1/cart');
    else url.pathname=url.pathname.replace(/\/?$/,'/')+'wc/store/v1/cart';
    const response=await fetch(url,{credentials:'same-origin',cache:'no-store'});
    if(!response.ok)throw Error('Store API: '+response.status);
    return response.json();
  });
}
async function waitCart(page,predicate,message) {
  const until=Date.now()+15000;
  let cart;
  do {
    cart=await readCart(page);
    if(predicate(cart))return cart;
    await new Promise(resolve=>setTimeout(resolve,200));
  } while(Date.now()<until);
  throw Error(message+'; last cart: '+JSON.stringify({items:cart?.items?.map(i=>({id:i.id,quantity:i.quantity})),coupons:cart?.coupons?.map(c=>c.code),totals:cart?.totals}));
}
async function audit(page,label) {
  await page.evaluate(()=>document.fonts.ready);
  assert.equal(await page.getByRole('main').count(),1,'One main landmark');
  assert.equal(await page.locator('main h1').count(),1,'One H1');
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
  assert(overflow<=1,'Horizontal overflow: '+overflow);
  await page.screenshot({path:out(label+'.png'),fullPage:true});
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
  const axe=await page.evaluate(tags=>window.axe.run(document,{runOnly:{type:'tag',values:tags}}),tags);
  await writeFile(out('axe-'+label+'.json'),JSON.stringify(axe,null,2));
  assert.equal(axe.violations.length,0,JSON.stringify(axe.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))));
}
async function run(width) {
  const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
  await context.route('**/*',route=>new URL(route.request().url()).origin===base.origin?route.continue():route.abort());
  const page=await context.newPage();
  let phase='empty';
  try {
    await page.goto(base.href,{waitUntil:'load'});
    const card=page.locator('.bk-product-card').filter({has:page.getByRole('heading',{name:'CI Featured Visible',exact:true})});
    const cartUrl=new URL(await card.locator('form').getAttribute('action'),base);
    assert.equal(cartUrl.origin,base.origin);
    await page.goto(cartUrl.href,{waitUntil:'load'});
    await page.locator('main.bk-cart').waitFor({state:'visible'});
    await page.locator('.wc-block-cart__empty-cart__title').waitFor({state:'visible'});
    assert.equal((await readCart(page)).items.length,0);
    await audit(page,'cart-empty-'+width);
    phase='add';
    const back=page.getByRole('link',{name:'Seguir explorando productos',exact:true});
    const shopUrl=new URL(await back.getAttribute('href'),base);
    assert.equal(shopUrl.origin,base.origin);
    await Promise.all([page.waitForURL(u=>u.href===shopUrl.href,{waitUntil:'load'}),back.click()]);
    assert(await page.locator('main.bk-shop').isVisible());
    await page.goto(base.href,{waitUntil:'load'});
    await Promise.all([page.waitForURL(u=>u.href===cartUrl.href,{waitUntil:'load'}),card.getByRole('button',{name:'Añadir al carrito: CI Featured Visible',exact:true}).click()]);
    const row=page.locator('.wc-block-cart-items__row').filter({has:page.getByText('CI Featured Visible',{exact:true})});
    await row.waitFor({state:'visible'});
    const initial=await waitCart(page,c=>c.items.length===1&&c.items[0].quantity===1,'Initial item');
    const id=initial.items[0].id;
    const minor=initial.totals.currency_minor_unit;
    assert.equal(initial.totals.currency_code,'COP');
    const unit=Number(initial.items[0].prices.price);
    assert(unit>0);
    phase='quantity';
    const qty=row.locator('.wc-block-components-quantity-selector__input');
    const plus=row.locator('.wc-block-components-quantity-selector__button--plus');
    await plus.click();
    const updated=await waitCart(page,c=>c.items.some(i=>i.id===id&&i.quantity===2),'Quantity increased to two');
    assert.equal(Number(updated.items.find(i=>i.id===id).totals.line_subtotal),unit*2);
    assert.equal(await qty.inputValue(),'2');
    const minus=row.locator('.wc-block-components-quantity-selector__button--minus');
    await minus.click();
    await waitCart(page,c=>c.items.some(i=>i.id===id&&i.quantity===1),'Quantity reduced to one');
    assert.equal(await qty.inputValue(),'1');
    await plus.click();
    await waitCart(page,c=>c.items.some(i=>i.id===id&&i.quantity===2),'Quantity increased again');
    phase='coupon';
    const couponPanel=page.locator('.wc-block-components-totals-coupon');
    await couponPanel.waitFor({state:'visible'});
    const input=couponPanel.locator('input');
    if(!await input.isVisible())await couponPanel.locator('button.wc-block-components-panel__button').click();
    await input.waitFor({state:'visible'});
    await input.fill(coupon);
    await couponPanel.locator('.wc-block-components-totals-coupon__button').click();
    const discounted=await waitCart(page,c=>c.coupons.some(x=>x.code===coupon),'Coupon applied');
    assert.equal(Number(discounted.totals.total_discount),5000*10**minor);
    assert.equal(Number(discounted.totals.total_items),unit*2);
    assert.equal(Number(discounted.totals.total_price),
      Number(updated.totals.total_price)-5000*10**minor,'Server total after fixed discount');
    phase='reload';
    await page.reload({waitUntil:'load'});
    await row.waitFor({state:'visible'});
    const persisted=await waitCart(page,c=>c.items.some(i=>i.id===id&&i.quantity===2)&&c.coupons.some(x=>x.code===coupon),'Cart survives reload');
    assert.equal(persisted.totals.total_price,discounted.totals.total_price);
    const checkout=page.locator('.wc-block-cart__submit-button');
    await checkout.waitFor({state:'visible'});
    const checkoutUrl=new URL(await checkout.getAttribute('href'),base);
    assert.equal(checkoutUrl.origin,base.origin);
    assert.notEqual(checkoutUrl.href,cartUrl.href);
    assert(['http:','https:'].includes(checkoutUrl.protocol));
    phase='audit-filled';
    await audit(page,'cart-filled-'+width);
    phase='remove';
    await row.locator('.wc-block-cart-item__remove-link').click();
    await waitCart(page,c=>c.items.length===0,'Item removed');
    await page.locator('.wc-block-cart__empty-cart__title').waitFor({state:'visible'});
    assert.equal(await page.locator('.wc-block-cart-items__row').count(),0);
    results.push({width,passed:true,quantity:2,currency:'COP',couponDiscount:5000,checkoutLink:checkoutUrl.pathname});
  } catch(error) {
    failures.push({width,phase,error:String(error),url:page.url(),mainText:(await page.locator('main').first().innerText({timeout:2000}).catch(()=>'' )).slice(0,1600)});
    await page.screenshot({path:out('failure-cart-'+width+'.png'),fullPage:true}).catch(()=>{});
  } finally {await context.close();}
}
try {for(const width of [320,768,1440])await run(width);}
finally {await browser.close();await writeFile(out('summary-cart.json'),JSON.stringify({results,failures},null,2));}
console.log(JSON.stringify({results,failures}));
if(failures.length)process.exitCode=1;
