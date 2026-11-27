import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright';
const script = 'wp-content/plugins/bakata-core/assets/dropify-visible-export.js';
const browser = await chromium.launch();
try {
  const page = await browser.newPage({acceptDownloads:true});
  await page.route('**/*', route => route.abort());
  const header = '<thead><tr><th><input type="checkbox"></th><th><a><span>ID</span><span>sort</span></a></th><th>SKU</th><th>Imagen</th><th>Nombre</th><th>Precio</th><th>Precio sugerido</th><th>Stock</th><th>Categoría</th><th>Bodega</th><th>Tienda</th><th>Actions</th></tr></thead>';
  const row = '<tr><td><input value="hidden-canary"></td><td>96</td><td>025216</td><td><img alt="opaque-canary"></td><td>Producto de prueba<br><a>Importar</a><span hidden>secret-canary</span></td><td>7.000</td><td>17.000</td><td>412</td><td>Otro</td><td>Fixture</td><td>fixture-store</td><td><a href="https://example.invalid/private?token=secret-canary">Acción</a></td></tr>';
  await page.setContent('<table>'+header+'<tbody>'+row+'</tbody></table>');
  await page.addScriptTag({content:await readFile(script,'utf8')});
  const button=page.getByRole('button',{name:'Exportar página visible a Bakatá Intelligence'});
  await button.waitFor();
  const [download]=await Promise.all([page.waitForEvent('download'),button.click()]);
  const data=await readFile(await download.path(),'utf8');
  const parsed=JSON.parse(data);
  assert.equal(parsed.schema,'bakata-dropify-visible-v1');
  assert.deepEqual(parsed.rows,[{external_id:'96',sku:'025216',title:'Producto de prueba',display_price:'7.000',suggested_price:'17.000',display_stock:'412',category:'Otro',warehouse:'Fixture',store:'fixture-store'}]);
  assert(!/canary|https:|Importar/.test(data));
  await writeFile('/tmp/bakata-dropify-visible-fixture.json',data,{mode:0o600});
  await page.locator('tbody').evaluate(el=>el.insertAdjacentHTML('beforeend',el.innerHTML));
  await button.click();
  assert((await page.getByRole('status').innerText()).includes('Identidades repetidas'));
  await page.setContent('<table><thead><tr><th>ID</th></tr></thead><tbody><tr><td>96</td></tr></tbody></table>');
  await page.addScriptTag({content:await readFile(script,'utf8')});
  assert.equal(await page.getByRole('button',{name:'Exportar página visible a Bakatá Intelligence'}).count(),0);
  console.log('Visible Dropify export fixture passed.');
} finally {await browser.close();}
