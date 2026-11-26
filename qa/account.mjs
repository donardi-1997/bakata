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
  // Fail on a hidden control directly, rather than masking the click error
  // with a concurrent navigation timeout. All links must be user actionable.
  await link.waitFor({state:'visible'});
  await link.click();
  await page.waitForURL(u=>u.href===url.href,{waitUntil:'domcontentloaded'});
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
    assert.equal(await main.locator('.bk-account-shortcuts').count(),0,'No dashboard shortcuts for guests');
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
    const shortcuts=content.locator('.bk-account-shortcuts');
    await shortcuts.waitFor({state:'visible'});
    assert.equal(await shortcuts.locator('a.bk-account-shortcut').count(),3,'Three native dashboard shortcuts');
    for(const [label,endpoint] of [['Mis pedidos','orders'],['Mis direcciones','edit-address'],['Mi perfil','edit-account']]) {
      const link=shortcuts.getByRole('link',{name:new RegExp('^'+label)});
      const native=nav.locator('.woocommerce-MyAccount-navigation-link--'+endpoint+' a');
      assert.equal(new URL(await link.getAttribute('href'),base).href,new URL(await native.getAttribute('href'),base).href,'Shortcut uses native endpoint');
    }
    await audit(page,'dashboard-'+width);
    phase='orders';
    await follow(page,shortcuts.getByRole('link',{name:/^Mis pedidos/}));
    assert.equal(await main.locator('.bk-account-shortcuts').count(),0,'Shortcuts only on dashboard');
    const rows=content.locator('.woocommerce-orders-table__row');
    await rows.first().waitFor({state:'visible'});
    assert.equal(await rows.count(),1,'Only own historical order');
    const ownLink=rows.first().locator('.woocommerce-orders-table__cell-order-number a');
    await ownLink.waitFor({state:'visible'});
    const listedUrl=new URL(await ownLink.getAttribute('href'),page.url());
    assert(listedUrl.pathname.endsWith('/'+own+'/')||listedUrl.searchParams.get('view-order')===String(own),'Own order ID in list');
    await page.screenshot({path:out('account-orders-'+width+'.png'),fullPage:true});
    phase='order-detail';
    const ownUrl=await follow(page,ownLink);
    const details=content.locator('.woocommerce-order-details');
    await details.waitFor({state:'visible'});
    assert.equal((await content.locator('mark.order-number').innerText()).trim(),String(own),'Own order ID in detail');
    const line=details.locator('tr.woocommerce-table__line-item');
    await line.waitFor({state:'visible'});
    assert.equal(await line.count(),1,'One historical line');
    const cell=line.locator('.woocommerce-table__product-name');
    // A historical product without a linked catalog product is rendered as
    // plain text followed by the native strong.product-quantity element.
    const name=await cell.evaluate(el=>{
      const copy=el.cloneNode(true);
      copy.querySelectorAll('.product-quantity,.wc-item-meta').forEach(node=>node.remove());
      return copy.textContent.trim();
    });
    assert.equal(name,'CI Account Order own','Exact historical product name');
    assert.match(await cell.locator('.product-quantity').innerText(),/^×\s*1$/,'Native item quantity');
    assert(!(await content.innerText()).includes('CI Account Order other'),'Foreign order item absent');
    await audit(page,'order-detail-'+width);
    phase='isolation';
    const foreignUrl=new URL(ownUrl);
    if(foreignUrl.searchParams.has('view-order'))foreignUrl.searchParams.set('view-order',String(other));
    else foreignUrl.pathname=foreignUrl.pathname.replace(new RegExp('/'+own+'/?$'),'/'+other+'/');
    assert.notEqual(foreignUrl.href,ownUrl.href);
    const deniedResponse=await page.goto(foreignUrl.href,{waitUntil:'load'});
    assert(deniedResponse?.ok(),'Native account error page rendered');
    assert.equal(new URL(page.url()).href,foreignUrl.href,'Denial on requested order endpoint');
    // WooCommerce selects block notices for block themes and classic notices
    // for classic themes. Both expose role=alert; require the actual error.
    const denial=content.getByRole('alert').filter({hasText:/Invalid order\./});
    await denial.waitFor({state:'visible'});
    assert.equal(await denial.count(),1,'One explicit native denial notice');
    const returnLink=denial.getByRole('link',{name:'My account',exact:true});
    assert.equal(new URL(await returnLink.getAttribute('href'),page.url()).href,account.href);
    assert(await nav.isVisible(),'Customer remains authenticated');
    assert.equal(await login.count(),0,'Denial is authorization, not authentication failure');
    assert(!(await main.textContent()).includes('CI Account Order other'),'Foreign order must not leak, even in hidden markup');
    assert(!(await main.textContent()).includes('ci-bakata-account-other@example.invalid'),'Foreign customer email must not leak');
    assert.equal(await main.locator('.woocommerce-order-details,.woocommerce-customer-details,mark.order-number,tr.woocommerce-table__line-item').count(),0,'No foreign order or customer details');
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
    assert(!(await main.textContent()).includes('CI Account Order own'),'Logged-out order must not leak, even in hidden markup');
    assert.equal(await main.locator('.woocommerce-order-details').count(),0);
    results.push({width,passed:true,ownOrder:true,foreignOrderDenied:true,profileSaved:true,addressSaved:true,loggedOut:true});
  } catch(error) {
    // No request bodies, form values, credentials or order URLs with nonces in logs.
    failures.push({width,phase,error:String(error).replaceAll(password,'[redacted]').slice(0,1600),path:new URL(page.url()).pathname,orderLayout:await page.locator('main.bk-account .woocommerce-orders-table__cell-order-number, main.bk-account .woocommerce-order-details').evaluateAll(nodes=>nodes.map(el=>({tag:el.tagName,className:el.className,display:getComputedStyle(el).display,visible:el.getBoundingClientRect().height>0}))).catch(()=>[])});
    // Avoid capturing partially filled authentication forms.
    if(!['guest','login','recovery'].includes(phase))await page.screenshot({path:out('failure-account-'+width+'.png'),fullPage:true}).catch(()=>{});
  } finally {await context.close();}
}
try {for(const width of [320,768,1440])await run(width);}
finally {await browser.close();await writeFile(out('summary-account.json'),JSON.stringify({results,failures},null,2));}
console.log(JSON.stringify({results,failures}));
if(failures.length)process.exitCode=1;
