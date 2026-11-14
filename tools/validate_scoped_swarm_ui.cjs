/* Served-build UI acceptance. Every API/WebSocket is intercepted; no command
 * or fixture can reach a real GCS. Uses the same browser settings as Overview. */
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const {chromium} = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.MDS_OVERVIEW_URL || 'http://127.0.0.1:3038';
const output = process.env.MDS_OVERVIEW_OUTPUT;
async function run() {
  if (output) fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true, executablePath:process.env.MDS_CHROMIUM_PATH,
    args:['--no-sandbox','--disable-dev-shm-usage']});
  const results=[];
  try {
    for (const scenario of [{count:1,groups:1},{count:3,groups:1},{count:100,groups:1},{count:100,groups:4}])
      for (const width of [390,768,900,1440]) for (const theme of ['dark','light']) {
      const context=await browser.newContext({viewport:{width,height:960},hasTouch:width<=768});
      const page=await context.newPage(), errors=[], writes=[];
      const groupSize=scenario.count/scenario.groups;
      const assignments=Array.from({length:scenario.count},(_,i)=>({hw_id:String(i+1),
        follow:i%groupSize===0?'0':String(Math.floor(i/groupSize)*groupSize+1),frame:'body',
        offset_x:i%groupSize===0?0:-5,offset_y:i*3,offset_z:0}));
      const members=assignments.map(row=>({...row,callsign:`AIRCRAFT-${row.hw_id}`,available:true,
        armed:true,landed_state:2,flight_mode:50593792,readiness_status:'ready'}));
      const ready=hw_id=>({hw_id,status:'ready',message:'Ready',valid_for_ms:10000,scoped_start_supported:true});
      page.on('pageerror',e=>errors.push(e.message));
      await page.routeWebSocket('**/*',socket=>socket.close());
      await page.route('**/*',route=>{
        const request=route.request(),url=new URL(request.url());
        if (!['GET','HEAD','OPTIONS'].includes(request.method())) {
          writes.push({path:url.pathname,body:request.postDataJSON()});
          return route.fulfill({status:409,json:{detail:url.pathname.endsWith('/sequential-return')
            ? 'Fixture: no dispatch' : {message:'Fixture: no dispatch',dispatched:false}}});
        }
        if(url.port!=='5030' && !url.pathname.startsWith('/api/')) return route.continue();
        let json;
        if(url.pathname.includes('/auth'))json={dashboard_auth_enabled:false,api_auth_enabled:false,authenticated:true};
        else if(url.pathname==='/api/v1/config/fleet')json=members;
        else if(url.pathname==='/api/v1/config/swarm')json={version:1,assignments};
        else if(url.pathname==='/api/v1/swarm/runtime/preview') {
          const targets=url.searchParams.getAll('target_hw_ids');
          const ids=targets.length?targets:members.slice(0,groupSize).map(m=>m.hw_id);
          const refs=targets.length&&!targets.includes('1')?['1']:[];
          const clusters=Array.from({length:scenario.groups},(_,i)=>({cluster_id:String(i*groupSize+1),members:members.slice(i*groupSize,(i+1)*groupSize)}));
          json={runtime_mode:'SITL',revision:'a'.repeat(64),clusters,
            observed_at_ms:Date.now(),runtime_nodes:{},start_admissions:Object.fromEntries(ids.map(id=>[id,ready(id)])),
            reference_hw_ids:refs,reference_admissions:Object.fromEntries(refs.map(id=>[id,ready(id)]))};
        }
        else if(url.pathname==='/api/v1/swarm/runtime/sequential-return')json=null;
        else if(url.pathname.includes('/commands/active')||url.pathname.includes('/commands/recent'))json={commands:[]};
        else if(url.pathname.includes('/runtime-status'))json={mode:'sitl',configured_mode:'sitl',restart_required:false};
        else if(url.pathname.includes('/health'))json={status:'healthy'};
        else if(url.pathname.includes('git'))json={gcs_status:{commit:'1234567',status:'clean'},git_status:{}};
        else return route.fulfill({status:503,json:{detail:'No read fixture'}});
        return route.fulfill({status:200,json,headers:{'access-control-allow-origin':new URL(base).origin,
          'access-control-allow-credentials':'true','access-control-allow-methods':'GET,HEAD,OPTIONS',
          'access-control-allow-headers':'Content-Type'}});
      });
      await page.addInitScript(theme=>localStorage.setItem('drone-dashboard-theme',theme),theme);
      await page.goto(base+'/swarm-design');
      const scope=page.getByRole('button',{name:'Choose command aircraft',exact:true});
      await page.waitForFunction(count=>document.querySelector('[data-recipient-count]')?.dataset.recipientCount===String(count),groupSize);
      const clusterChoice=page.getByRole('combobox',{name:'Swarm formation'});
      assert.equal(await clusterChoice.count(),scenario.groups>1?1:0,'Show formation choice only when needed');
      assert.equal(await scope.getAttribute('data-recipient-count'),String(groupSize));
      if(scenario.groups>1){
        await clusterChoice.selectOption(String((scenario.groups-1)*groupSize+1));
        await page.waitForFunction(id=>document.querySelector('[aria-label="Choose command aircraft"]')?.title.includes(`AIRCRAFT-${id}`),String((scenario.groups-1)*groupSize+1));
        assert.equal(await scope.getAttribute('data-recipient-count'),String(groupSize));
        await clusterChoice.selectOption('1');
        await page.waitForFunction(()=>document.querySelector('[aria-label="Choose command aircraft"]')?.title.includes('AIRCRAFT-1,'));
      }
      assert.equal(await page.getByRole('button',{name:'Hold all',exact:true}).count(),1);
      assert.equal(await page.getByRole('button',{name:'Managed Return',exact:true}).count(),1);
      const prefix=`${scenario.count}-${scenario.groups}-${width}-${theme}`;
      const actions=await page.locator('.swarm-ops__actions').boundingBox();
      const diagram=await page.locator('.swarm-ops > .swarm-diagram').boundingBox();
      assert(actions.y<diagram.y,'Controls precede the bounded roster');
      assert(diagram.height<=450,'Large roster cannot bury recovery controls');
      if(output)await page.screenshot({path:path.join(output,`swarm-${prefix}.png`),fullPage:true});
      await scope.click();
      const picker=page.getByRole('dialog',{name:'Command aircraft',exact:true});
      await picker.waitFor();
      const bounds=await picker.boundingBox();
      assert(bounds.x>=-2&&bounds.x+bounds.width<=width+2,'Picker inside viewport');
      await picker.getByRole('button',{name:'Clear command aircraft'}).click();
      const selected=scenario.count===1?'1':'2';
      await picker.getByRole('checkbox',{name:`Include AIRCRAFT-${selected} (H${selected})`}).check();
      if(output)await picker.screenshot({path:path.join(output,`swarm-to-${prefix}.png`)});
      await picker.getByRole('button',{name:'Use 1 aircraft'}).click();
      assert.equal(await scope.getAttribute('data-recipient-count'),'1');
      await page.getByRole('button',{name:'Start Swarm',exact:true}).click();
      const review=page.getByRole('dialog',{name:'Start Swarm',exact:true});
      if(scenario.count>1)await review.getByText('Leader reference: AIRCRAFT-1',{exact:true}).waitFor();
      else assert.equal(await review.locator('.swarm-ops__references').count(),0);
      await review.getByRole('button',{name:'Confirm Start Swarm',exact:true}).waitFor();
      assert(await review.getByRole('button',{name:'Confirm Start Swarm',exact:true}).isEnabled());
      assert(await scope.isDisabled(),'Reviewed scope is locked');
      assert.equal(writes.length,0,'Selection/review sends no command');
      if(output)await review.screenshot({path:path.join(output,`swarm-review-${prefix}.png`)});
      await review.getByRole('button',{name:'Confirm Start Swarm',exact:true}).click();
      await page.waitForFunction(()=>document.querySelector('[role=alert]')?.textContent.includes('Fixture'));
      assert.equal(writes.length,1);
      assert.equal(writes[0].path,'/api/v1/swarm/runtime/start');
      assert.deepEqual(writes[0].body.target_hw_ids,[selected]);
      await review.getByRole('button',{name:'Cancel',exact:true}).click();
      await page.reload();
      await page.waitForFunction(()=>document.querySelector('[data-recipient-count]')?.dataset.recipientCount==='1');
      await page.getByRole('button',{name:'Managed Return',exact:true}).click();
      const recovery=page.getByRole('dialog',{name:'Managed Return',exact:true});
      await recovery.waitFor();
      assert.equal(await recovery.locator('.swarm-return-order li').count(),1,'Return keeps the selected subset after remount');
      assert((await recovery.locator('.swarm-return-order').innerText()).includes(`AIRCRAFT-${selected}`));
      const recoveryBounds=await recovery.boundingBox();
      assert(recoveryBounds.x>=-2&&recoveryBounds.x+recoveryBounds.width<=width+2,'Return review inside viewport');
      if(output)await recovery.screenshot({path:path.join(output,`swarm-return-${prefix}.png`)});
      await recovery.getByRole('button',{name:'Start return',exact:true}).click();
      await page.waitForFunction(()=>document.querySelector('[role=alert]')?.textContent.includes('Fixture'));
      assert.equal(writes.length,2);
      assert.equal(writes[1].path,'/api/v1/swarm/runtime/sequential-return');
      assert.deepEqual(writes[1].body.target_drone_ids,[selected]);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'No horizontal overflow');
      assert.deepEqual(errors,[]);
      results.push({...scenario,width,theme,passed:true,fixture_submissions:writes.length,real_commands:0,errors});
      await context.close();
    }
    if(output)fs.writeFileSync(path.join(output,'summary.json'),JSON.stringify({status:'passed',scenarios:results.length,results},null,2));
    console.log(JSON.stringify({status:'passed',scenarios:results.length}));
  } finally {await browser.close();}
}
run().catch(error=>{console.error(error);process.exitCode=1;});
