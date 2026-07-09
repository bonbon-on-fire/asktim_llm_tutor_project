# Math Symbol Formatting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the tutor's LaTeX math (`\(…\)` inline, `\[…\]` display) as formatted symbols in all three chat UIs, without treating currency `$…$` as math.

**Architecture:** Add a `marked` extension that tokenizes `\(…\)`/`\[…\]` *during* markdown parsing (before markdown's backslash-escaping destroys the delimiters — verified: post-render KaTeX does not work) and renders each with `katex.renderToString`. Output still flows through the existing single `DOMPurify.sanitize` → `innerHTML` path, preserving the XSS guarantee. KaTeX is vendored once in `ui_core/static` (served to all three apps via the `ui_core.static` blueprint, exactly like the already-shared `chat.css`).

**Tech Stack:** Vanilla JS, vendored `marked` + `DOMPurify` (existing), vendored **KaTeX 0.16.x** (new), Flask/Jinja templates. Unit tests run under node's built-in test runner (`node --test`); no new package dependencies.

## Global Constraints

- **Delimiters:** ONLY `\(…\)` (inline) and `\[…\]` (display). NEVER `$…$` or `$$…$$` — `$` is currency in this course.
- **Security:** Exactly one sanitized `innerHTML` assignment per message; all rendered HTML passes through `DOMPurify.sanitize`. Never disable sanitization. Student text and any deps-missing path stay `textContent`.
- **Offline/VPN:** All assets vendored locally (no CDN), baked into the container image — same rule the existing `marked`/`dompurify` comments state.
- **Graceful degradation:** If KaTeX is absent, markdown still renders (math stays literal); if `marked`/`DOMPurify` are absent, fall back to `textContent`. Chat must never break.
- **Cost:** Client-side only. No tutor-prompt or token changes.
- **Commits:** Follow repo convention — do NOT add a `Co-Authored-By: Claude` trailer.

---

### Task 1: Vendor KaTeX assets into `ui_core/static`

**Files:**
- Create: `ui_core/static/js/katex.min.js`
- Create: `ui_core/static/css/katex.min.css`
- Create: `ui_core/static/css/fonts/` (the full KaTeX font directory)

**Interfaces:**
- Produces: browser global `window.katex` with `katex.renderToString(tex, opts)`; in node, `require(".../katex.min.js")` returns the same object (UMD). `katex.min.css` references fonts via `url(fonts/…)` relative to itself, so fonts MUST sit in a `fonts/` dir beside the CSS.

- [ ] **Step 1: Fetch the KaTeX dist tarball into the scratchpad**

Run (build-time network is fine; runtime stays offline):
```bash
cd "C:/Users/nishi/AppData/Local/Temp/claude/d--asktim-llm-tutor-project/4d2f8e3c-d8c7-4487-a2da-39bef8ef0888/scratchpad"
npm pack katex@0.16.11
tar -xzf katex-0.16.11.tgz
ls package/dist/katex.min.js package/dist/katex.min.css package/dist/fonts | head
```
Expected: the three paths list successfully (`fonts/` contains `KaTeX_*.woff2/.woff/.ttf`).
Fallback if `npm` has no network: download `katex.tar.gz` from https://github.com/KaTeX/KaTeX/releases/tag/v0.16.11 and use its `katex/` folder instead of `package/dist/`.

- [ ] **Step 2: Copy assets into `ui_core/static`**

Run (from repo root `d:/asktim_llm_tutor_project`; adjust the `SRC` path to the scratchpad `package/dist`):
```bash
SRC="C:/Users/nishi/AppData/Local/Temp/claude/d--asktim-llm-tutor-project/4d2f8e3c-d8c7-4487-a2da-39bef8ef0888/scratchpad/package/dist"
mkdir -p ui_core/static/js ui_core/static/css/fonts
cp "$SRC/katex.min.js"  ui_core/static/js/katex.min.js
cp "$SRC/katex.min.css" ui_core/static/css/katex.min.css
cp -r "$SRC/fonts/." ui_core/static/css/fonts/
ls ui_core/static/js/katex.min.js ui_core/static/css/katex.min.css && ls ui_core/static/css/fonts | wc -l
```
Expected: both files listed; font count > 0 (KaTeX ships ~60 font files).

- [ ] **Step 3: Smoke-test that KaTeX renders in node (SSR, no DOM)**

Run:
```bash
node -e "const k=require('./ui_core/static/js/katex.min.js'); const h=k.renderToString('\\\\frac{a}{b}',{throwOnError:false}); console.log(h.includes('katex')?'OK':'FAIL');"
```
Expected: prints `OK`.

- [ ] **Step 4: Commit**

```bash
git add ui_core/static/js/katex.min.js ui_core/static/css/katex.min.css ui_core/static/css/fonts
git commit -m "chore(ui): vendor KaTeX 0.16.11 (js, css, fonts) in ui_core/static"
```

---

### Task 2: Shared `katex-marked.js` helper (marked extension + renderer)

**Files:**
- Create: `ui_core/static/js/katex-marked.js`
- Test: `ui_core/static/js/test_katex_marked.js`

**Interfaces:**
- Consumes: `window.marked` (has `Marked` class + `parse`), `window.katex` (from Task 1), `window.DOMPurify` — all resolved from the global at call time.
- Produces:
  - `makeMathExtension(katex)` → a `marked` extension config object `{ extensions: [...] }` suitable for `markedInstance.use(...)`. Exported via `module.exports` in node.
  - `window.renderTutorMarkdown(content: string)` → sanitized HTML string, or `null` if `marked`/`DOMPurify` are unavailable (caller then uses `textContent`). If only KaTeX is missing, renders markdown with math left literal.

- [ ] **Step 1: Write the failing test**

Create `ui_core/static/js/test_katex_marked.js`:
```js
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
  assert.ok(!out.includes("\\frac"), "raw \\frac should be consumed by KaTeX");
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test ui_core/static/js/test_katex_marked.js`
Expected: FAIL — `Cannot find module './katex-marked.js'`.

- [ ] **Step 3: Write the helper**

Create `ui_core/static/js/katex-marked.js`:
```js
"use strict";
// Render \(...\) (inline) and \[...\] (display) math with KaTeX *inside* the
// marked parse, before markdown's backslash-escaping strips the delimiters.
// $...$ is deliberately NOT a delimiter — it is currency in this course.
(function (global) {
  function makeMathExtension(katex) {
    function render(tex, displayMode) {
      return katex.renderToString(tex, { displayMode: displayMode, throwOnError: false });
    }
    return {
      extensions: [
        {
          name: "inlineMath",
          level: "inline",
          start(src) { const m = src.match(/\\\(/); return m ? m.index : undefined; },
          tokenizer(src) {
            const m = /^\\\(([\s\S]+?)\\\)/.exec(src);
            if (m) return { type: "inlineMath", raw: m[0], text: m[1] };
          },
          renderer(token) { return render(token.text, false); },
        },
        {
          name: "displayMath",
          level: "inline",
          start(src) { const m = src.match(/\\\[/); return m ? m.index : undefined; },
          tokenizer(src) {
            const m = /^\\\[([\s\S]+?)\\\]/.exec(src);
            if (m) return { type: "displayMath", raw: m[0], text: m[1] };
          },
          renderer(token) { return render(token.text, true); },
        },
      ],
    };
  }

  let cached = null; // memoized Marked instance (browser)
  function renderTutorMarkdown(content) {
    const marked = global.marked;
    const katex = global.katex;
    const DOMPurify = global.DOMPurify;
    if (!marked || !DOMPurify) return null; // caller falls back to textContent
    let html;
    if (katex) {
      if (!cached) { cached = new marked.Marked(); cached.use(makeMathExtension(katex)); }
      html = cached.parse(content || "");
    } else {
      html = marked.parse(content || ""); // KaTeX missing: math stays literal
    }
    return DOMPurify.sanitize(html);
  }

  const api = { makeMathExtension: makeMathExtension, renderTutorMarkdown: renderTutorMarkdown };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  global.renderTutorMarkdown = renderTutorMarkdown; // browser global
})(typeof globalThis !== "undefined" ? globalThis : this);
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test ui_core/static/js/test_katex_marked.js`
Expected: PASS — 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add ui_core/static/js/katex-marked.js ui_core/static/js/test_katex_marked.js
git commit -m "feat(ui): shared katex-marked helper renders LaTeX math, spares currency"
```

---

### Task 3: Wire KaTeX assets into the templates

**Files:**
- Modify: `ui_core/templates/base_chat.html` (head + scripts near lines 8 and 141-143)
- Modify: `database_ui/templates/index.html` (head near line 8 + scripts near lines 52-54)

**Interfaces:**
- Consumes: `ui_core.static` files from Tasks 1–2.
- Produces: `window.katex` and `window.renderTutorMarkdown` are defined before `chat.js`/`database.js` run.

- [ ] **Step 1: Add the KaTeX stylesheet + scripts to `base_chat.html`**

In `ui_core/templates/base_chat.html`, change the `{% block head_extra %}` line (line 8) to also load the KaTeX CSS:
```html
    <link rel="stylesheet" href="{{ url_for('ui_core.static', filename='css/katex.min.css') }}">
{% block head_extra %}{% endblock %}</head>
```
Then, immediately before the existing `marked.min.js` script tag (line 141), add the KaTeX libs so they load (deferred, in order) before `chat.js`:
```html
    <script src="{{ url_for('ui_core.static', filename='js/katex.min.js') }}" defer></script>
    <script src="{{ url_for('ui_core.static', filename='js/katex-marked.js') }}" defer></script>
```
(Leave the existing `marked`/`dompurify`/`chat.js` tags as-is, after these.)

- [ ] **Step 2: Add the same wiring to `database_ui/templates/index.html`**

In `database_ui/templates/index.html`, after the existing `ui_core.static` chat.css link (line 7), add:
```html
    <link rel="stylesheet" href="{{ url_for('ui_core.static', filename='css/katex.min.css') }}">
```
And immediately before the `marked.min.js` script (line 52), add:
```html
    <script src="{{ url_for('ui_core.static', filename='js/katex.min.js') }}" defer></script>
    <script src="{{ url_for('ui_core.static', filename='js/katex-marked.js') }}" defer></script>
```

- [ ] **Step 3: Verify the assets are served (run one app, curl the URLs)**

Run (main_ui; use the repo's normal run command if different):
```bash
python -m main_ui &
sleep 4
curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:8000/ui-core/js/katex.min.js
curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:8000/ui-core/css/katex.min.css
curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:8000/ui-core/css/fonts/KaTeX_Main-Regular.woff2
kill %1
```
Expected: three `200` lines. (If the app's port/entrypoint differs, consult `main_ui/run_app.py` / `main_ui/README.md`.)

- [ ] **Step 4: Commit**

```bash
git add ui_core/templates/base_chat.html database_ui/templates/index.html
git commit -m "feat(ui): load KaTeX css+js in chat templates before chat scripts"
```

---

### Task 4: Route tutor rendering through `renderTutorMarkdown` in all three call sites

**Files:**
- Modify: `main_ui/static/js/chat.js` (`setMessageContent`, ~lines 181-197)
- Modify: `sandbox_ui/static/js/chat.js` (`setMessageContent`, ~lines 214-229)
- Modify: `database_ui/static/js/database.js` (`setMessageContent`, ~lines 148-160)

**Interfaces:**
- Consumes: `window.renderTutorMarkdown` (Task 2). Returns a sanitized HTML string, or `null` when deps are unavailable.

- [ ] **Step 1: Update `main_ui/static/js/chat.js`**

Replace the body of `setMessageContent` (lines 181-197) with:
```js
  function setMessageContent(el, role, content) {
    // Tutor replies are markdown + LaTeX math (\(...\), \[...\]). renderTutorMarkdown
    // parses markdown, renders math with KaTeX, and DOMPurify-sanitizes — one
    // sanitized innerHTML write, so the no-raw-innerHTML XSS guarantee holds.
    // Student text, and any case where the libs failed to load, stay textContent.
    const rich =
      role === "tutor" && typeof window.renderTutorMarkdown === "function"
        ? window.renderTutorMarkdown(content)
        : null;
    if (rich !== null) {
      el.classList.add("message-rich");
      el.innerHTML = rich;
    } else {
      // textContent — never raw innerHTML — to prevent XSS from tutor/student text.
      el.textContent = content;
    }
  }
```

- [ ] **Step 2: Update `sandbox_ui/static/js/chat.js`**

Replace the body of `setMessageContent` (lines 214-229) with the identical function from Step 1.

- [ ] **Step 3: Update `database_ui/static/js/database.js`**

Replace the body of `setMessageContent` (lines 148-160) with (note the `content || ""` the viewer uses):
```js
  function setMessageContent(el, role, content) {
    // Tutor replies are markdown + LaTeX math; render + sanitize via the shared
    // helper. Everything else is text.
    const rich =
      role === "tutor" && typeof window.renderTutorMarkdown === "function"
        ? window.renderTutorMarkdown(content || "")
        : null;
    if (rich !== null) {
      el.classList.add("message-rich");
      el.innerHTML = rich;
    } else {
      el.textContent = content || "";
    }
  }
```

- [ ] **Step 4: Sanity-check the JS parses (no syntax errors)**

Run:
```bash
node --check main_ui/static/js/chat.js
node --check sandbox_ui/static/js/chat.js
node --check database_ui/static/js/database.js
```
Expected: no output, exit 0 for each.

- [ ] **Step 5: Commit**

```bash
git add main_ui/static/js/chat.js sandbox_ui/static/js/chat.js database_ui/static/js/database.js
git commit -m "feat(ui): render tutor math via renderTutorMarkdown in all three chat UIs"
```

---

### Task 5: End-to-end + sanitizer verification in the browser

**Files:**
- No source changes expected. If DOMPurify strips required KaTeX markup, modify `ui_core/static/js/katex-marked.js` (see Step 3).

**Interfaces:**
- Consumes: everything from Tasks 1–4.

- [ ] **Step 1: Render a math + currency message and confirm formatted output**

Start `main_ui` locally, open the chat, and get the tutor to produce (or inject a stored tutor message containing) both math and currency, e.g.:
`Marginal cost is \(\frac{\Delta C}{\Delta Q}\) and total was $1,500 with \[\sum_{i=1}^{n} q_i\] units.`
Drive it with the browser (Playwright MCP): navigate to the app, snapshot the message.
Expected: `\(\frac{\Delta C}{\Delta Q}\)` and `\[\sum…\]` render as formatted fractions/summation; `$1,500` shows literally as `$1,500` (no math styling).

- [ ] **Step 2: Confirm KaTeX markup survived DOMPurify**

In the browser console (Playwright `browser_evaluate`), check the rendered tutor message node:
```js
document.querySelectorAll('.message-rich .katex').length
```
Expected: `>= 1`. If `0`, DOMPurify stripped KaTeX output — go to Step 3. Otherwise skip to Step 4.

- [ ] **Step 3: (Only if Step 2 found 0) widen the DOMPurify allowlist minimally**

In `ui_core/static/js/katex-marked.js`, change the sanitize call to preserve MathML/SVG namespaces KaTeX uses:
```js
    return DOMPurify.sanitize(html, { USE_PROFILES: { html: true, mathMl: true, svg: true } });
```
Re-run Steps 1–2. Do NOT disable sanitization. Commit this change with:
```bash
git add ui_core/static/js/katex-marked.js
git commit -m "fix(ui): keep KaTeX MathML/SVG through DOMPurify"
```

- [ ] **Step 4: Confirm graceful degradation**

Temporarily rename the vendored KaTeX file (`ui_core/static/js/katex.min.js` → `.bak`), reload the chat, and confirm the message still renders (markdown intact, math shown as literal `\(...\)` source) with no console errors — then restore the file.
Expected: no crash; chat usable. (This exercises the `if (katex)` branch in `renderTutorMarkdown`.)

- [ ] **Step 5: Final commit (if any verification tweaks were made beyond Step 3)**

```bash
git status   # ensure tree is clean or only intended changes remain
```

---

## Notes for the implementer

- **Why an extension, not a post-pass:** verified empirically — `marked.parse("\\(\\frac{a}{b}\\)")` yields `(\frac{a}{b})` (delimiters stripped). The extension must tokenize math *before* markdown escaping. The Task 2 unit test is the guard against regressing this.
- **Both delimiters are `level: "inline"`** on purpose: `\[…\]` display math is caught even when the tutor puts it inside a paragraph; KaTeX's `.katex-display` CSS still breaks it onto its own centered line.
- **Do not touch** the per-app `marked.min.js` / `dompurify.min.js` copies or the tutor prompt.
