window.mountOfferComparison = function mountOfferComparison(api) {
  const region = document.querySelector("#offer-workbench");
  if (!region) return;
  const form = region.querySelector("form");
  const rows = form.querySelector('[data-offer="rows"]');
  const output = form.querySelector('[data-offer="output"]');
  const submit = form.querySelector('[type="submit"]');
  const add = form.querySelector('[data-offer="add"]');
  let revision = 0;

  function invalidate() {
    revision++;
    output.textContent = "";
    submit.disabled = false;
  }
  function sync() {
    const berth = form.elements.profile.value === "berth";
    form.querySelector('[data-offer="demand"]').textContent = berth ? "船舶吃水（m）" : "所需功率（kW）";
    Array.from(rows.children).forEach((row,i) => {
      row.querySelector("legend").textContent = "候选 " + (i + 1);
      row.querySelector("[data-price]").textContent = berth ? "成本（元）" : "报价（元/kWh）";
      row.querySelector("[data-limit]").textContent = berth ? "允许吃水（m）" : "可供功率（kW）";
      row.querySelector("button").disabled = rows.childElementCount <= 2;
    });
    add.disabled = rows.childElementCount >= 16;
  }
  function addRow(data={}) {
    const row = document.createElement("fieldset");
    row.className = "offer-row";
    row.innerHTML = '<legend></legend><label>编号<input name="id" maxlength="32" required></label>'+
      '<label><span data-price></span><input type="number" step="any" min="0" name="price"></label>'+
      '<label>报价来源<input name="quote_ref" maxlength="96"></label>'+
      '<label><span data-limit></span><input type="number" step="any" min="0" name="limit"></label>'+
      '<label>约束核验<select name="assessment"><option value="unknown">按数值核对 / 待补</option><option value="pass">明确满足</option><option value="fail">明确不满足</option></select></label>'+
      '<label>核验来源<input name="check_ref" maxlength="96"></label>'+
      '<label>记录有效至<input name="valid_until" type="datetime-local"></label>'+
      '<button type="button">移除</button>';
    Object.entries(data).forEach(([k,v])=>{row.elements.namedItem(k).value=v;});
    row.querySelector("button").addEventListener("click",()=>{row.remove();invalidate();sync();});
    rows.append(row);
    sync();
  }
  function dateValue(value) { return value ? new Date(value).toISOString() : null; }
  function reset() {
    invalidate();
    rows.replaceChildren();
    form.elements.required.value="";
    form.elements.requirement_ref.value="";
    form.elements.as_of.value="";
    addRow();addRow();
  }
  form.elements.profile.addEventListener("change",reset);
  form.addEventListener("input",invalidate);
  add.addEventListener("click",()=>{invalidate();addRow();});
  form.querySelector('[data-offer="example"]').addEventListener("click",()=>{
    invalidate();rows.replaceChildren();
    const berth=form.elements.profile.value==="berth";
    form.elements.required.value=berth?"12":"1000";
    form.elements.requirement_ref.value=berth?"样例-船舶吃水":"样例-用电需求";
    form.elements.as_of.value="";
    const prices=berth?["830","910","940"]:["0.31","0.28","0.41"];
    const limits=berth?["11","12","13"]:["1200","800","1400"];
    prices.forEach((price,i)=>addRow({id:["A","B","C"][i],price,limit:limits[i],quote_ref:"样例-报价"+(i+1),check_ref:"样例-约束"+(i+1)}));
  });
  form.addEventListener("submit",async event=>{
    event.preventDefault();
    const request=++revision;
    submit.disabled=true;output.textContent="正在核对报价与约束…";
    try {
      const offers=Array.from(rows.children,row=>{
        const field=key=>row.elements.namedItem(key).value.trim() || null;
        return {id:field("id"), price:field("price"), quote_ref:field("quote_ref"),limit:field("limit"),
          check_ref:field("check_ref"),assessment:field("assessment"),valid_until:dateValue(field("valid_until"))};
      });
      const sheet={profile:form.elements.profile.value,required:form.elements.required.value || null,
        requirement_ref:form.elements.requirement_ref.value.trim() || null,as_of:dateValue(form.elements.as_of.value),offers};
      const result=await api("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:"请比较所附候选的最低可行报价。",offer_sheet:sheet,mode:"brief",session_id:"offer-workbench"})});
      if(request===revision) output.textContent=result.answer;
    } catch(error) {
      if(request===revision) output.textContent="比选失败，请核对候选编号、数值、来源及有效期。"+(error.message || "");
    } finally {if(request===revision) submit.disabled=false;}
  });
  reset();
};
