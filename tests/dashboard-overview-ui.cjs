// Actual client/browser over synthetic local data; no user login or external source.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
(async()=>{
 const fixture=spawn(process.env.ASIS_PYTHON||'python3',[path.join(__dirname,'fixtures/overview_server.py')]);
 let browser;
 try{
  const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('fixture startup timed out')),10000);fixture.stdout.once('data',chunk=>{clearTimeout(timer);resolve(chunk.toString().trim());});fixture.once('exit',code=>reject(Error('fixture stopped: '+code)));});
  assert.match(port,/^\d+$/);
  browser=await chromium.launch({channel:process.env.ASIS_BROWSER_CHANNEL||'chrome',headless:true});
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const base='http://127.0.0.1:'+port,output=process.env.ASIS_UI_OUTPUT||path.join(__dirname,'../.local/overview-ui');fs.mkdirSync(output,{recursive:true});
  for(const [name,width,height] of [['desktop',1280,1000],['mobile',390,844]]){
   await page.setViewportSize({width,height});await page.goto(base+'/overview');await page.waitForSelector('#overview-services .overview-card');
   assert.equal(await page.locator('#dashboard-detail').isVisible(),false);
   assert.equal(await page.locator('#overview-services .overview-card').count(),6);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
   assert.equal(await page.locator('#overview-recent script').count(),0);
   await page.screenshot({path:path.join(output,name+'.png'),fullPage:true});
  }
  await page.goto(base+'/dashboard');await page.waitForSelector('#dashboard-detail:not([hidden])');await page.waitForFunction(()=>document.getElementById('record-count').textContent==='0');
  assert.equal(await page.locator('#overview').isVisible(),false);assert.equal(await page.locator('#board-status').textContent(),'');
  assert.deepEqual(errors,[]);console.log(JSON.stringify({desktop_and_mobile:true,no_horizontal_overflow:true,six_status_cards:true,source_text_rendered_safely:true,detail_view_preserved:true,no_browser_errors:true}));
 }finally{if(browser)await browser.close();fixture.kill('SIGINT');}
})().catch(e=>{console.error(e);process.exitCode=1;});
