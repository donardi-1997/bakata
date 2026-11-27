import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { referencedMessages, waitForInvalidMessage } from './checkout-validation.mjs';
import { validReportId } from './checkout-report-id.mjs';

for(const id of ['CON','con','PRN','AUX','NUL','COM1','lpt9','COM9','CONIN_','conout_'])assert.equal(validReportId(id),false,id);
for(const id of ['test-1','COM10','con_1','lpt0'])assert.equal(validReportId(id),true,id);
const browser=await chromium.launch({args:['--host-resolver-rules=MAP * ~NOTFOUND']});
try {
  const page=await browser.newPage({serviceWorkers:'block'});
  await page.route('**/*',route=>route.abort());
  await page.setContent('<label for="email">Email</label><input id="email" aria-describedby="notice"><p id="notice">Guest notice</p>');
  const field=page.locator('#email');
  const before=await referencedMessages(field);
  await field.evaluate(el=>{
    el.setAttribute('aria-invalid','true');
    setTimeout(()=>{
      const error=document.createElement('p');
      error.id='error';error.textContent='Invalid email';
      document.body.append(error);
      el.setAttribute('aria-errormessage','error');
    },150);
  });
  await waitForInvalidMessage(page,'email',before,2000);

  await page.setContent('<label for="email">Email</label><input id="email" aria-describedby="notice"><p id="notice">Guest notice</p><p id="error" hidden>Invalid email</p>');
  const baseline=await referencedMessages(field);
  await field.evaluate(el=>{el.setAttribute('aria-invalid','true');el.setAttribute('aria-errormessage','error');});
  await assert.rejects(waitForInvalidMessage(page,'email',baseline,200),/Timeout/);
  await page.locator('#error').evaluate(el=>{el.hidden=false;el.setAttribute('aria-hidden','true');});
  await assert.rejects(waitForInvalidMessage(page,'email',baseline,200),/Timeout/);
  await page.locator('#error').evaluate(el=>el.removeAttribute('aria-hidden'));
  await waitForInvalidMessage(page,'email',baseline,1000);
  const unchanged=await referencedMessages(field);
  await assert.rejects(waitForInvalidMessage(page,'email',unchanged,200),/Timeout/);

  await page.setContent('<label for="email">Email</label><input id="email" aria-describedby="notice"><p id="notice">Guest notice</p><p id="error">Invalid email</p><p id="error">Duplicate</p>');
  const duplicateBaseline=await referencedMessages(field);
  await field.evaluate(el=>{el.setAttribute('aria-invalid','true');el.setAttribute('aria-describedby','notice error');});
  await assert.rejects(waitForInvalidMessage(page,'email',duplicateBaseline,200),/Timeout/);
  await page.locator('[id="error"]').last().evaluate(el=>el.remove());
  await waitForInvalidMessage(page,'email',duplicateBaseline,1000);

  await page.setContent('<label for="email">Email</label><input id="email"><p id="error"><span aria-hidden="true">Hidden text</span></p>');
  const hiddenBaseline=await referencedMessages(field);
  await field.evaluate(el=>{el.setAttribute('aria-invalid','true');el.setAttribute('aria-errormessage','error');});
  assert.equal((await referencedMessages(field)).size,0);
  await assert.rejects(waitForInvalidMessage(page,'email',hiddenBaseline,200),/Timeout/);
  await page.locator('#error').evaluate(el=>el.append('Visible error'));
  await waitForInvalidMessage(page,'email',hiddenBaseline,1000);
  assert.equal((await referencedMessages(field)).get('error'),'Visible error');
  await page.evaluate(()=>{const duplicate=document.createElement('input');duplicate.id='email';document.body.append(duplicate);});
  await assert.rejects(waitForInvalidMessage(page,'email',hiddenBaseline,200),/Timeout/);
  await page.locator('[id="email"]').last().evaluate(el=>el.remove());
  await waitForInvalidMessage(page,'email',hiddenBaseline,1000);
  const start=Date.now();
  await assert.rejects(waitForInvalidMessage(page,'missing',new Map(),250),/Timeout/);
  assert(Date.now()-start<2000,'Missing element must not incur Playwright locator default timeout');
  console.log('Checkout validation wait and report ID checks passed.');
} finally {
  await browser.close();
}
