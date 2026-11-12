
const data=JSON.parse(document.querySelector("#payload").textContent);
const $=s=>document.getElementById(s);
const time=n=>n==null?"待回执":new Date(n*60000).toISOString().slice(0,19).replace("T"," ");
const difference=(x,y)=>x==null||y==null?"待回执":(x-y).toFixed(2)+" 分钟";
function el(tag,text){const n=document.createElement(tag);n.textContent=text;return n}
function option(key,title){const n=el("option",title);n.value=key;return n}
for(const [k,title] of Object.entries(data.ports)) $("port").append(option(k,title));
let rows=[];
function showCall(){
 const i=$("call").selectedIndex,r=rows[i];$("facts").replaceChildren();
 $("prev").disabled=i<=0;$("next").disabled=i<0||i>=rows.length-1;if(!r)return;
 for(const [key,value] of [["航次编号",r[0]],["签发或回测时点",time(r[2])],["船代申报",time(r[3])],["研究策略预测",time(r[4])],
     ["实际到港",time(r[5])],["预测减实绩",difference(r[4],r[5])],["申报减实绩",difference(r[3],r[5])]]){
     $("facts").append(el("dt",key),el("dd",value));}
}
function refresh(){
 const p=$("period").value,site=$("port").value;rows=data.rows[p].filter(r=>r[1]===site);
 $("call").replaceChildren(...rows.map(r=>option(r[0],String(r[0]))));
 $("scope").textContent=p==="live"?"共封存 "+data.rows.live.length+" 个航次，最近核对截至 "+data.checked+"。本港已有 "+rows.filter(r=>r[5]!=null).length+" / "+rows.length+" 个到港回执。":"本港共 "+rows.length+" 个合格航次。回测时点为申报预计到港前六小时。";
 showCall();
 const wrap=$("score");wrap.replaceChildren();const tab=el("table","");tab.append(el("caption",data.ports[site]+" · 平均绝对误差（分钟）"));
 const header=el("tr","");["评估期","航次","研究策略","原申报"].forEach(n=>header.append(el("th",n)));tab.append(header);
 for(const k of ["apr_aug","october"]){const e=data.summary.eta[site+"|"+k];const tr=el("tr","");
 [k==="october"?"10 月":"4—8 月",e["实际航次数"],e["研究策略平均绝对误差_分钟"],e["船代原申报平均绝对误差_分钟"]].forEach(n=>tr.append(el("td",n)));tab.append(tr)}
 wrap.append(tab,el("p",data.deploy[site]==="declared"?"本机保留船代申报。":"本机采用按船舶、港口和时段拟合的修正。"));
 const k=p==="primary"?"apr_aug":"october",b=data.summary.berth[k];
 $("berths").textContent=b["评估期"]+"，四港共有 "+b["可核对作业时长的航次"]+" 个航次可复算。固定泊位方案平均等待 "+b["固定泊位方案平均模拟等待_分钟"]+" 分钟，修正 ETA 方案 "+b["修正ETA可择泊位方案平均模拟等待_分钟"]+" 分钟。历史筛选通过 "+b["通过历史筛选的泊位代码数"]+" / "+b["历史检查代码数"]+" 个泊位代码。";
}
for(const o of data.orders){const d=el("details","");d.append(el("summary",o.title),el("p",o.answer),el("small",o.id));$("orders").append(d)}
$("period").onchange=refresh;$("port").onchange=refresh;$("call").onchange=showCall;
$("prev").onclick=()=>{$("call").selectedIndex--;showCall()};$("next").onclick=()=>{$("call").selectedIndex++;showCall()};refresh();
