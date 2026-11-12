(() => {
  const labels={llm:"14B 推理 / LLM",embedding:"向量检索 / Embeddings",twin:"TwinLab", "carbon-api":"能碳后端 / Carbon API",carbon:"能碳界面 / Carbon UI",
    strait:"海峡态势 / Strait",mobile:"Flutter Web","ais-lab":"AIS 实验室",xiaoyi:"小鸥主站 / GullMate",policy:"路径策略 / Routing","agent-rl":"Agentic RL",portfolio:"研究门户 / Portfolio",ship:"Godot 航行仿真"};
  const states={ready:"健康接口就绪 / Endpoint ready",offline:"已关闭 / Offline",unmanaged:"端口由其他进程占用 / Unmanaged listener",unresponsive:"进程在运行，健康检查未通过 / Process up, probe failed",process_only:"进程在运行 / Process only"};
  const make=(tag,value)=>{const el=document.createElement(tag);el.textContent=value;return el};
  window.mountSystemComponents=function(host){
    if(!host)return;
    const stamp=host.querySelector("[data-runtime-time]"),output=host.querySelector("[data-runtime-body]"),refresh=host.querySelector("button");
    const badge=document.querySelector("#modalBody [data-model-runtime]");let timer=null,busy=false;
    function schedule(){clearTimeout(timer);if(host.isConnected)timer=setTimeout(check,15000)}
    async function check(){
      if(!host.isConnected||busy)return;
      if(document.hidden){schedule();return;}
      busy=true;refresh.disabled=true;
      try{
        const token=sessionStorage.getItem("xiaoyi_access_token"),headers=token?{Authorization:"Bearer "+token}:{};
        const res=await fetch("/api/system/components",{cache:"no-store",headers});if(!res.ok)throw Error("HTTP "+res.status);
        const value=await res.json();if(!host.isConnected)return;
        output.replaceChildren();stamp.dataset.checkedAt=value.checked_at;
        if(value.state!=="checked")throw Error("受管服务清单不可用 / Manager unavailable");
        stamp.textContent=value.checked_at+(value.scope==="application"?" · 当前应用 / This deployment":"")+" · "+value.ready_http_services+" / "+value.http_service_count+" 健康接口就绪 / Endpoints ready";
        const live=value.inference.state;
        badge.textContent=live==="not_configured"?"未配置本地推理 / NOT CONFIGURED":live==="verified"?"已核验 / MODEL VERIFIED":live==="offline"?"推理已关闭 / OFFLINE":"身份未核验 / UNVERIFIED";
        badge.dataset.live=live;badge.className=live==="verified"?"status-pill":"demo-badge";
        const table=make("table",""),head=table.createTHead().insertRow();
        for(const name of ["组件 / Component","端口 / Port","探测状态 / Probe"])head.append(make("th",name));
        const body=table.createTBody();
        for(const [name,item] of Object.entries(value.services)){
          const row=body.insertRow();row.dataset.component=name;row.dataset.state=item.state;
          for(const cell of [labels[name]||name,item.port??"—",states[item.state]||item.state])row.insertCell().textContent=cell;
        }
        output.append(table);
      }catch(e){
        if(host.isConnected){stamp.textContent=String(e.message);output.replaceChildren();badge.textContent="待核验 / UNVERIFIED";badge.dataset.live="unverified";badge.className="demo-badge"}
      }finally{busy=false;refresh.disabled=false;schedule()}
    }
    refresh.onclick=check;check();
  };
})();
