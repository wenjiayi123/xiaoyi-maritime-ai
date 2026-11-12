function trainingTrace(report) {
  const panel=document.createElement("details");
  panel.innerHTML='<summary>逐步对比受训策略和基准 / Compare policies step by step</summary><div class="training-trace-controls"><label>策略 / Policy <select data-a></select></label> <label>对照 / Baseline <select data-b></select></label> <label>测试回合 / Episode <select data-episode></select></label></div><p><label>时刻 / Step <input type="range" min="0" value="0" data-step></label></p><p data-time></p><div class="tp-scroll"><table><thead><tr><th>策略</th><th>动作</th><th>服务量（模型单位）</th><th>积压量（模型单位）</th><th>约束违规</th></tr></thead><tbody></tbody></table></div>';
  const a=panel.querySelector("[data-a]"),b=panel.querySelector("[data-b]"),episode=panel.querySelector("[data-episode]"),bar=panel.querySelector("[data-step]");
  for(const policy of report.results){
    for(const s of [a,b])s.add(new Option(policy.algorithm_id,policy.algorithm_id));
  }
  a.value=report.results.find(x=>!["pid","sop_rule"].includes(x.algorithm_id))?.algorithm_id||a.value;
  b.value=report.results.some(x=>x.algorithm_id==="pid")?"pid":b.value;
  const selected=s=>report.results.find(x=>x.algorithm_id===s.value);
  function episodes(){
    const before=episode.value,valid=new Set(selected(b).frames.map(x=>x.evaluation_episode));
    const choices=[...new Set(selected(a).frames.map(x=>x.evaluation_episode))].filter(x=>valid.has(x));
    episode.replaceChildren(...choices.map(x=>new Option(x,String(x))));
    if(choices.includes(Number(before)))episode.value=before;
  }
  function draw(){
    const list=s=>selected(s).frames.filter(x=>x.evaluation_episode===Number(episode.value));
    const rhs=new Map(list(b).map(x=>[JSON.stringify([x.timestamp,x.step]),x]));
    const pairs=list(a).map(x=>[x,rhs.get(JSON.stringify([x.timestamp,x.step]))]).filter(p=>p[1]);
    bar.max=String(Math.max(0,pairs.length-1));bar.disabled=!pairs.length;
    const frame=pairs[Number(bar.value)],tbody=panel.querySelector("tbody"),caption=panel.querySelector("[data-time]");
    tbody.replaceChildren();if(!frame){caption.textContent="没有同一时刻的轨迹 / No matching frames";return;}
    caption.textContent=frame[0].timestamp+" · "+frame[0].step+" / "+pairs.length;
    for(const [i,f] of frame.entries()){
      const row=tbody.insertRow(),name=[a,b][i].value;
      for(const v of [name,f.action_label??f.action,f.served_units??"—",f.backlog_units??"—",f.constraint_violation===undefined?"—":f.constraint_violation?"是":"否"]){
        row.insertCell().textContent=String(v);
      }
    }
  }
  for(const s of [a,b])s.onchange=()=>{episodes();draw()};
  episode.onchange=()=>{bar.value=0;draw()};bar.oninput=draw;
  episodes();draw();return panel;
}
