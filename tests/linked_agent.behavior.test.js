"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const test = require("node:test");
const { randomUUID } = require("node:crypto");

const source = fs.readFileSync(require.resolve("../web/linked_agent.js"), "utf8");
const decode = text => text.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&amp;/g,"&");
const escapeHtml = text => String(text ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const deferred = () => {let resolve, reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const catalog={actions:[{id:"energy.compare",label:"能碳试算",parameters:{carbon:{type:"number",default:100,minimum:0,maximum:1000}}},{id:"port.adjust",label:"港口调整",mutates:true,parameters:{power:{type:"integer",default:50,minimum:1,maximum:100}}}]};
const prepared = (id="plan-one") => ({id,action_id:"energy.compare",label:"能碳试算",target:"energy",parameters:{carbon:100},samples:3,interval_seconds:2,before:{config:{},source:"test",observed_at:"test"},plan_sha256:"a".repeat(64),mutates:false});
const receipt = (plan,status="completed") => ({id:"run-one",status,plan,observations:[],changes:[],comparison_notice:"模拟观测"});

// Minimal DOM surface used by the console: HTML-created controls, delegated events,
// native numeric validity and replacing a modal. It does not emulate API behavior.
function harness(handler=async () => ({})) {
  const nodes=[], listeners={}, scrolls=[]; let opened=false;
  class Element {
    constructor(tag="div",attrs={},parent=null) {this.tag=tag;this.attrs=attrs;this.parent=parent;this.disabled="disabled" in attrs;this.checked="checked" in attrs;this.value=attrs.value || "";this._html="";nodes.push(this);}
    get id(){return this.attrs.id;}
    get type(){return this.attrs.type || this.tag;}
    get dataset(){return Object.fromEntries(Object.entries(this.attrs).filter(([k])=>k.startsWith("data-")).map(([k,v])=>[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),v]));}
    hasAttribute(name){return name in this.attrs;}
    matches(selector){return selector.split(",").some(part=>{part=part.trim();if(part.startsWith("#"))return this.id===part.slice(1);const match=part.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);return Boolean(match && this.hasAttribute(match[1]) && (match[2]==null || this.attrs[match[1]]===match[2]));});}
    closest(selector){return this.matches(selector) ? this : this.parent?.closest(selector);}
    get innerHTML(){return this._html;}
    set innerHTML(html){
      this._html=String(html);
      for(let i=nodes.length-1;i>=0;i--) {let parent=nodes[i].parent;while(parent && parent!==this)parent=parent.parent;if(parent===this)nodes.splice(i,1);}
      const stack=[this];
      for(const token of this._html.matchAll(/<\/?([\w-]+)\b([^>]*)>/g)) {
        const tag=token[1];
        if(token[0].startsWith("</")) {if(stack.at(-1).tag===tag)stack.pop();continue;}
        const attrs={};for(const attribute of token[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g))attrs[attribute[1]]=decode(attribute[2] ?? "");
        const node=new Element(tag,attrs,stack.at(-1));
        if(tag==="option" && (node.hasAttribute("selected") || !node.parent.value))node.parent.value=node.value;
        if(!["input","br","img","path","polyline"].includes(tag))stack.push(node);
      }
    }
    set textContent(value){this.innerHTML=escapeHtml(value);}
    get textContent(){return this.innerHTML.replace(/<[^>]*>/g,"");}
    checkValidity(){if(this.type!=="number")return true;const n=Number(this.value);return Number.isFinite(n) && (!this.attrs.min || n>=Number(this.attrs.min)) && (!this.attrs.max || n<=Number(this.attrs.max)) && (this.attrs.step==="any" || Number.isInteger(n));}
    reportValidity(){this.validityReported=true;}
    scrollIntoView(options){scrolls.push({id:this.id,...options});}
  }
  const root=new Element("div",{id:"modalBody"});
  const document={querySelector:selector=>nodes.find(n=>n.matches(selector)) || null,querySelectorAll:selector=>nodes.filter(n=>n.matches(selector)),addEventListener:(type,callback)=>{(listeners[type] ||= []).push(callback);}};
  const toasts=[], calls=[];
  const context={window:{},document,crypto:{randomUUID},CSS:{escape:x=>x},setTimeout:callback=>{queueMicrotask(callback);return 1;},Blob,URL};
  vm.runInNewContext(source,context);
  const agent=context.window.createLinkedAgent({api:async (path,options)=>{calls.push({path,options});return path==="/api/linked-agent/catalog" ? handler(path,options) ?? catalog : handler(path,options);},openModal:()=>{opened=true;root.innerHTML="Loading";},escapeHtml,toast:(...args)=>toasts.push(args),isOpen:()=>opened});
  const dispatch=async (type,element)=>{assert.ok(element,`missing ${type} target`);for(const callback of listeners[type] || [])await callback({target:element});};
  return {agent,root,document,toasts,calls,scrolls,close:()=>{opened=false;root.innerHTML="Other modal";},click:selector=>dispatch("click",document.querySelector(selector)),edit:async(selector,value)=>{const input=document.querySelector(selector);if(input.type==="checkbox")input.checked=value;else input.value=String(value);await dispatch("input",input);},change:async(selector,value)=>{const input=document.querySelector(selector);input.value=value;await dispatch("change",input);}};
}
const withCatalog=handler=>(path,options)=>path==="/api/linked-agent/catalog" ? catalog : handler(path,options);

test("catalog errors replace loading with a working retry control",async()=>{
  let first=true;const h=harness(()=>{if(first){first=false;throw new Error("offline");}return catalog;});
  await h.agent.open();assert.match(h.root.innerHTML,/offline/);
  await h.click("[data-la-reload]");assert.ok(h.document.querySelector("#laAction"));
});

test("closing during catalog or parsing never writes into a different modal",async()=>{
  const pending=deferred();const h=harness(()=>pending.promise);
  const opening=h.agent.open("调整碳价");h.close();pending.resolve(catalog);await opening;
  assert.equal(h.root.innerHTML,"Other modal");assert.equal(h.calls.length,1);
  const parseResult=deferred();const p=harness(withCatalog(()=>parseResult.promise));await p.agent.open();await p.edit("#laCommand","调整碳价");
  const parsing=p.click("[data-la-parse]");p.close();parseResult.resolve({action_id:"energy.compare",parameters:{carbon:200}});await parsing;
  assert.equal(p.root.innerHTML,"Other modal");assert.equal(p.toasts.length,0);
});

test("draft parameters, command, sampling and restore choice survive modal reopen",async()=>{
  const h=harness(withCatalog(()=>({})));await h.agent.open();await h.change("#laAction","port.adjust");
  await h.edit('[data-la-param="power"]',73);await h.edit("#laSamples",7);await h.edit("#laInterval",5);await h.edit("#laRestore",false);await h.edit("#laCommand","配置草稿");
  h.close();await h.agent.open();
  assert.equal(h.document.querySelector('[data-la-param="power"]').value,"73");assert.equal(h.document.querySelector("#laSamples").value,"7");assert.equal(h.document.querySelector("#laInterval").value,"5");assert.equal(h.document.querySelector("#laRestore").checked,false);assert.equal(h.document.querySelector("#laCommand").value,"配置草稿");
});

test("editing parameters while preview is pending prevents executing the stale plan",async()=>{
  const pending=deferred();const h=harness(withCatalog(()=>pending.promise));await h.agent.open();
  const preview=h.click("[data-la-preview]");await h.edit('[data-la-param="carbon"]',222);pending.resolve(prepared());await preview;
  assert.equal(h.document.querySelector("[data-la-execute]"),null);assert.match(h.document.querySelector("#laPlan").textContent,/重新预览/);
});

test("editing a command during parsing keeps the newer input and parameters",async()=>{
  const pending=deferred();const h=harness(withCatalog(()=>pending.promise));await h.agent.open();await h.edit("#laCommand","old request");
  const parsing=h.click("[data-la-parse]");await h.edit("#laCommand","new request");await h.edit('[data-la-param="carbon"]',333);
  pending.resolve({action_id:"energy.compare",parameters:{carbon:200}});await parsing;
  assert.equal(h.document.querySelector("#laCommand").value,"new request");assert.equal(h.document.querySelector('[data-la-param="carbon"]').value,"333");
});

test("blank numeric fields are rejected before creating any plan",async()=>{
  const h=harness(withCatalog(()=>prepared()));await h.agent.open();await h.edit('[data-la-param="carbon"]',"");await h.click("[data-la-preview]");
  assert.equal(h.calls.filter(c=>c.path==="/api/linked-agent/plans").length,0);assert.match(h.toasts.at(-1)[1],/完整参数/);
});

test("an uncertain execution POST reuses request identity on retry",async()=>{
  const plan=prepared();let attempts=0;const h=harness(withCatalog(path=>{if(path.includes("/execute")){if(++attempts===1)throw new Error("connection lost");return receipt(plan);}return {};}));
  await assert.rejects(h.agent.runPlan(plan),/connection lost/);await h.agent.runPlan(plan);
  const requests=h.calls.filter(c=>c.path.includes("/execute")).map(c=>JSON.parse(c.options.body).request_id);
  assert.equal(requests.length,2);assert.equal(requests[0],requests[1]);
});

test("poll failure retains the running receipt and prevents duplicate execution until refreshed",async()=>{
  const plan=prepared();let recover=false;const h=harness(withCatalog(path=>{if(path.includes("/execute"))return receipt(plan,"running");if(path.includes("/runs/")){if(!recover)throw new Error("poll offline");return receipt(plan);}return {};}));await h.agent.open();
  await assert.rejects(h.agent.runPlan(plan),/poll offline/);assert.equal(h.document.querySelector("[data-la-preview]").disabled,true);
  await assert.rejects(h.agent.runPlan(plan),/刷新回执/);assert.equal(h.calls.filter(c=>c.path.includes("/execute")).length,1);
  recover=true;await h.click("[data-la-refresh]");assert.equal(h.document.querySelector("[data-la-preview]").disabled,false);
});

test("an executing job keeps controls locked after closing and reopening",async()=>{
  const plan=prepared(),pending=deferred();const h=harness(withCatalog(path=>path.includes("/execute") ? receipt(plan,"running") : pending.promise));await h.agent.open();
  const execution=h.agent.runPlan(plan);await Promise.resolve();await Promise.resolve();h.close();await h.agent.open();
  assert.equal(h.document.querySelector("[data-la-preview]").disabled,true);assert.equal(h.document.querySelector("#laCommand").disabled,true);
  await assert.rejects(h.agent.runPlan(plan),/等待当前操作结束/);pending.resolve(receipt(plan));await execution;
  assert.equal(h.document.querySelector("[data-la-preview]").disabled,false);
});

test("a slow running refresh cannot replace a newer completed receipt",async()=>{
  const plan=prepared(),pending=deferred();const h=harness(withCatalog(()=>pending.promise));await h.agent.open();h.agent.showRun(receipt(plan,"running"));
  const refreshing=h.click("[data-la-refresh]");h.agent.showRun(receipt(plan));pending.resolve(receipt(plan,"running"));await refreshing;
  assert.match(h.document.querySelector("#laReceipt").innerHTML,/已完成/);assert.equal(h.document.querySelector("[data-la-preview]").disabled,false);
});

test("receipt is revealed at execution start and completion, without scrolling for every poll",async()=>{
  const plan=prepared();let polls=0;const h=harness(withCatalog(path=>path.includes("/execute") ? receipt(plan,"running") : receipt(plan,++polls<3 ? "running" : "completed")));
  await h.agent.open();await h.agent.runPlan(plan);
  assert.equal(polls,3);assert.equal(h.scrolls.length,2);assert.ok(h.scrolls.every(item=>item.id==="laReceipt" && item.block==="start" && item.behavior==="smooth"));
});

test("a cancellation that is no longer pending does not report accepted cancellation",async()=>{
  const plan=prepared();const h=harness(withCatalog(path=>path.endsWith("/cancel") ? {cancellation_requested:false} : receipt(plan)));await h.agent.open();h.agent.showRun(receipt(plan,"running"));
  await h.click("[data-la-cancel]");assert.equal(h.toasts.at(-1)[0],"当前任务已不在观测中");
  assert.match(h.document.querySelector("#laReceipt").innerHTML,/已完成/);
});

test("history response after modal replacement cannot overwrite another dialog",async()=>{
  const pending=deferred();const h=harness(withCatalog(()=>pending.promise));await h.agent.open();
  const history=h.click("[data-la-history]");h.close();pending.resolve({items:[]});await history;
  assert.equal(h.root.innerHTML,"Other modal");assert.equal(h.toasts.length,0);
});

test("unapplied failed mutations are never summarized as retained target configuration",()=>{
  const h=harness();const result=receipt({...prepared(),mutates:true},"failed");
  const summary=h.agent.summarize(result);assert.match(summary,/未变更目标配置/);assert.doesNotMatch(summary,/目标保留本轮配置/);
});
