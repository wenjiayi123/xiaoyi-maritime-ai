const data=JSON.parse(document.getElementById("records").textContent);
const $=id=>document.getElementById(id);
let english=false;
if(location.protocol.startsWith("http")){
  let pref="auto";try{pref=localStorage.getItem("gullmate.navigation.language.v1")||"auto"}catch{}
  english=pref==="en"||(pref==="auto"&&(navigator.languages?.[0]||navigator.language||"zh").toLowerCase().startsWith("en"));
}
const t=(ch,en)=>english?en:ch;
const elem=(name,text)=>{const e=document.createElement(name);if(text!==undefined)e.textContent=text;return e};
function table(host,cols,rows) {
  const scroll=elem("div");scroll.className="scroll";
  const tbl=elem("table"),head=tbl.createTHead().insertRow(),body=tbl.createTBody();
  for(const col of cols)head.append(elem("th",col));
  for(const row of rows){const r=body.insertRow();for(const cell of row)r.append(elem("td",String(cell)))}
  scroll.append(tbl);host.append(scroll);
}
function section(id,name){const host=$(id);host.hidden=false;host.replaceChildren(elem("h2",name));return host}
function disclosure(host,label,text,kind="p"){const d=elem("details"),sum=elem("summary",label),value=elem(kind,text);if(kind==="code")value.className="hash";d.append(sum,value);host.append(d)}
const names=[["萨凡纳高等泊预警","Savannah queue alert"],["美国等泊前瞻","U.S. queue forecast"],["岸电储能费用优先","Shore power cost policy"]];
const statuses=[["拒绝自动预警","Automatic alerts declined"],["等待官方实绩","Awaiting official observation"],["沙箱已回滚，新候选评估未通过","Sandbox rolled back; candidate declined"]];
const roles={risk:["风险岗","Risk"],operations:["运营岗","Operations"],equipment:["设备岗","Equipment"]};
const actions={sign:["沙箱签注","Sandbox signature"],execute:["沙箱运行并结算","Sandbox execution and settlement"],submit_evaluation:["登记评估候选","Candidate queued"],rollback:["回滚沙箱状态","Sandbox rolled back"],finish_evaluation:["回写评估结论","Evaluation recorded"]};
function display(){
  const i=$("cases").selectedIndex,entry=data.cases[i];document.documentElement.lang=english?"en":"zh-CN";
  $("heading").textContent=t("自主决策工单","Decision work orders");$("choose").textContent=t("选择工单","Work order");
  $("language").textContent=t("English","中文");[...$("cases").options].forEach((v,j)=>v.textContent=t(...names[j])+" · "+data.cases[j].id);
  const overview=section("overview",t(...statuses[i]));overview.append(elem("p",t(...entry.description)),elem("small",entry.id));
  disclosure(overview,t("来源和取证时间","Source and evidence timestamp"),t(...entry.source));
  disclosure(overview,t("业务原件 SHA-256","Source SHA-256"),entry.business,"code");
  disclosure(overview,t("模型 SHA-256","Model SHA-256"),entry.model,"code");
  const rv=section("reviews",t("三个岗位的实际答复","Original model responses by role"));
  for(const r of entry.reviews){const d=elem("details");d.append(elem("summary",t(...roles[r.role])),elem("p",r.answer),elem("small",r.task_id+" · "+r.evidence_id));rv.append(d)}
  $("history").hidden=$("score").hidden=i!==2;
  if(i===2) {
    const h=section("history",t("隔离演练记录","Isolated sandbox exercise"));h.append(elem("p",t("账户为本机演练身份。时间为 UTC。","Accounts are local test identities. Times are UTC.")));
    const list=elem("ol");list.className="trace";
    for(const e of data.events){
      const row=elem("li"),details=elem("details");
      details.append(elem("summary",t(...actions[e.action])+" · "+e.actor+" · "+e.at),elem("p",e.reason));
      for(const [label,value] of [[t("方案","Proposal"),e.proposal_sha],[t("操作前状态","State before"),e.before_sha],[t("操作后状态","State after"),e.after_sha],
        [t("事件","Event"),e.sha],[t("沙箱当前调度","Active sandbox schedule"),e.schedule||t("无","None")]]){
        const line=elem("p",label+" · "),code=elem("code",value);code.className="hash";line.append(code);details.append(line);
      }
      const phase=elem("p",t("工单阶段","Work order state")+" · "+e.phase);phase.dataset.eventPhase=e.phase;
      details.append(phase);row.append(details);list.append(row);
    }
    h.append(list);disclosure(h,t("最终事件 SHA-256","Final event SHA-256"),data.events.at(-1).sha,"code");
    const s=section("score",t("账单与策略反馈","Settlement and policy feedback"));
    const metricRows=data.baselines.map(row=>[t(...row.label),...row.values.map(x=>x.toFixed(2))]);
    table(s,[t("6 月 29 日当周参照","Comparator, week of June 29"),t("省费（元）","Cost saved (CNY)"),t("少排（kg）","CO₂ reduced (kg)"),t("降峰（kW）","Peak reduced (kW)")],metricRows);
    s.append(elem("p",t("电价提前 3 小时。正数表示减少。与原训练策略相比，碳排增加 0.49 kg。","Tariff advanced by three hours. Positive means a reduction. Emissions rose by 0.49 kg against the original trained policy.")));
    s.append(elem("p",t("后续规则在 3 个其他自然周的 9 个工况周中试验。相对固定电价识别，平均多花 191.61 元、少排 12.65 kg、峰值高 16.44 kW。","The feedback rule was tested on nine scenario-weeks across three other calendar weeks. Against fixed tariff recognition it cost CNY 191.61 more, reduced CO₂ by 12.65 kg and raised peak demand by 16.44 kW on average.")));
    const d=elem("details");d.append(elem("summary",t("查看九次评估","Inspect nine evaluations")));table(d,[t("周起日","Week start"),t("工况","Scenario"),t("选择","Policy"),"CNY","kg","kW"],data.trials.map(v=>[v.target,v.scenario,v.selected,...v.values.map(x=>x.toFixed(2))]));s.append(d);
  }
  const real=section("real",t("实际到港反馈","Observed vessel arrivals"));
  const obs=data.observations;
  real.append(elem("p",t("芬兰四港的 "+obs.registered+" 个预签航次中，已有 "+obs.matched+" 个在签发后收到实际到港回执。","Of "+obs.registered+" pre-issued forecasts at four Finnish ports, "+obs.matched+" have matching arrival reports recorded after issue.")),
              elem("small",t("核对时刻","Checked at")+" "+obs.checked));
  const d=elem("details");d.append(elem("summary",t("逐航次实绩和误差","Arrival receipts and errors")));const blank=t("待回","Pending");
  table(d,[t("航次","Call"),t("港口","Port"),t("实际到港 UTC","Actual UTC"),t("预测绝对误差（分）","Forecast absolute error (min)"),t("船代申报绝对误差（分）","Declared ETA absolute error (min)")],obs.rows.map(r=>[r.call,r.port,r.actual||blank,r.actual?r.forecast_abs_error_min.toFixed(2):"—",r.actual?r.declared_abs_error_min.toFixed(2):"—"]));real.append(d);
  if(obs.matched){
    real.append(elem("p",t("当前已到港子集的平均绝对误差（分钟）","Mean absolute error on matched arrivals (minutes)")+" · "+t("研究预测","Forecast")+" "+obs.research_mae.toFixed(2)+" · "+t("船代申报","Declared ETA")+" "+obs.declaration_mae.toFixed(2)));
  }
  const original=elem("a",t("官方到港回执查询","Official arrival records"));original.href=obs.actual_feed_url;original.rel="noopener noreferrer";original.target="_blank";real.append(original);
  $("server").hidden=!location.protocol.startsWith("http");$("check").textContent=t("读取主站当前工单状态","Read current server state");$("live").textContent="";
}
for(const c of data.cases)$("cases").add(new Option(c.id,c.id));
$("cases").onchange=display;$("language").onclick=()=>{english=!english;display()};
$("check").onclick=async()=>{
  const id=$("cases").value;
  try{
    const u="/api/decision-cycles/"+encodeURIComponent(id)+(id===data.cases[2].id?"?scenario=phase_minus3":"");
    const token=sessionStorage.getItem("xiaoyi_access_token"),headers=token?{Authorization:"Bearer "+token}:{};
    const r=await fetch(u,{cache:"no-store",headers});if(!r.ok)throw Error(String(r.status));
    const j=await r.json();if(j.case_id!==id)throw Error("ID");
    if($("cases").value===id)$("live").textContent=t("当前主站状态","Current server state")+" · "+j.state.phase+" · "+t("日志事件","Events")+" "+j.events.length;
  }catch(e){if($("cases").value===id)$("live").textContent=t("读取失败","Read failed")+" · "+e.message}
};
display();
