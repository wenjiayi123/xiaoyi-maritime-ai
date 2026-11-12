(() => {
  const host=document.getElementById("throughputComparison");
  if(!host)return;
  const form=host.querySelector("form"),controls=form.elements,out=host.querySelector("[data-tp-result]");
  const status=host.querySelector("[data-tp-status]"),download=host.querySelector("[data-tp-download]");
  const submit=form.querySelector("[type=submit]"),endpoint="/api/analytics/throughput";
  let catalog=null,loading=false,revision=0,displayed=null,downloading=false;
  const create=(name,text)=>{const el=document.createElement(name);el.textContent=text;return el};
  async function fetchLocal(path){
    const headers={};const token=sessionStorage.getItem("xiaoyi_access_token");
    if(token)headers.Authorization="Bearer "+token;
    const response=await fetch(endpoint+path,{headers,cache:"no-store"});
    if(!response.ok){let body;try{body=await response.json()}catch{}throw Error(body?.detail||String(response.status))}
    return response;
  }
  function move(month,offset){
    const [y,m]=month.split("-").map(Number),n=y*12+m-1+offset;
    return Math.floor(n/12)+"-"+String(n%12+1).padStart(2,"0");
  }
  function reset(){
    revision++;displayed=null;download.disabled=true;out.replaceChildren();status.textContent="";
  }
  function periods(){
    const all=catalog.ports[controls.port.value].periods,known=new Set(all),length=Number(controls.months.value);
    const complete=all.filter(month=>Array.from({length:length/2},(_,k)=>known.has(move(month,2*k))).every(Boolean));
    const latest=complete.at(-1),previous=move(latest,-12);
    for(const key of ["base","current"]){
      const select=controls[key];select.replaceChildren(...complete.map(month=>new Option(month,month)));
      select.value=(key==="current"||!complete.includes(previous))?latest:previous;
    }
  }
  function table(headers,rows){
    const div=create("div","");div.className="tp-scroll";const t=create("table",""),tr=t.createTHead().insertRow();
    headers.forEach(h=>tr.append(create("th",h)));const body=t.createTBody();
    for(const row of rows){const r=body.insertRow();row.forEach(v=>r.append(create("td",v)))}
    div.append(t);return div;
  }
  const numbers=v=>Number(v).toLocaleString("en-US",{maximumFractionDigits:4});
  function render(r){
    const unit=r.unit==="TEU"?"TEU":"万 TEU / 10,000 TEU";
    const rows=[["基期 / Base",r.base.start+" → "+r.base.end,numbers(r.base.display)],["对比 / Current",r.current.start+" → "+r.current.end,numbers(r.current.display)],["差额 / Change",r.percent===null?"—":r.percent+"%",numbers(r.delta)]];
    out.replaceChildren(table(["口径 / Measure","区间或变化率 / Period or change",unit],rows));
    if(r.overlap)out.append(create("p","两个窗口有重叠 / Comparison windows overlap."));
    const details=create("details",""),summary=create("summary","分期与来源 / Periods and sources");
    const note=r.port==="singapore"?"MPA 月度数以千 TEU 发布，合并两个自然月。 / MPA monthly observations are in thousands of TEU.":"交通运输部沿海港口累计数以万 TEU 发布，按同年累计差计算双月。 / Two-month volumes are derived from cumulative coastal-port totals.";
    details.append(summary,create("p",note));
    for(const [key,label] of [["base","基期 / Base"],["current","对比 / Current"]]){
      for(const row of r[key].rows){
        const line=create("p",label+" · "+row.start+" → "+row.end+" · "+numbers(row.teu)+" TEU ");
        for(const source of row.sources){
          const link=create("a",source.period+" ↗");link.href=source.download;link.target="_blank";link.rel="noopener noreferrer";
          line.append(link,document.createTextNode(" "));
        }
        details.append(line);
      }
    }
    out.append(details);status.textContent="资料快照 / Source snapshot · "+r.snapshot;download.disabled=false;
  }
  async function compare(){
    reset();const id=revision,params=new URLSearchParams(new FormData(form));status.textContent="正在核对 / Comparing…";
    try{const r=await(await fetchLocal("/compare?"+params)).json();if(id!==revision)return;
      displayed={params,r};render(r);
    }catch(e){if(id===revision)status.textContent="无法比较 / Cannot compare · "+e.message}
  }
  host.addEventListener("toggle",async e=>{
    if(e.target!==host||!host.open||catalog||loading)return;
    loading=true;
    try{catalog=await(await fetchLocal("/catalog")).json();periods();submit.disabled=false;await compare()}
    catch(e){status.textContent="读取失败，重新展开可重试 / Reopen to retry · "+e.message}
    finally{loading=false}
  });
  form.addEventListener("change",e=>{reset();if(catalog&&["port","months"].includes(e.target.name))periods();status.textContent="请选择比较 / Select Compare."});
  form.addEventListener("submit",e=>{e.preventDefault();if(catalog)compare()});
  download.addEventListener("click",async()=>{
    if(!displayed||downloading)return;
    const active=displayed,id=revision;downloading=true;download.disabled=true;
    try{
      const params=new URLSearchParams(active.params);params.set("comparison_sha",active.r.comparison_sha);
      const res=await fetchLocal("/download?"+params);
      if(res.headers.get("X-Comparison-SHA256")!==active.r.comparison_sha)throw Error("Comparison checksum mismatch");
      const blob=await res.blob();if(id!==revision)return;
      const url=URL.createObjectURL(blob),a=create("a","");
      a.href=url;a.download=`throughput-${active.r.port}-${active.r.base.start}-${active.r.current.start}-${active.r.months}m-${active.r.unit}.csv`;
      document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);
    }catch(e){if(id===revision)status.textContent="下载失败 / Download failed · "+e.message}
    finally{downloading=false;if(id===revision)download.disabled=!displayed}
  });
})();
