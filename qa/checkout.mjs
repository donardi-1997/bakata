import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { chromium } from 'playwright';
const require=createRequire(import.meta.url);
assert.equal(process.env.BAKATA_CI_FIXTURES,'1');
const base=new URL('http://localhost:8080/');
const reports=new URL('./reports/',import.meta.url);
await mkdir(reports,{recursive:true});
const out=name=>new URL(name,reports).pathname;
const browser=await chromium.launch();
const results=[],failures=[];
const tags=['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'];
async function cart(page) {
  return page.evaluate(async()=>{
    const link=document.querySelector('link[rel="https://api.w.org/"]')?.href;
    const url=link?new URL(link):new URL('/wp-json/',location.origin);
    if(url.origin!==location.origin)throw Error('Unexpected API origin');
    if(url.searchParams.has('rest_route'))url.searchParams.set('rest_route','/wc/store/v1/cart');
    else url.pathname=url.pathname.replace(/\/?$/,'/')+'wc/store/v1/cart';
    const res=await fetch(url,{credentials:'same-origin',cache:'no-store'});
    if(!res.ok)throw Error('Cart API '+res.status);
    return res.json();
  });
}
async function waitCart(page, predicate) {
  const deadline=Date.now()+20000;
  do {const c=await cart(page);if(predicate(c))return c;await new Promise(r=>setTimeout(r,250));}
  while(Date.now()<deadline);
  throw Error('Expected Colombian address and shipping total not reached');
}
async function run(width) {
  const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
  let blockedSubmissions=0;
  await context.route('**/*',route=>{
    const req=route.request(),url=new URL(req.url());
    if(url.origin!==base.origin)return route.abort();
    // No order submission or payment processing in this suite.
    const path=url.searchParams.get('rest_route')||url.pathname;
    if(req.method()==='POST'&&(/\/wc\/store\/v\d+\/checkout(?:\/|$)/.test(path)||path==='/checkout/'||url.searchParams.get('wc-ajax')==='checkout')){
      blockedSubmissions++;return route.abort();
    }
    return route.continue();
  });
  const page=await context.newPage();
  let phase='cart';
  try {
    await page.goto(base.href,{waitUntil:'load'});
    const card=page.locator('.bk-product-card').filter({has:page.getByRole('heading',{name:'CI Featured Visible',exact:true})});
    const cartUrl=new URL(await card.locator('form').getAttribute('action'),base);
    assert.equal(cartUrl.origin,base.origin);
    await Promise.all([page.waitForURL(u=>u.href===cartUrl.href,{waitUntil:'load'}),card.getByRole('button',{name:'Añadir al carrito: CI Featured Visible',exact:true}).click()]);
    const link=page.locator('.wc-block-cart__submit-button');
    await link.waitFor({state:'visible'});
    const checkoutUrl=new URL(await link.getAttribute('href'),base);
    assert.equal(checkoutUrl.origin,base.origin);
    phase='checkout';
    await Promise.all([page.waitForURL(u=>u.href===checkoutUrl.href,{waitUntil:'load'}),link.click()]);
    await page.locator('main.bk-checkout .wc-block-checkout__form').waitFor({state:'visible'});
    assert.equal(await page.getByRole('main').count(),1);
    assert.equal(await page.locator('main h1').count(),1);
    const steps=page.locator('main .bk-purchase-steps');
    assert.equal(await steps.count(),1,'Purchase progress rendered once');
    assert.equal(await steps.locator('li').count(),3,'Three purchase stages');
    assert.equal(await steps.locator('[aria-current=step]').count(),1,'Exactly one current stage');
    assert.equal(await steps.locator('[aria-current=step]').innerText(),'Datos y pago');

    const back=page.getByRole('link',{name:'Volver al carrito',exact:true});
    assert.equal(new URL(await back.getAttribute('href'),base).href,cartUrl.href);
    phase='address';
    const form=page.locator('main.bk-checkout');
    const email=form.locator('#email');
    await email.waitFor({state:'visible'});
    await email.fill('checkout-test@example.invalid');
    const fields={first_name:'CI',last_name:'Fixture',address_1:'Calle de prueba 123',city:'Bogotá'};
    for(const [key,value] of Object.entries(fields)) {
      const field=form.locator('#shipping-'+key);
      await field.waitFor({state:'visible'});
      await field.fill(value);
    }
    const country=form.locator('#shipping-country');
    if(await country.count()&&await country.isVisible()&&await country.evaluate(el=>el.tagName==='SELECT')){
      await country.selectOption('CO');
    }
    const state=form.locator('#shipping-state');
    await state.waitFor({state:'visible'});
    if(await state.evaluate(el=>el.tagName==='SELECT')){
      const states=await state.locator('option').evaluateAll(options=>options.map(o=>o.value));
      assert(states.includes('CO-DC')&&states.includes('CO-ANT'),'Native Colombian departments');
      await state.selectOption('CO-DC');
    } else {
      await state.fill('Capital District');
      await state.press('ArrowDown');
      await state.press('Enter');
    }
    const postcode=form.locator('#shipping-postcode');
    if(await postcode.count()&&await postcode.isVisible()) {
      assert.notEqual(await postcode.getAttribute('required'),'','Colombian postcode optional');
      await postcode.fill('');
    }
    const phone=form.locator('#shipping-phone');
    if(await phone.count()&&await phone.isVisible())await phone.fill('3000000000');
    await email.focus();
    phase='shipping';
    const c=await waitCart(page,c=>c.shipping_address?.country==='CO'&&c.shipping_address?.state==='CO-DC'&&c.shipping_address?.city==='Bogotá'&&Number(c.totals.total_shipping)===12000*10**c.totals.currency_minor_unit);
    assert.equal(c.totals.currency_code,'COP');
    assert.equal(c.items.length,1);
    assert.equal(c.items[0].quantity,1);
    assert.equal(Number(c.totals.total_price),Number(c.totals.total_items)+Number(c.totals.total_shipping));
    await form.getByText('CI QA Delivery',{exact:true}).first().waitFor({state:'visible'});
    await form.getByText('CI QA Offline payment',{exact:true}).first().waitFor({state:'visible'});
    const place=form.locator('.wc-block-components-checkout-place-order-button');
    await place.waitFor({state:'visible'});
    phase='audit';
    await page.evaluate(()=>document.fonts.ready);
    const geometry=await page.evaluate(()=>{
      const width=document.documentElement.clientWidth;
      const scrollWidth=document.documentElement.scrollWidth;
      const offenders=Array.from(document.querySelectorAll('main.bk-checkout *')).filter(el=>{const r=el.getBoundingClientRect();return r.width>1&&r.height>1&&r.right>width+1&&r.left>=0;}).map(el=>({tag:el.tagName,className:el.getAttribute('class'),right:Math.round(el.getBoundingClientRect().right)})).slice(0,20);
      return {width,scrollWidth,overflow:scrollWidth-width,offenders};
    });
    await writeFile(out('layout-checkout-'+width+'.json'),JSON.stringify(geometry,null,2));
    assert(geometry.overflow<=1,'Horizontal overflow: '+JSON.stringify(geometry));
    await page.screenshot({path:out('checkout-'+width+'.png'),fullPage:true});
    await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
    const axe=await page.evaluate(tags=>window.axe.run(document,{runOnly:{type:'tag',values:tags}}),tags);
    await writeFile(out('axe-checkout-'+width+'.json'),JSON.stringify(axe,null,2));
    assert.equal(axe.violations.length,0,JSON.stringify(axe.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))));
    assert.equal(blockedSubmissions,0,'No order submission attempted');
    phase='return';
    await Promise.all([page.waitForURL(u=>u.href===cartUrl.href,{waitUntil:'load'}),back.click()]);
    await page.locator('.wc-block-cart-items__row').first().waitFor({state:'visible'});
    assert.equal((await cart(page)).items[0].quantity,1);
    results.push({width,passed:true,currency:'COP',department:'CO-DC',shippingFixture:12000,orderSubmitted:false});
  } catch(error) {
    failures.push({width,phase,error:String(error),url:page.url(),fields:await page.locator('main input,main select').evaluateAll(els=>els.map(e=>({tag:e.tagName,id:e.id,name:e.name,role:e.getAttribute('role'),required:e.required}))).catch(()=>[])});
    await page.screenshot({path:out('failure-checkout-'+width+'.png'),fullPage:true}).catch(()=>{});
  } finally {await context.close();}
}
try {for(const width of [320,768,1440])await run(width);}
finally {await browser.close();await writeFile(out('summary-checkout.json'),JSON.stringify({results,failures},null,2));}
console.log(JSON.stringify({results,failures}));
if(failures.length)process.exitCode=1;
