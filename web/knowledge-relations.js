// Join the current catalog to the registered editions. A category reference
// describes the collection; only a matched passage supports a factual answer.
export function buildSourceGraph(catalog, sources) {
  const documents = new Map(sources.map(source => [source.source_id, source]));
  const categories = new Map();
  const parents = new Map();
  for (const category of catalog.categories) {
    const ids = [...new Set(category.current_kb_files)];
    for (const id of ids) {
      if (!documents.has(id)) throw new Error("目录引用了未登记文件：" + id);
      if (!parents.has(id)) parents.set(id, []);
      parents.get(id).push(category.id);
    }
    categories.set(category.id, { ...category, ids });
  }
  return { documents, categories, parents };
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function option(value, title) {
  return new Option(title, value);
}

function linkToSource(raw) {
  if (!raw) return null;
  let url;
  try { url = new URL(raw, window.location.href); } catch { return null; }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
  const link = element("a", "查看登记出处");
  link.href = url.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function sourceDetails(source) {
  const panel = element("details");
  const title = source.display_name || source.source_id;
  panel.append(element("summary", title));
  panel.append(element("p", [source.institution, source.version,
    source.official ? "发布方来源" : "内部资料", source.content_scope].filter(Boolean).join(" · ")));
  panel.append(element("code", "文件 " + source.source_id + "　SHA-256 " + (source.document_checksum_sha256 || "缺失")));
  const link = linkToSource(source.source_url);
  if (link) panel.append(link);
  return panel;
}

export function locationTerms(text) {
  // Only shorten locator questions. Keep complete identifiers, jurisdictions
  // and dates; quantitative or operative provisions require the full question.
  if (!/出处|来源|发布|指南|题录|目录|哪里查|从哪里|官网|官方/.test(text) ||
      /多少|限值|罚款|豁免|有效期|第.{1,6}条|是否|例外|同时|以及/.test(text)) return null;
  const ids = text.match(/\b[A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)*\b/g) || [];
  const places = text.match(/新加坡港?|中国|马来西亚|美国|欧盟|英国|澳大利亚|日本/g) || [];
  const dates = text.match(/\d{4}(?:[-/.年]\d{1,2}(?:[-/.月]\d{1,2})?)?/g) || [];
  const subject = text.split(/的|所在|由谁|在哪里|从哪里|哪里查/)[0].trim();
  const words = ids.length ? [...places, ...ids, ...dates] : [subject, ...dates];
  const moreSpecific = [...new Set(words)].join(" ").trim();
  return moreSpecific.length >= 2 && moreSpecific !== text ? moreSpecific : null;
}

export async function findSourcePassage(api, query, filters, excluded, registry) {
  const search = text => api("/api/knowledge/search", { method:"POST", headers:{"Content-Type":"application/json"},
    body:JSON.stringify({ query:text, top_k:8, ...filters }) });
  const first = await search(query);
  const codes = query.match(/\b[A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)*\b/g) || [];
  function select(hits) {
    const eligible = hits.filter(hit => hit.qualified && hit.source !== excluded);
    if (!filters.official_only || !codes.length || !registry) return eligible[0];
    // An instrument's own registered publication precedes a different
    // publication which only mentions it. Keep retrieval order for ties.
    function titleMatches(hit) {
      const title = (registry.get(hit.source)?.display_name || "").toUpperCase();
      const titleCodes = new Set(title.match(/[A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)*/g) || []);
      return codes.filter(code => titleCodes.has(code)).length;
    }
    return eligible.sort((a,b)=>titleMatches(b)-titleMatches(a))[0];
  }
  const direct = select(first.hits);
  if (direct || !filters.official_only) return {hit:direct};
  const terms = locationTerms(query);
  if (!terms) return {};
  const candidates = new Set(first.hits.map(hit => hit.source));
  const second = await search(terms);
  const hit = select(second.hits.filter(hit => candidates.has(hit.source)));
  return {hit, terms};
}

export async function mountKnowledgeRelations(host, api) {
  const [catalog, sources] = await Promise.all([api("/api/knowledge/catalog"), api("/api/knowledge/sources")]);
  const graph = buildSourceGraph(catalog, sources);
  if (!host.isConnected) return;
  host.replaceChildren();
  const category = element("select");
  category.setAttribute("aria-label", "业务大类");
  for (const item of graph.categories.values()) category.add(option(item.id, item.name));
  const group = element("div", undefined, "rel-collection");
  const note = element("p", "目录关联指向可继续查阅的文件；回答中的数值和条款仍需核对具体片段。");
  const form = element("form");
  const query = element("input");
  query.type = "search";
  query.required = true;
  query.minLength = 2;
  query.maxLength = 300;
  query.placeholder = "输入业务问题；两项来源可用分号分开";
  query.setAttribute("aria-label", "业务问题");
  const submit = element("button", "追溯来源", "drawer-button");
  submit.type = "submit";
  const onlyOfficial = element("input");
  onlyOfficial.type = "checkbox";
  const filter = element("label");
  filter.append(onlyOfficial, document.createTextNode(" 仅发布方来源"));
  form.append(query, filter, submit);
  const results = element("div", undefined, "rel-results");
  results.setAttribute("aria-live", "polite");
  const date = document.querySelector("#knowledgeAsOf")?.value;

  function showCategory(id) {
    const item = graph.categories.get(id);
    category.value = id;
    group.replaceChildren();
    const heading = element("h3", item.name);
    const subjects = element("p", "目录主题 · " + item.topics.map(t => t.name).join("、"));
    const list = element("div", undefined, "rel-documents");
    for (const sourceId of item.ids) list.append(sourceDetails(graph.documents.get(sourceId)));
    group.append(heading, subjects, element("strong", item.ids.length + " 份已关联文件"), list);
  }

  function showHits(payload) {
    const hits = payload.hits.filter(hit => hit.qualified);
    if (!hits.length) {
      results.append(element("p", "没有达到检索门槛的片段。"));
      return;
    }
    for (const hit of hits) {
      const block = element("article", undefined, "rel-hit");
      block.append(element("h3", hit.title), element("blockquote", hit.snippet));
      const source = graph.documents.get(hit.source);
      if (!source || !hit.chunk_checksum_sha256 || !source.document_checksum_sha256 ||
          source.document_checksum_sha256 !== hit.document_checksum_sha256) {
        block.append(element("p", "索引与来源登记的版本不一致，请重新打开知识全景。"));
      } else {
        block.append(element("code", "片段 " + hit.id + "　SHA-256 " + hit.chunk_checksum_sha256), sourceDetails(source));
        const links = element("div", undefined, "rel-links");
        const parents = graph.parents.get(hit.source) || [];
        if (!parents.length) links.append(element("span", "该文件尚无目录大类关联。"));
        for (const id of parents) {
          const button = element("button", graph.categories.get(id).name);
          button.type = "button";
          button.addEventListener("click", () => {
            showCategory(id);
            category.focus();
            category.scrollIntoView({ block: "nearest" });
          });
          links.append(button);
        }
        block.append(links);
      }
      results.append(block);
    }
  }

  let requestId = 0;
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const text = query.value.trim();
    const current = ++requestId;
    if (text.length < 2) {
      results.textContent = "请输入至少两个字符。";
      return;
    }
    results.textContent = "正在检索知识片段…";
    try {
      const filters = {official_only:onlyOfficial.checked, ...(date ? {as_of_date:date} : {})};
      const parts = text.split(/[；;]/).map(s=>s.trim()).filter(Boolean);
      if (parts.length === 2 && parts.every(s => s.length >= 2)) {
        const first = await findSourcePassage(api, parts[0], filters, undefined, graph.documents);
        const second = await findSourcePassage(api, parts[1], filters, first.hit?.source, graph.documents);
        if (current !== requestId || !host.isConnected) return;
        results.replaceChildren();
        for (const [index, result] of [first, second].entries()) {
          results.append(element("h3", parts[index]));
          if (result.terms) results.append(element("small", "补查登记来源所用检索词 · " + result.terms));
          showHits({hits:result.hit ? [result.hit] : []});
        }
        return;
      }
      const data = await api("/api/knowledge/search", { method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ query:text, top_k:5,...filters }) });
      if (current === requestId && host.isConnected) {
        results.replaceChildren();
        showHits(data);
      }
    } catch {
      if (current === requestId && host.isConnected) results.textContent = "知识检索暂时不可用，请重试。";
    }
  });
  category.addEventListener("change", () => showCategory(category.value));
  host.append(form, results, note, category, group);
  showCategory(category.value);
}
