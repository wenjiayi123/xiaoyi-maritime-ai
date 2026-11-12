"use strict";
(async () => {
  const el = id => document.getElementById(id);
  const response = await fetch("/web/harness-credit-results.json");
  if (!response.ok) throw new Error("回执载入失败");
  const all = await response.json(); let data = all.fresh;
  const names = {parent:"续训前 · 相同观测", parent_raw:"续训前 · 原观测", candidate:"本轮 RL 续训", rules:"固定规则"};
  const outcomes = {verified_candidate_recommended:"推荐已核验的候选", no_registered_candidate_meets_requirements:"两项候选均未达到当前要求", evidence_gap_reported:"有证据缺口", awaiting_user_clarification:"追问并等待", incorrect_report:"错误报告", step_limit:"达到步数上限"};
  function node(tag,text,cls) {
    const n=document.createElement(tag);
    if (text!==undefined) n.textContent=text;
    if (cls) n.className=cls;
    return n;
  }
  function table(){el("scores").replaceChildren();for (const key of ["parent_raw","parent","candidate","rules"].filter(k=>k in data.arms)) {
    const s=data.arms[key].stats,tr=node("tr");
    [names[key],s.correct+"/8",s.recommend,s.wait,s.wrong,s.timeout,s.invalid].forEach(x=>tr.append(node("td",x)));
    el("scores").append(tr);
  }
  }
  const label=["第一项响应丢失","核验前收紧成本上限","两项均超预算","缺碳价，等待回复","第二项响应丢失","中途更新目标","收紧初始预算","缺碳价，随后收到补充"];
  label.forEach((name,i)=>{const opt=node("option",(i+1)+" · "+name);opt.value=i;el("case").append(opt);});
  function panel(where,rec) {
    const block=el(where);block.replaceChildren();
    block.append(node("p",outcomes[rec.outcome]+" · "+rec.steps.length+" 步 · "+rec.invalid+" 次无效调用"));
    const list=node("ol",undefined,"flow");
    rec.steps.forEach((s,i)=>{
      const li=node("li"),d=node("details"),sum=node("summary",(i+1)+". "+s.tool,s.error?"error":"");
      d.append(sum,node("div","目标版本 "+s.version+" · "+s.feedback,"detail"));
      if(s.event) d.append(node("div",s.event,"detail"));
      s.calls.forEach(c=>d.append(node("div",c,"detail mono")));
      if(s.fused) d.append(node("div","编排与 14B 合成得分 "+s.fused+"。14B 单独首选 "+s.raw,"detail mono"));
      if(s.scores) d.append(node("div","动作分 "+s.scores,"detail mono"));
      li.append(d);list.append(li);
    });
    block.append(list);
  }
  function render(){
    const i=Number(el("case").value), key=el("arm").value,t=data.tasks[i];
    el("lefttitle").textContent=names[key];el("terms").textContent=t;
    panel("left",data.arms[key].rows[i]);panel("right",data.arms.candidate.rows[i]);
  }
  el("scope").textContent=all.scope;
  el("weights").textContent=all.weights;
  for (const c of all.challenge) {
    const tr=node("tr");
    const fmt=v=>v.toLocaleString("zh-CN",{minimumFractionDigits:3,maximumFractionDigits:3});
    [c.order==="ordered"?"原顺序":"交换后",fmt(c.choices[0].cost),fmt(c.choices[1].cost),"候选"+(c.chosen+1),c.steps].forEach(v=>tr.append(node("td",v)));
    el("swap").append(tr);
  }
  function setStudy(){
    const fresh=el("set").value==="fresh"; data=all[el("set").value];
    names.parent=fresh?"同一 14B · 单独运行":"续训前 · 相同观测";
    names.candidate=fresh?"同一 14B + RL 编排":"本轮 14B 续训";
    el("righttitle").textContent=names.candidate;el("arm").replaceChildren();
    for(const k of ["parent","parent_raw","rules"].filter(k=>k in data.arms)){
      const opt=node("option",names[k]);opt.value=k;el("arm").append(opt);
    }
    table();render();
  }
  el("set").addEventListener("change",setStudy);setStudy();
  el("arm").addEventListener("change",render);el("case").addEventListener("change",render);render();
})().catch(e=>{document.getElementById("terms").textContent="读取实验数据失败。"+e.message;});
