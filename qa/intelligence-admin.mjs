import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

assert.equal(process.env.BAKATA_CI_FIXTURES,'1');
const base = 'http://localhost:8080';
const url = base+'/wp-admin/admin.php?page=bakata-intelligence';
const env = Object.fromEntries((await readFile('.env','utf8')).split(/\r?\n/).filter(l=>/^[A-Z_]+=/.test(l)).map(l=>[l.slice(0,l.indexOf('=')),l.slice(l.indexOf('=')+1)]));
const password = process.env.BAKATA_CI_INTELLIGENCE_PASSWORD;
assert(password?.length>=24);
const browser=await chromium.launch();
const reports=new URL('./reports/',import.meta.url);
await mkdir(reports,{recursive:true});
async function context(){
  const c=await browser.newContext({viewport:{width:1440,height:900}});
  await c.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
  return c;
}
async function login(c,user,pass){
  const p=await c.newPage();
  await p.goto(base+'/wp-login.php');
  await p.locator('#user_login').fill(user);
  await p.locator('#user_pass').fill(pass);
  await Promise.all([p.waitForURL(u=>!u.pathname.endsWith('wp-login.php')),p.locator('#wp-submit').click()]);
  return p;
}
try {
  const guest=await context();
  const gp=await guest.newPage();
  await gp.goto(url);
  assert(!gp.url().includes('page=bakata-intelligence') || gp.url().includes('wp-login.php'));
  assert.equal(await gp.getByRole('heading',{name:'Bakatá Intelligence',exact:true}).count(),0);
  await guest.close();
  const restricted=await context();
  const rp=await login(restricted,'ci-bakata-intelligence-reader',password);
  const denied=await rp.goto(url);
  assert(denied?.status()===403,'Subscriber cannot view administrator panel');
  assert.equal(await rp.getByRole('heading',{name:'Bakatá Intelligence',exact:true}).count(),0);
  const deniedPost=await restricted.request.post(base+'/wp-admin/admin-post.php',{form:{action:'bakata_intelligence_clear'}});
  assert.equal(deniedPost.status(),403);
  await restricted.close();
  const admin=await context();
  const page=await login(admin,env.WP_ADMIN_USER,env.WP_ADMIN_PASSWORD);
  await page.goto(url);
  await page.getByRole('heading',{name:'Sin evaluaciones cargadas'}).waitFor();
  await page.locator('#bk-snapshot').setInputFiles('/tmp/bakata-intelligence-preview.json');
  await Promise.all([page.waitForURL(u=>u.searchParams.get('bk_notice')==='loaded'),page.locator('#bk_upload').click()]);
  await page.getByRole('heading',{name:'Resumen de datos simulados'}).waitFor();
  assert.equal(await page.locator('table.widefat tbody tr').count(),2);
  assert((await page.locator('table.widefat').innerText()).includes('77,77'));
  await page.locator('table.widefat summary').first().click();
  assert((await page.locator('table.widefat details[open]').innerText()).includes('fixture-cost'));
  await page.screenshot({path:new URL('intelligence-admin.png',reports).pathname,fullPage:true});
  await page.locator('#bk-status').selectOption('incomplete');
  await Promise.all([page.waitForURL(u=>u.searchParams.get('status')==='incomplete'),page.locator('#bk_filter').click()]);
  assert.equal(await page.locator('table.widefat tbody tr').count(),1);
  assert((await page.locator('table.widefat tbody').innerText()).includes('Precio no informado'));
  const noNonce=await admin.request.post(base+'/wp-admin/admin-post.php',{form:{action:'bakata_intelligence_clear'}});
  assert.equal(noNonce.status(),403);
  await page.reload();
  await page.getByRole('heading',{name:'Resumen de datos simulados'}).waitFor();
  await Promise.all([page.waitForURL(u=>u.searchParams.get('bk_notice')==='cleared'),page.locator('#bk_clear').click()]);
  await page.getByRole('heading',{name:'Sin evaluaciones cargadas'}).waitFor();
  await admin.close();
  console.log('Intelligence administrator preview passed.');
} finally {await browser.close();}
