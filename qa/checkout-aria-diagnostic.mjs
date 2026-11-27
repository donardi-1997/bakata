// Isolated diagnostic only: never press Place Order or send checkout POSTs.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { chromium } from 'playwright';
import { validReportId } from './checkout-report-id.mjs';

assert.equal(process.env.BAKATA_CI_FIXTURES,'1');
const base=new URL(process.env.BAKATA_QA_BASE_URL||'http://localhost:8080/');
assert.equal(base.protocol,'http:');
assert(['localhost','127.0.0.1'].includes(base.hostname));
assert.equal(base.pathname,'/');
assert(!base.username&&!base.password&&!base.search&&!base.hash);
const product=process.env.BAKATA_QA_PRODUCT_ID||'';
const variant=process.env.BAKATA_QA_VARIANT||'bakata';
assert(/^[1-9][0-9]*$/.test(product));
assert(validReportId(variant),'Invalid variant');
const runId=process.env.BAKATA_QA_RUN_ID||randomUUID();
assert(validReportId(runId),'Invalid run ID');
const runRoot=new URL(`./reports/checkout-diagnostics/${runId}/`,import.meta.url);
await mkdir(runRoot,{recursive:true});
const reports=new URL(`${variant}/`,runRoot);
await mkdir(reports);
const require=createRequire(import.meta.url);
const browser=await chromium.launch();
const context=await browser.newContext({viewport:{width:768,height:900},reducedMotion:'reduce'});
let blocked=0;
await context.route('**/*',route=>{
  const req=route.request(),url=new URL(req.url());
  if(url.origin!==base.origin)return route.abort();
  const path=url.searchParams.get('rest_route')||url.pathname;
  if(req.method()==='POST'&&(/\/wc\/store\/v\d+\/checkout(?:\/|$)/.test(path)||path==='/checkout/'||url.searchParams.get('wc-ajax')==='checkout')){
    blocked++;return route.abort();
  }
  return route.continue();
});
const page=await context.newPage();
try {
  const add=new URL(base);add.searchParams.set('add-to-cart',product);
  await page.goto(add.href,{waitUntil:'load'});
  await page.goto(new URL('checkout/',base).href,{waitUntil:'load'});
  const email=page.locator('#email');
  await email.waitFor({state:'visible'});
  await email.fill('invalid-email');
  await email.evaluate(el=>el.blur());
  await page.waitForFunction(()=>document.querySelector('#email')?.getAttribute('aria-invalid')==='true');
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
  const observations=[];
  async function observe(stage) {
    const dom=await page.evaluate(()=>{
      const input=document.querySelector('#email');
      const id=input.getAttribute('aria-errormessage');
      const target=document.getElementById(id);
      const live=target?.closest('[role="alert"],[aria-live]');
      return {invalid:input.getAttribute('aria-invalid'),describedBy:input.getAttribute('aria-describedby'),errorId:id,
        target:target?.outerHTML,liveAncestor:live?.outerHTML};
    });
    const axe=await page.evaluate(()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}}));
    await writeFile(fileURLToPath(new URL(`axe-diagnostic-${variant}-${stage}.json`,reports)),JSON.stringify(axe,null,2));
    observations.push({stage,dom,violations:axe.violations.map(v=>({id:v.id,impact:v.impact,targets:v.nodes.map(n=>n.target)})),incomplete:axe.incomplete.map(v=>v.id)});
  }
  await observe('initial');
  await page.waitForTimeout(2000);
  await observe('stable');
  // Controlled diagnostic, not a proposed production patch.
  await email.evaluate(el=>el.setAttribute('aria-describedby',[el.getAttribute('aria-describedby'),el.getAttribute('aria-errormessage')].filter(Boolean).join(' ')));
  await observe('describedby-experiment');
  assert.equal(blocked,0,'No checkout submission attempted');
  await writeFile(fileURLToPath(new URL(`checkout-aria-diagnostic-${variant}.json`,reports)),JSON.stringify({observations,blockedSubmissions:blocked},null,2));
  console.log(JSON.stringify({runId,reportDirectory:fileURLToPath(reports),variant,observations,blockedSubmissions:blocked}));
} finally {
  await context.close();
  await browser.close();
}
