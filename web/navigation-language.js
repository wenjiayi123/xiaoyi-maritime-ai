(() => {
  const labels={
    chat:["智能对话","AI Dialogue","Chat"],decisions:["决策建议","Decision Advisory","Decisions"],
    analytics:["数据分析","Data Analytics","Analytics"],rl:["训练中心","Training Center","Training"],
    knowledge:["知识库","Knowledge Base","Library"],tasks:["任务中心","Action Center","Tasks"]
  };
  const key="gullmate.navigation.language.v1";
  const picker=document.getElementById("navLanguage");
  const navigation=document.querySelector(".top-nav");
  if(!picker||!navigation)return;
  const small=matchMedia("(max-width:620px)");
  try{
    const saved=localStorage.getItem(key);
    if(["auto","en","zh"].includes(saved))picker.value=saved;
  }catch{}
  function update(){
    const auto=picker.value==="auto";
    const en=picker.value==="en"||(auto&&(navigator.languages?.[0]||navigator.language||"zh").toLowerCase().startsWith("en"));
    const dual=auto&&!small.matches;
    navigation.setAttribute("aria-label",en?"Main navigation":"主导航");
    for(const button of navigation.querySelectorAll("button[data-view-target]")){
      const entry=labels[button.dataset.viewTarget];if(!entry)continue;
      const [zh,full,short]=entry,span=button.querySelector(":scope > span");
      const text=en?(small.matches?short:full):zh;
      const caption=dual?zh:text;
      span.setAttribute("data-no-bilingual","");span.lang=dual||!en?"zh-CN":"en";
      span.replaceChildren(document.createTextNode(caption));
      if(dual){const translation=document.createElement("small");translation.className="bi-english";translation.lang="en";translation.textContent=full;span.append(translation)}
      button.setAttribute("aria-label",en?full:zh);
      button.lang=en?"en":"zh-CN";button.title=en?full:zh;
    }
    const side=document.querySelector('[data-action="toggle-sidebar"]');
    if(side){side.setAttribute("aria-label",en?"Open tools and navigation settings":"打开功能侧栏和导航设置");side.lang=en?"en":"zh-CN"}
  }
  picker.addEventListener("change",()=>{try{localStorage.setItem(key,picker.value)}catch{}update()});
  small.addEventListener("change",update);
  window.addEventListener("languagechange",update);
  update();
})();
