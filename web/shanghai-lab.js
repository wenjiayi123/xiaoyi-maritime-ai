(() => {
  'use strict';
  const $ = id => document.getElementById(id), base = '/api/harness/shanghai';
  const names = {shared_snapshot:'统一输入校验',malacca_plan_and_resource_recheck:'沙盘排程与资源复核',energy_ledger_recheck:'能碳逐时守恒',port_execution_readback_and_restore:'执行读回与隔离状态恢复',failure:'未通过'};
  let result = null, briefing = null, delivery = null, catalog = null;
  const print = v => JSON.stringify(v, null, 2);
  function status(message, error = false) {$('status').textContent = message; $('status').dataset.error = String(error);}
  async function request(path, body) {
    const response = await fetch(base + path, {method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(55000),cache:'no-store'});
    const value = await response.json(); if(!response.ok) throw Error(value.detail || value.error || `HTTP ${response.status}`); return value;
  }
  function metric(label,value,unit,warning=false) {const box=document.createElement('div');box.className='metric'+(warning?' warn':'');for(const [tag,text] of [['span',label],['strong',value],['small',unit]]) {const el=document.createElement(tag);el.textContent=text;box.append(el);}return box;}
  function resetView(){ briefing=null;delivery=null;$('metrics').replaceChildren();$('mobile').hidden=true;$('refresh').disabled=true;$('export').disabled=true;$('briefing').textContent='等待本次已校验结果…';$('delivery').textContent='';$('receipt').textContent='尚无本次记录';$('comparison').textContent='尚无本次记录'; }
  async function render() {
    resetView();
    $('day').value=result.request.day; $('scenario').value=result.request.scenario; $('seed').value=String(result.request.seed);
    $('receipt').textContent=print({id:result.id,status:result.status,result_sha256:result.result_sha256,steps:result.steps.map(s=>({...s,label:names[s.step]})),execution:result.execution});
    $('comparison').textContent=print({planning:result.plan?.comparison,storage:result.energy?.comparison,scope:result.energy?.scope});
    if(result.status==='blocked') {$('briefing').textContent=result.request.scenario==='communications_loss'?'通信中断导致来源质量不满足运行条件，任务已停止。原始原因和失败步骤保留在校验回执中。':'本次试验未完成，请查看逐步校验记录定位原因。';$('export').disabled=false;status('前置条件未通过；失败记录已保留。',true);return;}
    [briefing,delivery] = await Promise.all([request(`/trials/${result.id}/briefing`),request(`/trials/${result.id}/delivery`)]);
    if(briefing.result_sha256!==result.result_sha256 || delivery.result_sha256!==result.result_sha256) throw Error('结果版本不一致，不能展示成功。');
    const e=result.energy, m=result.plan.metrics || result.steps.find(s=>s.step==='malacca_plan_and_resource_recheck').metrics;
    $('metrics').append(metric('完成工程作业量',String(result.summary.processed_teu),'TEU · 本试验'),metric('总等待',String(m.wait_vessel_hours),'船时 · 同一工单集合'),metric('储能费用变化',(-e.comparison.deltas.cost_saving_cny).toFixed(2),'元 · 相对同排程无储能方案'),metric('储能碳排变化',(e.comparison.deltas.carbon_change_kg>=0?'+':'')+e.comparison.deltas.carbon_change_kg.toFixed(2),'kgCO₂e · 能损影响保留',e.comparison.deltas.carbon_change_kg>0));
    $('briefing').textContent=briefing.text;
    $('mobile').href=`http://127.0.0.1:7357/?shanghai_trial=${result.id}`; $('mobile').hidden=false;
    $('refresh').disabled=false; $('export').disabled=false;
    $('delivery').textContent=`PortAI：${delivery.status==='acknowledged_lab'?'已签收并读回':delivery.status==='waiting_acknowledgement'?'岗位复核完成，等待签收':'等待岗位复核'} · 回执 ${delivery.events.length} 条 · 独立复核身份 ${delivery.distinct_reviewers} 个。`;
    status(`联动校验通过 · ${result.elapsed_seconds.toFixed(2)} 秒 · ${result.id}`);
  }
  $('trial-form').addEventListener('submit',async event=>{
    event.preventDefault();$('run').disabled=true;resetView();status('正在统一输入、排程、核算并核对执行回执…');
    const args={day:$('day').value,scenario:$('scenario').value,seed:Number($('seed').value)},signature=print(args);
    let pending;try {pending=JSON.parse(localStorage.getItem('shanghai-lab.pending'));}catch {pending=null;}
    if(!pending || pending.signature!==signature) pending={signature,body:{...args,request_id:'web-'+crypto.randomUUID()}};
    localStorage.setItem('shanghai-lab.pending',print(pending));
    try {result=await request('/trials',pending.body);localStorage.removeItem('shanghai-lab.pending');history.replaceState(null,'',`?trial=${result.id}`);await render();}
    catch(error) {status(error.message,true);$('request-note').textContent='若提交响应中断，保持参数不变再次运行会沿用原请求编号。';}
    finally {$('run').disabled=false;}
  });
  $('refresh').addEventListener('click',async()=>{try {result=await request(`/trials/${result.id}`);await render();}catch(e){status(e.message,true);}});
  $('export').addEventListener('click',()=>{const blob=new Blob([print({result,briefing,delivery,catalog})],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=result.id+'-evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  async function start(){try {catalog=await request('/catalog');$('contract').textContent=print(catalog.contract);$('assumptions').textContent=print(catalog.assumptions);for(const source of catalog.dataset.sources){const row=document.createElement('div');row.className='source';const link=document.createElement('a');link.textContent=source.id;link.href=source.url;link.target='_blank';link.rel='noopener';const note=document.createElement('small');note.textContent=`${source.scope} · ${source.evidence_class} · SHA256 ${source.sha256}`;row.append(link,note);$('sources').append(row);}status(`数据目录已校验：${catalog.daily_rows} 条港口日指标，${catalog.weather_hours} 小时再分析气象。`);const id=new URLSearchParams(location.search).get('trial');if(id&&/^sjt-[a-f0-9]{24}$/.test(id)){result=await request('/trials/'+id);await render();}}catch(e){status(e.message,true);}}
  start();
})();
