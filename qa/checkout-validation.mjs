// This function is also serialized into Playwright's browser-side wait.
function inspect(field) {
  if(!field)return {invalid:false,messages:[]};
  const ids=[...new Set(['aria-errormessage','aria-describedby'].flatMap(name=>(field.getAttribute(name)||'').trim().split(/\s+/).filter(Boolean)))];
  const messages=[];
  for(const id of ids) {
    const nodes=[...document.querySelectorAll('[id]')].filter(el=>el.id===id);
    if(nodes.length!==1)continue;
    const target=nodes[0];
    const visible=el=>!el.closest('[aria-hidden="true"],[inert]')&&el.checkVisibility({visibilityProperty:true})&&el.getClientRects().length>0;
    if(!visible(target))continue;
    const walker=document.createTreeWalker(target,NodeFilter.SHOW_TEXT);
    let node,text='';
    while((node=walker.nextNode())) {
      if(node.parentElement&&visible(node.parentElement))text+=node.nodeValue;
    }
    text=text.trim();
    if(text)messages.push([id,text]);
  }
  return {invalid:field.getAttribute('aria-invalid')==='true',messages};
}

export async function referencedMessages(field) {
  return new Map((await field.evaluate(inspect,{},{timeout:5000})).messages);
}

export async function waitForInvalidMessage(page,id,before,timeout=5000) {
  if(!id)throw Error('Invalid field has no ID');
  const predicate=new Function('args',`
    const {id,before}=args;
    const inspect = ${inspect.toString()};
    const fields=[...document.querySelectorAll('[id]')].filter(el=>el.id===id);
    if(fields.length!==1)return false;
    const snapshot=inspect(fields[0]);
    return snapshot.invalid && snapshot.messages.some(([key,text])=>!Object.hasOwn(before,key)||before[key]!==text);
  `);
  await page.waitForFunction(predicate,{id,before:Object.fromEntries(before)},{timeout});
}
