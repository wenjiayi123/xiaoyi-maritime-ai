"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const fc = require("fast-check");
const contract = require("../web/runtime_contract.js");

test("property fuzz: arbitrary JSON never bypasses object-only telemetry boundary", () => {
  fc.assert(
    fc.property(fc.jsonValue(), (value) => {
      const encoded = JSON.stringify(value);
      try {
        const parsed = contract.parseJsonObject(encoded, 50_000);
        assert.equal(typeof parsed, "object");
        assert.notEqual(parsed, null);
        assert.equal(Array.isArray(parsed), false);
      } catch (error) {
        assert.ok(error instanceof TypeError || error instanceof RangeError);
      }
      assert.equal({}.polluted, undefined);
    }),
    { numRuns: 1_000 },
  );
});

test("property fuzz: SSE parser returns only bounded named object events", () => {
  fc.assert(
    fc.property(fc.string({ maxLength: 4_000 }), (block) => {
      try {
        const parsed = contract.parseSseBlock(block);
        if (parsed === null) return;
        assert.match(parsed.event, /^[a-z][a-z0-9_-]{0,63}$/i);
        assert.equal(typeof parsed.data, "object");
        assert.equal(Array.isArray(parsed.data), false);
      } catch (error) {
        assert.ok(
          error instanceof SyntaxError
            || error instanceof TypeError
            || error instanceof RangeError,
        );
      }
    }),
    { numRuns: 1_000 },
  );
});

test("property fuzz: energy ranges fail closed to today", () => {
  fc.assert(
    fc.property(fc.anything(), (value) => {
      const normalized = contract.normalizeEnergyRange(value);
      assert.ok(contract.ENERGY_RANGES.includes(normalized));
      if (!contract.ENERGY_RANGES.includes(value)) assert.equal(normalized, "today");
    }),
    { numRuns: 1_000 },
  );
});

test("property fuzz: entropy fallback produces fixed-shape session identifiers", () => {
  fc.assert(
    fc.property(fc.uint8Array({ minLength: 16, maxLength: 16 }), (entropy) => {
      const cryptoStub = {
        getRandomValues(target) {
          target.set(entropy);
          return target;
        },
      };
      const identifier = contract.createSessionId(cryptoStub, 1_786_665_600_000);
      assert.match(identifier, /^web-1786665600000-[0-9a-f]{32}$/);
    }),
    { numRuns: 1_000 },
  );
});
