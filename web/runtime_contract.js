(function attachRuntimeContract(root, factory) {
  "use strict";
  const contract = factory();
  if (typeof module === "object" && module.exports) module.exports = contract;
  else root.XiaoyiRuntimeContract = contract;
})(typeof globalThis === "object" ? globalThis : this, function createRuntimeContract() {
  "use strict";

  const ENERGY_RANGES = Object.freeze(["today", "7d", "30d"]);
  const MAX_EVENT_CHARACTERS = 2_000_000;

  function normalizeEnergyRange(value) {
    return ENERGY_RANGES.includes(value) ? value : "today";
  }

  function parseJsonObject(value, maxCharacters = MAX_EVENT_CHARACTERS) {
    if (typeof value !== "string") throw new TypeError("JSON event must be a string");
    if (!Number.isSafeInteger(maxCharacters) || maxCharacters < 1) {
      throw new RangeError("JSON event limit must be a positive safe integer");
    }
    if (value.length > maxCharacters) throw new RangeError("JSON event exceeds the client limit");
    const parsed = JSON.parse(value);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new TypeError("JSON event must contain an object");
    }
    return parsed;
  }

  function parseSseBlock(block) {
    if (typeof block !== "string") throw new TypeError("SSE block must be a string");
    if (block.length > MAX_EVENT_CHARACTERS) throw new RangeError("SSE block exceeds the client limit");
    let event = "message";
    const dataLines = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) {
        const candidate = line.slice(6).trim();
        event = /^[a-z][a-z0-9_-]{0,63}$/i.test(candidate) ? candidate : "message";
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (!dataLines.length) return null;
    return { event, data: parseJsonObject(dataLines.join("\n")) };
  }

  function createSessionId(cryptoApi, now = Date.now()) {
    if (!cryptoApi || typeof cryptoApi.getRandomValues !== "function") {
      throw new Error("Secure browser entropy is unavailable");
    }
    if (typeof cryptoApi.randomUUID === "function") return `web-${cryptoApi.randomUUID()}`;
    const bytes = new Uint8Array(16);
    cryptoApi.getRandomValues(bytes);
    const entropy = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    return `web-${Math.trunc(Number(now))}-${entropy}`;
  }

  return Object.freeze({
    ENERGY_RANGES,
    MAX_EVENT_CHARACTERS,
    createSessionId,
    normalizeEnergyRange,
    parseJsonObject,
    parseSseBlock,
  });
});
