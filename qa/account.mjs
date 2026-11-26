import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { chromium } from 'playwright';
const require=createRequire(import.meta.url);
assert.equal(process.env.BAKATA_CI_FIXTURES,'1');
const password=process.env.BAKATA_CI_ACCOUNT_PASSWORD;
assert(password?.length>=24,'Ephemeral account credential required');
const own=Number(process.env.BAKATA_CI_OWN_ORDER);
const other=Number(process.env.BAKATA_CI_OTHER_ORDER);
assert(Number.isInteger(own)&&own>0&&Number.isInteger(other)&&other>0&&own!==other);
const base=new URL('http://localhost:8080/');
const reports=new URL('./reports/',import.meta.url);
await mkdir(reports,{recursive:true});
const out=name=>new URL(name,reports).pathname;
const browser=await chromium.launch();
const results=[],failures=[];
const tags=['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'];
async function follow(page,link) {
  const url=new URL(await link.getAttribute('href'),page.url());
  assert.equal(url.origin,base.origin);
  await Promise.all([page.waitForURL(u=>u.href===url.href,{waitUntil:'load'}),link.click()]);
  await page.locator('main.bk-account').waitFor({state:'visible'});
  return url;
}
async function submit(page,button) {
  const [response]=await Promise.all([page.waitForNavigation({waitUntil:'load'}),button.click()]);
  assert(response?.ok(),'Native form navigation failed');
  await page.locator('main.bk-account').waitFor({state:'visible'});
}
async function audit(page,label) {
  await page.evaluate(()=>document.fonts.ready);
  assert.equal(await page.getByRole('main').count(),1,'One main landmark');
  assert.equal(await page.locator('main h1').count(),1,'One H1');
  const geometry=await page.evaluate(()=>{
    const width=document.documentElement.clientWidth, scrollWidth=document.documentElement.scrollWidth;
    const offenders=Array.from(document.querySelectorAll('main.bk-account *')).filter(el=>{const r=el.getBoundingClientRect();return r.width>1&&r.height>1&&r.left>=0&&r.right>width+1;}).map(el=>({tag:el.tagName,className:el.getAttribute('class'),right:Math.round(el.getBoundingClientRect().right)})).slice(0,20);
    return {width,scrollWidth,overflow:scrollWidth-width,offenders};
  });
  await writeFile(out('layout-account-'+label+'.json'),JSON.stringify(geometry,null,2));
  assert(geometry.overflow<=1,'Horizontal overflow: '+JSON.stringify(geometry));
  await page.screenshot({path:out('account-'+label+'.png'),fullPage:true});
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
  const axe=await page.evaluate(tags=>window.axe.run(document,{runOnly:{type:'tag',values:tags}}),tags);
  await writeFile(out('axe-account-'+label+'.json'),JSON.stringify(axe,null,2));
  assert.equal(axe.violations.length,0,JSON.stringify(axe.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))));
}
async function run(width) {
  const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
  await context.route('**/*',route=>new URL(route.request().url()).origin===base.origin?route.continue():route.abort());
  const page=await context.newPage();
  page.setDefaultTimeout(12000);
  let phase='guest';
  try {
    await page.goto(base.href,{waitUntil:'load'});
    const account=await follow(page,page.locator('.bk-header-account'));
    const main=page.locator('main.bk-account');
    const login=main.locator('form.woocommerce-form-login');
    const nav=main.locator('.woocommerce-MyAccount-navigation');
    const content=main.locator('.woocommerce-MyAccount-content');
    await login.waitFor({state:'visible'});
    await main.locator('form.woocommerce-form-register #reg_email').waitFor({state:'visible'});
    assert.equal(await nav.count(),0,'No account navigation for guests');
    assert.equal(await main.locator('.woocommerce-orders-table').count(),0);
    await audit(page,'guest-'+width);
    phase='recovery';
    await follow(page,login.locator('.lost_password a'));
    await main.locator('form.lost_reset_password #user_login').waitFor({state:'visible'});
    assert.equal(await main.locator('input[name=woocommerce-lost-password-nonce]').count(),1);
    await audit(page,'recovery-'+width);
    // Do not submit recovery or registration: no mail delivery in this suite.
    await page.goto(account.href,{waitUntil:'load'});
    phase='login';
    await login.locator('#username').fill('ci-bakata-account-own');
    await login.locator('#password').fill(password);
    await submit(page,login.locator('button[name=login]'));
    await nav.waitFor({state:'visible'});
    assert.equal(await login.count(),0,'Authentication succeeded');
    assert.equal(await nav.locator('a[aria-current=page]').count(),1);
    await audit(page,'dashboard-'+width);
    phase='orders';
    await follow(page,nav.locator('.woocommerce-MyAccount-navigation-link--orders a'));
    const rows=content.locator('.woocommerce-orders-table__row');
    await rows.first().waitFor({state:'visible'});
    assert.equal(await rows.count(),1,'Only own historical order');
    const ownLink=rows.first().locator('.woocommerce-orders-table__cell-order-number a');
    const ownUrl=await follow(page,ownLink);
    assert(ownUrl.pathname.endsWith('/'+own+'/')||ownUrl.searchParams.get('view-order')===String(own),'Own order ID');
    await content.getByText('CI Account Order own',{exact:true}).waitFor({state:'visible'});
    assert.equal(await content.getByText('CI Account Order other',{exact:true}).count(),0);
    await audit(page,'order-detail-'+width);
    phase='isolation';
    const foreignUrl=new URL(ownUrl);
    if(foreignUrl.searchParams.has('view-order'))foreignUrl.searchParams.set('view-order',String(other));
    else foreignUrl.pathname=foreignUrl.pathname.replace(new RegExp('/'+own+'/?$'),'/'+other+'/');
    assert.notEqual(foreignUrl.href,ownUrl.href);
    await page.goto(foreignUrl.href,{waitUntil:'load'});
    await main.locator('.woocommerce-error').waitFor({state:'visible'});
    assert.equal(await main.getByText('CI Account Order other',{exact:true}).count(),0,'Foreign order must not leak');
    assert.equal(await main.locator('.woocommerce-order-details').count(),0);
    phase='profile';
    await follow(page,nav.locator('.woocommerce-MyAccount-navigation-link--edit-account a'));
    const profile=content.locator('form.woocommerce-EditAccountForm');
    const display='CI Customer '+width;
    await profile.locator('#account_display_name').fill(display);
    await submit(page,profile.locator('button[name=save_account_details]'));
    await page.reload({waitUntil:'load'});
    await profile.locator('#account_display_name').waitFor({state:'visible'});
    assert.equal(await profile.locator('#account_display_name').inputValue(),display,'Profile persists');
    await audit(page,'profile-'+width);
    phase='addresses';
    await follow(page,nav.locator('.woocommerce-MyAccount-navigation-link--edit-address a'));
    const shipping=content.locator('.woocommerce-Address .edit').filter({hasText:/Shipping address/i});
    await follow(page,shipping);
    const address=content.locator('.woocommerce-address-fields');
    const street='Calle de prueba '+width;
    await address.locator('#shipping_address_1').fill(street);
    assert.equal(await address.locator('#shipping_city').inputValue(),'Bogotá');
    assert.equal(await address.locator('#shipping_state').inputValue(),'CO-DC');
    await submit(page,address.locator('button[name=save_address]'));
    await content.getByText(street,{exact:false}).waitFor({state:'visible'});
    await follow(page,shipping);
    await address.locator('#shipping_address_1').waitFor({state:'visible'});
    assert.equal(await address.locator('#shipping_address_1').inputValue(),street,'Address persists');
    await audit(page,'address-'+width);
    phase='logout';
    const logout=nav.locator('.woocommerce-MyAccount-navigation-link--customer-logout a');
    const logoutUrl=new URL(await logout.getAttribute('href'),base);
    assert.equal(logoutUrl.origin,base.origin);
    await Promise.all([page.waitForNavigation({waitUntil:'load'}),logout.click()]);
    await login.waitFor({state:'visible'});
    assert.equal(await nav.count(),0);
    await page.goto(ownUrl.href,{waitUntil:'load'});
    await login.waitFor({state:'visible'});
    assert.equal(await main.getByText('CI Account Order own',{exact:true}).count(),0,'Logged-out order must not leak');
    results.push({width,passed:true,ownOrder:true,foreignOrderDenied:true,profileSaved:true,addressSaved:true,loggedOut:true});
  } catch(error) {
    // No request bodies, form values, credentials or order URLs with nonces in logs.
    failures.push({width,phase,error:String(error).replaceAll(password,'[redacted]').slice(0,1600),path:new URL(page.url()).pathname});
    // Avoid capturing partially filled authentication forms.
    if(!['guest','login','recovery'].includes(phase))await page.screenshot({path:out('failure-account-'+width+'.png'),fullPage:true}).catch(()=>{});
  } finally {await context.close();}
}
try {for(const width of [320,768,1440])await run(width);}
finally {await browser.close();await writeFile(out('summary-account.json'),JSON.stringify({results,failures},null,2));}
console.log(JSON.stringify({results,failures}));
if(failures.length)process.exitCode=1;
