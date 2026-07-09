"use strict";
const test = require("node:test");
const assert = require("node:assert");

// katex is vendored beside this file; marked is vendored per-app — borrow main_ui's copy.
const katex = require("./katex.min.js");
const markedMod = require("../../../main_ui/static/js/marked.min.js");
const Marked = markedMod.Marked;
const { makeMathExtension } = require("./katex-marked.js");

function render(src) {
  const inst = new Marked();
  inst.use(makeMathExtension(katex));
  return inst.parse(src);
}

test("inline \\(...\\) renders as KaTeX, not literal backslashes", () => {
  const out = render("Result: \\(\\frac{a}{b}\\) done");
  assert.ok(out.includes("katex"), "expected katex markup");
  assert.ok(out.includes('katex-html'), "expected rendered visual math markup");
});

test("display \\[...\\] renders as KaTeX display math", () => {
  const out = render("\\[\\sum_{i=1}^n x_i\\]");
  assert.ok(out.includes("katex"), "expected katex markup");
});

test("currency $500 is left literal (no math)", () => {
  const out = render("The fixed cost is $500 today");
  assert.ok(out.includes("$500"), "dollar amount must survive");
  assert.ok(!out.includes("katex"), "no math rendering for currency");
});

test("mixed currency prose stays literal", () => {
  const out = render("Charge $167, but also, the $250 setup");
  assert.ok(!out.includes("katex"), "no math rendering for currency prose");
});
