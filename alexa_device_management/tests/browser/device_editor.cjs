// Local browser regression test; HTTP/API fixtures never contact HA or Alexa.
const {chromium} = require(process.env.ADM_PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const web = path.resolve(__dirname, '../../rootfs/opt/alexa_device_management/web/static');
const artifacts = process.env.ADM_UI_ARTIFACTS || fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'adm-ui-'));
fs.mkdirSync(artifacts, {recursive:true});
const entities = [
  {entity_id:'switch.relay_a',domain:'switch',name:'Leselampe',category_suggestion:'SWITCH'},
  {entity_id:'switch.relay_b',domain:'switch',name:'Steckdose',category_suggestion:'SWITCH'},
  {entity_id:'sensor.temperature',domain:'sensor',name:'Temperatur',device_class:'temperature',state:'21',category_suggestion:'TEMPERATURE_SENSOR'},
];
let configuration = {schema_version:6,native_enabled:true,native_revision:'initial',entities:{},virtual_groups:[]};
for (const [index,e] of entities.entries()) configuration.entities[e.entity_id] = {
  enabled:true,name:e.name,group_mode:index<2?'combined':'',logical_device_name:index<2?'Wohnzimmer Relais':e.name,
  native_endpoint_ids:[index<2?'native:relay':'native:temperature'],read_only:index===2,
  display_category:index<2?'SWITCH':'TEMPERATURE_SENSOR',display_category_mode:'standard',
  capability_mode:'standard',capabilities:[index<2?'Alexa.PowerController':'Alexa.TemperatureSensor']};
const devices = [{device_id:'relay',name:'Doppelrelais',area_id:'living',area_name:'Wohnzimmer',entities:entities.slice(0,2)},
  {device_id:'sensor',name:'Raumsensor',area_id:'living',area_name:'Wohnzimmer',entities:entities.slice(2)}];
for(let i=0;i<28;i++) devices.push({device_id:`d${i}`,name:`Weiteres Gerät ${i+1}`,area_id:'living',area_name:'Wohnzimmer',entities:[{entity_id:`switch.extra_${i}`,domain:'switch',name:`Ausgang ${i+1}`} ]});
function overview(){return {configuration:structuredClone(configuration),alexa_connected:true,display_categories:['SWITCH','LIGHT','SMARTPLUG'],areas:[{area_id:'living',name:'Wohnzimmer'}],groups:[],alexa_only:[],summary:{ha_devices:30,ha_entities:31,selected:3},devices:devices.map(d=>({...d,entities:d.entities.map(e=>({...e,status:'synced',export:configuration.entities[e.entity_id]||{enabled:false},native:{enabled:true,endpoint_ids:configuration.entities[e.entity_id]?.native_endpoint_ids||[]}}))}))};}
const writes=[];
const server = http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname.startsWith('/api/')) {
    let input=''; for await(const chunk of req)input+=chunk;
    const body=input?JSON.parse(input):{};
    if(req.method==='POST')writes.push({path:url.pathname,body});
    let result={};
    if(url.pathname==='/api/device-overview')result=overview();
    if(url.pathname==='/api/ha-export/autosave'){configuration=structuredClone(body);configuration.native_revision=String(Date.now());result={configuration};}
    if(url.pathname==='/api/native-export/virtual-group')result={configuration};
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(result));return;
  }
  const filename=url.pathname==='/'?'device_overview.html':path.basename(url.pathname);
  if(!fs.existsSync(path.join(web,filename))){res.writeHead(404);res.end();return;}
  const content=fs.readFileSync(path.join(web,filename));
  res.writeHead(200,{'Content-Type':filename.endsWith('.js')?'text/javascript':filename.endsWith('.css')?'text/css':'text/html'});
  res.end(filename.endsWith('.html')?content.toString().replaceAll('{{INGRESS_PATH}}','').replaceAll('{{OVERVIEW_ASSET_VERSION}}','test'):content);
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({executablePath:process.env.ADM_BROWSER_EXECUTABLE || undefined,headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.locator('#btn-start-edit').click();
    const name=page.locator('.export-name[data-entity="switch.relay_a"]');
    await name.fill('Leselicht');
    await page.locator('.export-device-name[data-entity="switch.relay_a"]').fill('Wohnzimmerbeleuchtung');
    await page.locator('.export-category[data-entity="switch.relay_a"]').selectOption('LIGHT');
    await page.locator('.export-access[data-entity="switch.relay_a"]').selectOption('read');
    assert.equal(await page.locator('.export-device-name').count(),1);
    assert.equal(await page.locator('.export-access[data-entity="sensor.temperature"] option[value="write"]').evaluate(e=>e.disabled),true);
    await page.locator('#btn-finish-edit').click();
    await page.waitForFunction(()=>!document.getElementById('btn-start-edit').classList.contains('hidden'));
    assert.equal(configuration.entities['switch.relay_a'].name,'Leselicht');
    assert.equal(configuration.entities['switch.relay_a'].display_category,'LIGHT');
    assert.equal(configuration.entities['switch.relay_a'].read_only,true);
    await page.reload();await page.locator('#btn-start-edit').click();
    assert.equal(await name.inputValue(),'Leselicht');
    assert.equal(await page.locator('.export-category[data-entity="switch.relay_a"]').inputValue(),'LIGHT');
    for (const id of ['switch.relay_a','switch.relay_b'])await page.locator(`[data-combine-entity="${id}"]`).check();
    await page.locator('#search').fill('Raumsensor');
    assert.match(await page.locator('#entity-selection-count').textContent(),/2 Entities/);
    await page.locator('#search').fill('');
    await page.reload();
    await page.locator('#btn-combine-selection').waitFor({state:'visible'});
    assert.match(await page.locator('#entity-selection-count').textContent(),/2 Entities/);
    await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
    const sticky=await page.locator('#btn-finish-edit').boundingBox();assert(sticky.y>=0&&sticky.y<200);
    await page.locator('#btn-combine-selection').click();
    assert.equal(await page.locator('#virtual-group-dialog input[data-vgroup-entity]:checked').count(),2);
    assert.equal(await page.locator('.virtual-group-entity:visible').count(),2);
    await page.locator('#virtual-group-name').fill('Gemeinsame Beleuchtung');
    await page.locator('#btn-stage-virtual-group').click();
    assert.equal(await page.locator('#entity-selection-actions').isVisible(),false);
    await page.locator('#btn-finish-edit').click();
    await page.waitForFunction(()=>!document.getElementById('btn-start-edit').classList.contains('hidden'));
    const group=writes.find(w=>w.path==='/api/native-export/virtual-group');
    assert.deepEqual(group.body.entity_ids.sort(),['switch.relay_a','switch.relay_b']);
    assert.equal(group.body.names['switch.relay_a'],'Leselicht');
    await page.locator('#btn-start-edit').click();
    await page.evaluate(()=>window.scrollTo(0,document.getElementById('content').offsetTop-190));
    await page.screenshot({path:path.join(artifacts,'editor-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    await page.evaluate(()=>window.scrollTo(0,document.getElementById('content').offsetTop-160));
    await page.screenshot({path:path.join(artifacts,'editor-mobile.png')});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
    await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
    const mobileSticky=await page.locator('#btn-finish-edit').boundingBox();assert(mobileSticky.y>=0&&mobileSticky.y<200);
    assert.deepEqual(errors,[]);
    console.log('PASS: names, endpoint names, type/access save + reload, sensor guard, selection across filters/reload, contextual grouping, desktop/mobile sticky controls, no horizontal overflow or JS errors.');
  } finally {await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
