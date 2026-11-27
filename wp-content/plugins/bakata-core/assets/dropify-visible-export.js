(() => {
  'use strict';
  const fields = new Map([
    ['id','external_id'], ['sku','sku'], ['nombre','title'], ['precio','display_price'],
    ['precio sugerido','suggested_price'], ['stock','display_stock'], ['categoria','category'],
    ['bodega','warehouse'], ['tienda','store']
  ]);
  const normalize = s => s.normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toLowerCase().replace(/\s+/g,' ');
  const visible = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility === 'visible';
  function columns(table) {
    const row = table.tHead?.rows[0];
    if (!row) return null;
    const found = {};
    for (const [i,cell] of Array.from(row.cells).entries()) {
      if (!visible(cell)) continue;
      const title = normalize((cell.querySelector('a > span:first-child') || cell).innerText);
      if (fields.has(title)) {
        const field = fields.get(title);
        if (Object.hasOwn(found,field)) return null;
        found[field] = i;
      }
    }
    return Object.keys(found).length === fields.size ? found : null;
  }
  function locate() {
    const matches = Array.from(document.querySelectorAll('table')).filter(visible)
      .map(table => ({table,cols:columns(table)})).filter(x => x.cols);
    if (matches.length !== 1) throw Error('No se reconoce una única tabla Dropify compatible.');
    return matches[0];
  }
  function collect() {
    const {table,cols}=locate();
    const rows=[];
    for (const row of Array.from(table.tBodies).flatMap(body=>Array.from(body.rows))) {
      if (!visible(row)) continue;
      const record={};
      for (const [field,index] of Object.entries(cols)) {
        const cell=row.cells[index];
        if (!cell || !visible(cell) || cell.colSpan!==1) throw Error('La estructura de la tabla cambió.');
        let value=cell.innerText.trim().replace(/\s+/g,' ');
        if (field==='title') {
          // WP list-table row actions are not part of product names.
          const title=cell.querySelector(':scope > strong, .row-title');
          if (title && visible(title)) value=title.innerText.trim().replace(/\s+/g,' ');
          else {
            // Do not read hidden descendants or guess names from opaque markup.
            value=cell.innerText.split(/\n/).filter(x=>normalize(x)!=='importar').join(' ').trim().replace(/\s+/g,' ');
          }
        }
        if (value.length>512 || /[\u0000-\u001f\u007f]/.test(value)) throw Error('Campo fuera del contrato.');
        record[field]=value;
      }
      if (!/^[1-9][0-9]{0,29}$/.test(record.external_id) || !record.title || !record.store) throw Error('Fila sin identidad válida.');
      rows.push(record);
      if(rows.length>100) throw Error('Máximo 100 filas visibles por exportación.');
    }
    if(!rows.length) throw Error('No hay filas visibles.');
    const ids=new Set(rows.map(r=>JSON.stringify([r.store,r.external_id])));
    if(ids.size!==rows.length) throw Error('Identidades repetidas en la página.');
    return {schema:'bakata-dropify-visible-v1',captured_at:new Date().toISOString(),rows};
  }
  function mount() {
    if (document.getElementById('bk-dropify-export')) return;
    let table;
    try { ({table}=locate()); } catch (_) { return; }
    const box=document.createElement('div');
    box.id='bk-dropify-export';
    box.style.margin='12px 0';
    const button=document.createElement('button');
    button.type='button';
    button.className='button button-secondary';
    button.textContent='Exportar página visible a Bakatá Intelligence';
    const status=document.createElement('p');
    status.setAttribute('role','status');
    status.textContent='Solo esta página; el total mostrado por Dropify puede no ser real. No consulta Dropi ni importa productos.';
    button.addEventListener('click',()=>{
      try {
        const payload=collect();
        const blob=new Blob([JSON.stringify(payload)],{type:'application/json'});
        if(blob.size>262144) throw Error('Exportación superior a 256 KiB.');
        const url=URL.createObjectURL(blob);
        const link=document.createElement('a');
        link.href=url;
        link.download='bakata-dropify-'+payload.captured_at.replace(/[:.]/g,'-')+'.json';
        link.click();
        setTimeout(()=>URL.revokeObjectURL(url),1000);
        status.textContent='Exportadas '+payload.rows.length+' filas visibles.';
      } catch (error) {
        status.textContent='Exportación bloqueada: '+error.message;
      }
    });
    box.append(button,status);
    table.before(box);
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',mount,{once:true});
  else mount();
})();
