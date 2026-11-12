(() => {
  const host=document.querySelector("#trainingJobDetail");
  if(!host)return;
  const form=host.querySelector("form"),input=form.elements.run,choices=host.querySelector("datalist");
  const status=host.querySelector("[data-job-status]"),body=host.querySelector("[data-job-body]");
  const retry=host.querySelector("[data-job-retry]"),test=host.querySelector("[data-job-test]");
  let selected=null,revision=0,busy=false;
  const make=(tag,text)=>{const el=document.createElement(tag);el.textContent=text;return el};
  async function request(path,method="GET",payload){
    const headers={},token=sessionStorage.getItem("xiaoyi_access_token");if(token)headers.Authorization="Bearer "+token;
    if(payload)headers["Content-Type"]="application/json";
    const response=await fetch("/api/rl-lab/runs"+path,{method,headers,body:payload?JSON.stringify(payload):undefined,cache:"no-store"});
    const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"HTTP "+response.status);return data;
  }
  function reset(){
    selected=null;revision++;body.replaceChildren();status.textContent="";
    retry.hidden=test.hidden=true;
  }
  function render(job,result){
    const cfg=job.config,split=job.dataset.split;
    status.textContent=job.run_id+" · "+job.status+" · "+job.completed_training_episodes+"/"+job.total_training_episodes+" 回合 / episodes";
    body.append(make("p",cfg.dataset_id+" · seed "+cfg.seed+" · "+cfg.episodes+" 回合/算法 × "+cfg.horizon_steps+" 步 · 训练/验证/测试 "+[split.train_rows,split.validation_rows,split.test_rows].join(" / ")));
    if(job.error)body.append(make("p",job.error));
    for(const r of job.recoveries||[]){
      body.append(make("p","恢复 / Retry "+r.attempt+" · "+r.previous_status+" · 已保留 "+r.retained_episodes+" 回合 · "+(Object.keys(r.retained).join(", ")||"无完整算法检查点")));
    }
    const table=make("table",""),row=table.createTHead().insertRow();
    ["算法 / Policy","验证得分 / Validation","留出得分 / Held out","权重或规则 SHA-256 / Artifact"].forEach(t=>row.append(make("th",t)));
    const tb=table.createTBody(),wrap=make("div","");wrap.className="tp-scroll";
    for(const id of cfg.algorithms){
      const entry=job.training.algorithms[id],v=job.validation.results.find(x=>x.algorithm_id===id),t=result?.results.find(x=>x.algorithm_id===id);
      const tr=tb.insertRow();[id,v?.metrics.score??"—",t?.metrics.score??"—",entry?.artifact_sha256||"—"].forEach(text=>tr.append(make("td",String(text))));
    }
    wrap.append(table);body.append(wrap);
    if(result){
      const note=make("p","留出测试 / Held-out · "+result.evaluation_id+" · 最高得分 / Best score · "+result.best_algorithm_id+" · SHA-256 "+job.test_evaluation.artifact_sha256);
      note.style.overflowWrap="anywhere";body.append(note);
      if(result.environment_type==="port_operations" && result.results.length && result.results.every(r=>Array.isArray(r.frames)))body.append(trainingTrace(result));
    }
    retry.hidden=!["interrupted","failed"].includes(job.status);test.hidden=job.status!=="trained";
  }
  async function open(){
    reset();const id=input.value.trim(),rev=revision;
    if(!id)return;status.textContent="读取作业 / Loading…";
    try{
      const path="/"+encodeURIComponent(id),job=await request(path);
      const result=job.test_evaluation?await request(path+"/test-result"):null;
      if(revision!==rev)return;selected=job;render(job,result);
    }catch(e){if(revision===rev)status.textContent=e.message}
  }
  async function action(kind){
    if(!selected||busy)return;
    const job=selected,rev=revision;busy=true;retry.disabled=test.disabled=true;
    try{
      const payload=kind==="retry"?{expected_attempt:(job.recoveries||[]).length}:{};
      await request("/"+encodeURIComponent(job.run_id)+"/"+kind,"POST",payload);
      if(revision===rev)await open();
    }catch(e){if(revision===rev)status.textContent=e.message}
    finally{busy=false;retry.disabled=test.disabled=false}
  }
  form.addEventListener("submit",e=>{e.preventDefault();open()});input.addEventListener("input",reset);
  retry.addEventListener("click",()=>action("retry"));test.addEventListener("click",()=>action("evaluate"));
  host.addEventListener("toggle",async e=>{
    if(e.target!==host||!host.open)return;
    const rev=revision;
    try{const r=await request("?limit=10");
      choices.replaceChildren(...r.items.map(x=>new Option(x.status+" · "+x.config.dataset_id,x.run_id)));
      if(rev===revision&&!input.value&&r.items.length){input.value=r.items[0].run_id;await open()}
    }catch(e){if(rev===revision)status.textContent=e.message}
  });
})();
