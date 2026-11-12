(() => {
  const words={not_configured:"未配置本地模型 / Not configured",verified:"已核验加载 / Verified and loaded",offline:"已关闭 / Offline",unavailable:"未响应 / Unavailable",unverified:"身份未核验 / Identity unverified"};
  const make=(tag,text)=>{const el=document.createElement(tag);el.textContent=text;return el};
  async function load(host){
    const pane=host.querySelector("[data-gm-content]"),button=host.querySelector("button");
    if(button.disabled)return;
    button.disabled=true;pane.replaceChildren(make("p","正在核对文件和本机推理服务 / Checking artifacts and runtime…"));
    try{
      const headers={},token=sessionStorage.getItem("xiaoyi_access_token");if(token)headers.Authorization="Bearer "+token;
      const response=await fetch("/api/harness/open-models/gullmate-14b",{headers,cache:"no-store"});
      if(!response.ok)throw Error("HTTP "+response.status);
      const r=await response.json(),live=r.live;
      const configuration=make("p","部署所选 / Selected profile · "+(r.selected||"—")+" · "+(r.selected_alias||"—")+
        " · "+(r.selection_verified?"配置已核验 / Verified configuration":"配置待核验 / Unverified configuration"));
      const status=make("p","推理进程 / Inference process · "+words[live.state]+" · "+(live.observed||"—"));
      status.dataset.gmLive=live.state;configuration.dataset.gmSelected=r.selected||"";
      pane.replaceChildren(configuration,status,make("p","网关所指模型 / Gateway model · "+r.gateway));
      if(live.weight_sha){
        const hash=make("p","已加载底座 / Loaded base · "+live.weight_sha+" · "+live.n_ctx+" tokens · LoRA "+(live.adapter_sha||"未装载 / None"));
        hash.style.overflowWrap="anywhere";pane.append(hash);
      }
      const list=make("div","");pane.append(list);
      for(const item of r.items){
        const details=make("details",""),summary=make("summary",item.label);
        details.dataset.gmWeight=item.id;const file=make("p",(item.verified?"文件 SHA-256 已核验 / Verified":"文件未通过核验 / Unverified")+" · "+item.sha256);
        file.style.overflowWrap="anywhere";details.append(summary,file,make("p",item.test),make("p","准入 / Admission · "+item.gate));
        if(item.report_url){const link=make("a",item.report_title+" ↗");link.href=item.report_url;link.target="_blank";link.rel="noopener noreferrer";details.append(link)}
        list.append(details);
      }
    }catch(e){pane.replaceChildren(make("p","模型登记未能读取 / Cannot read inventory · "+e.message))}
    finally{button.disabled=false}
  }
  document.addEventListener("toggle",e=>{const box=e.target;if(box.matches?.("details[data-gm-catalog]")&&box.open&&!box.dataset.loaded){box.dataset.loaded="1";load(box)}},true);
  document.addEventListener("click",e=>{const b=e.target.closest?.("[data-gm-refresh]");if(b)load(b.closest("[data-gm-catalog]"))});
})();
