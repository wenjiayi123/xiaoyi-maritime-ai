const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const crypto=require('node:crypto');
const assert=require('node:assert/strict');
(async()=>{
  const out=path.resolve(process.env.RESEARCH_BROWSER_OUTPUT||'.codex_artifacts/research-v6-20261030/browser');
  await fs.mkdir(out,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:1080},acceptDownloads:true});
  const checks=[],errors=[],receipts=[];page.on('pageerror',e=>errors.push(e.message));
  const root=page.locator('#proofConsole');
  async function run(kind,status='completed'){
    const response=page.waitForResponse(r=>r.url().endsWith('/api/harness/proof/runs')&&r.request().method()==='POST');
    await root.locator(`[data-pf="run"][data-kind="${kind}"]`).first().click();
    const data=await(await response).json();receipts.push(data);
    await root.locator('[data-pf-current]').getByText(data.id,{exact:false}).waitFor();
    assert.equal(data.status,status);assert.equal(data.integrity.result_hash_valid,true);assert.equal(data.integrity.event_chain_valid,true);assert.equal(data.production_authority,false);return data;
  }
  async function sourceDownload(){
    const d=root.locator('[data-pf-research-sources]').first();await d.locator('summary').first().click();
    const button=d.locator('[data-pf=research-source]').first(),expected=await button.getAttribute('data-sha');
    const pending=page.waitForEvent('download');await button.click();const download=await pending;
    const destination=path.join(out,download.suggestedFilename());await download.saveAs(destination);
    assert.equal(crypto.createHash('sha256').update(await fs.readFile(destination)).digest('hex'),expected);
  }
  try{
    const boot=page.waitForRequest(r=>r.url().endsWith('/api/port-simulator/stream'));
    await page.goto('http://127.0.0.1:8010',{waitUntil:'domcontentloaded'});await boot;
    await page.locator('#proofConsoleBtn').click();await root.locator('[data-pf-v6]').waitFor();
    assert.equal(await root.locator('[data-pf-component]').count(),37);
    const catalog=await(await page.request.get('http://127.0.0.1:8010/api/harness/proof/catalog')).json();
    assert.equal(catalog.runtime_code_current,true);assert.equal(catalog.latest_research.scientific_evidence_current,true);
    checks.push('current loaded code and pinned scientific evidence; all37 independently scored entries visible');
    const first=await run('rl_v6');assert.equal(first.result.ports.length,8);assert.equal(first.result.seeds.length,5);
    assert.ok(first.result.runs.every(r=>r.frames.length===90&&!r.evaluation_mpc_fallback));
    assert.equal(first.result.aggregate.find(r=>r.algorithm===first.result.selection_summary.selected_rl).per_port.length,8);
    assert.match(await root.locator('[data-pf-current]').innerText(),/五次拟合不是五个独立港口/);
    checks.push('new eight-port90day frozen RL traces and all five fits, raw/filter distinctions and honest strong-baseline scope');
    await sourceDownload();checks.push('new port CSV downloaded from its corresponding interface with browser SHA256 verification');
    await root.locator('[name=v6port]').selectOption('port581');await root.locator('[name=v6quarter]').selectOption('04');await root.locator('[name=v6seed]').selectOption('632105');await root.locator('[name=v6scenario]').selectOption('publication_delay');
    const delayed=await run('rl_v6');assert.equal(delayed.parameters.seed,632105);assert.equal(delayed.parameters.port_id,'port581');
    assert.ok(delayed.result.runs.every(r=>r.frames.every(f=>(Date.parse(f.date)-Date.parse(f.public_latest_day))/86400000===14)));
    assert.ok(await root.locator('[data-pf-current] svg').count()>=2);
    await root.locator('[data-pf-current] h3').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'rl-five-fits.png')});
    checks.push('changing port, time, seed and14day public lag retrieves different bound complete trajectories with causal clocks');
    const initial=await run('long_twin_v6');assert.equal(initial.result.cells.length,56);
    const annualIndex=initial.result.cells.findIndex(c=>c.kind==='full_year_open_loop'&&c.model_status==='frozen'&&c.n>0&&c.n<c.expected);
    assert.ok(annualIndex>=0);await root.locator('[name=longcell]').selectOption(String(annualIndex));
    const annual=await run('long_twin_v6');assert.equal(annual.result.points.length,8760);assert.equal(annual.result.cell.expected,8760);
    assert.equal(annual.result.points[0].at,'2025-01-01T00:00:00+00:00');assert.equal(annual.result.points.at(-1).at,'2025-12-31T23:00:00+00:00');
    assert.ok(annual.result.points.some(p=>p.actual_m===null));assert.ok(annual.result.points.every(p=>p.test_observation_used_as_input===false));
    assert.ok(await root.locator('[data-pf-current] polyline[data-series="真实观测"]').count()>1);
    assert.match(await root.locator('[data-pf-current]').innerText(),/实际UTC时间/);
    await root.locator('[data-pf-current] h3').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'annual-real-gaps.png')});
    checks.push('all8760yearly hours, fixed origin, actual time axes, genuine missing-truth breaks and original frozen intervals visible');
    await sourceDownload();checks.push('selected tide station raw history response downloadable with preserved units/quality and SHA256');
    await page.setViewportSize({width:390,height:844});assert.equal(await root.evaluate(e=>e.scrollWidth<=e.clientWidth+2),true);await root.locator('[data-pf-current] h3').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'narrow-annual.png')});await page.setViewportSize({width:1440,height:1080});
    const blocked=annual.result.cells.findIndex(c=>c.station_id==='294'&&c.kind==='full_year_open_loop');
    await root.locator('[name=longcell]').selectOption(String(blocked));const missing=await run('long_twin_v6');
    assert.equal(missing.result.cell.passed,false);assert.equal(missing.result.cell.model_status,'blocked');assert.ok(missing.result.selection.source_errors.length>0);
    assert.match(await root.locator('[data-pf-current]').innerText(),/未通过/);
    checks.push('Newlyn missing source and frozen-model blockage remain explicit failures with original provider errors');
    const failed=annual.result.cells.findIndex(c=>c.station_id==='353'&&c.blockers.includes('coverage'));
    assert.ok(failed>=0);await root.locator('[name=longcell]').selectOption(String(failed));const coverage=await run('long_twin_v6');assert.equal(coverage.result.cell.passed,false);
    checks.push('independent Kushimoto coverage failure retained instead of widening intervals after viewing test labels');
    await root.locator('[data-pf-v6] [data-kind=rl_v6]').click();await root.locator('[name=v6seed]').waitFor();
    await page.evaluate(()=>{const select=document.querySelector('#proofConsole [name=v6seed]'),option=new Option('tampered','1');select.add(option);select.value='1';});
    const rejected=await run('rl_v6','failed');assert.ok(rejected.result.error);await root.locator('[data-pf-status=failed]').waitFor();
    checks.push('unregistered fit seed is rejected and stored as an actual visibly failed receipt');
    const exportPending=page.waitForEvent('download');await root.locator('[data-pf=export]').click();const exported=await exportPending;
    const file=path.join(out,'evidence-export.json');await exported.saveAs(file);const bundle=JSON.parse(await fs.readFile(file,'utf8'));
    assert.ok(bundle.receipts.some(r=>r.kind==='rl_v6'));assert.ok(bundle.receipts.some(r=>r.kind==='long_twin_v6'));assert.ok(bundle.receipts.some(r=>r.status==='failed'));
    assert.ok(bundle.receipts.every(r=>r.integrity.result_hash_valid&&r.integrity.event_chain_valid));
    checks.push('one-click export retains new RL/yearly evidence, failed requests, sources and locally verifiable receipts');
    const badSource=await page.request.get('http://127.0.0.1:8010/api/harness/proof/research-source/test/-1');assert.equal(badSource.status(),422);
    checks.push('source download accepts only registered study entries and refuses negative index');
    await page.setViewportSize({width:390,height:844});assert.equal(await root.evaluate(e=>e.scrollWidth<=e.clientWidth+2),true);
    await page.screenshot({path:path.join(out,'narrow-failure.png')});checks.push('new source, failure and research views stay within390pixel modal viewport');
    assert.deepEqual(errors,[]);checks.push('no browser runtime errors');
    const result={passed:true,checks,errors,receipts:receipts.map(r=>({id:r.id,kind:r.kind,status:r.status,integrity:r.integrity})),scientific_current:catalog.latest_research.scientific_evidence_current,whole_repository_current_at_start:catalog.latest_research.current,production_authority:false};
    await fs.writeFile(path.join(out,'acceptance.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});await fs.writeFile(path.join(out,'failure.json'),JSON.stringify({error:String(error),checks,errors},null,2));throw error;}
  finally{await browser.close();}
})();
