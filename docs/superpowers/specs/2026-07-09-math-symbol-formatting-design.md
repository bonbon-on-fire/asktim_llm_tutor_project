# Math symbol formatting for tutor output — design

**Date:** 2026-07-09
**Status:** Approved, ready for implementation
**Source:** CTL.SC2x staff-meeting item — "Output math symbols should be correctly formatted."

## Problem

The tutor emits LaTeX math using the standard `\(…\)` (inline) and `\[…\]` (display)
delimiters — **4,130** `\(`/`\)` pairs in current transcripts, with commands like `\sum`,
`\frac`, `\times`. But the chat UIs render tutor replies only through `marked` + `DOMPurify`
(see [`setMessageContent`](../../../main_ui/static/js/chat.js) at `chat.js:181`). There is **no
math renderer**, so students see raw LaTeX source such as `\(\frac{a}{b}\)` and
`\[\sum_{i=1}^n x_i\]` instead of formatted symbols.

## Decisions (locked with the user)

| Question | Decision |
|---|---|
| Rendering engine | **KaTeX, client-side**, vendored locally (like `marked`/`dompurify`) — offline/VPN-safe |
| Delimiters | **Only** `\(…\)` (inline) and `\[…\]` (display). **Never** `$…$` |
| Surfaces | **All three**: `main_ui`, `sandbox_ui`, `database_ui` viewer |
| Integration point | A **`marked` extension** that renders math during parse (not a post-render pass) |
| Cost impact | **None.** Client-side only; no prompt/token change |

### Why `$…$` must never be a math delimiter

`$` is used pervasively for **currency** in this supply-chain course: `$500`, `$1,500`,
`$167, but also, the $`, `$0.50 (down from $`, etc. Treating `$…$` as math would catastrophically
mangle dollar amounts. Only the unambiguous `\(…\)` / `\[…\]` delimiters trigger rendering.

### Why a `marked` extension, not a post-render auto-render pass

The obvious approach — run KaTeX's `renderMathInElement` *after* `marked` — is **broken**, verified
empirically against the vendored `marked`:

| Input | `marked` output | Result |
|---|---|---|
| `Inline \(\frac{a}{b}\) done` | `Inline (\frac{a}{b}) done` | delimiters stripped → KaTeX finds nothing |
| `Display \[\sum_{i=1}^n x_i\] end` | `Display [sum_{i=1}^n x_i] end` | delimiters **and** `\sum` backslash gone |
| `Cost is $500 today` | `Cost is $500 today` | currency untouched (good) |

Markdown's backslash-escaping eats `\(`, `\)`, `\[`, `\]` (they are ASCII punctuation) before any
post-pass can see them. A `marked` extension tokenizes the math spans *during* parsing — before
escaping — so the delimiters are matched intact and the interior is never treated as markdown.

### Why KaTeX over MathJax / prompt-only Unicode

- **KaTeX vs MathJax:** KaTeX is far lighter to vendor for offline/VPN use and renders faster;
  tutor-level math (fractions, sums, exponents, roots) is well within its coverage.
- **vs prompt-only Unicode:** Emitting `×`, `≤`, `√`, `Σ` in the prompt would need no frontend work
  but renders fractions / exponents / summation limits poorly, and is the *only* option that could
  perturb output tokens/cost. KaTeX keeps fidelity high and cost flat.

## Architecture

Render math *inside* the existing single-sanitized-`innerHTML` pipeline. The tutor branch of each
`setMessageContent` becomes:

```
marked.parse(content)          // with the KaTeX extension registered
  → DOMPurify.sanitize(html)   // KaTeX output still passes through the sanitizer
  → el.innerHTML = …           // exactly one sanitized innerHTML assignment (XSS guard intact)
```

KaTeX output is HTML **we** generate from the LaTeX (via `katex.renderToString(tex, {displayMode,
throwOnError:false})`), not tutor-controlled markup, and it is still run through DOMPurify. The
no-raw-`innerHTML` XSS guarantee is preserved unchanged.

### Components / files

- **Vendored assets** (copied into each app's static dir, matching the existing `marked`/`dompurify`
  vendoring for offline/VPN + container bake-in):
  - `katex.min.js`
  - `katex.min.css`
  - the KaTeX **fonts** directory (referenced by `katex.min.css`)
  - Destinations: `main_ui/static/js|css`, `sandbox_ui/static/js|css`, `database_ui/static/js|css`
    (mirror each app's existing static layout).
- **One shared hand-written helper** `katex-marked.js` — defines the `marked` extension (inline
  `\(…\)` and block `\[…\]` tokenizers + `katex.renderToString` renderers) and exposes a
  `renderTutorMarkdown(content)` wrapper returning the sanitized HTML. Copied identically into each
  app's static `js/` so all three call sites share one implementation.
- **Template wiring:**
  - `ui_core/templates/base_chat.html` (covers `main_ui` + `sandbox_ui`): add `katex.min.css` in
    `<head>`; load `katex.min.js` then `katex-marked.js` with `defer`, ordered **before** `chat.js`.
  - `database_ui/templates/index.html`: same additions for the standalone viewer.
- **Call-site edits** (route the tutor branch through the shared helper):
  - `main_ui/static/js/chat.js` (`setMessageContent`, ~`chat.js:181`)
  - `sandbox_ui/static/js/chat.js` (same function; the file differs from main_ui but has the same shape)
  - `database_ui/static/js/database.js` (`setMessageContent`, ~`database.js:148`)

### Data flow (unchanged except the render step)

Tutor reply text (already containing `\(…\)` / `\[…\]`) → `renderTutorMarkdown` → marked tokenizes
markdown **and** math → math tokens render via KaTeX → assembled HTML → DOMPurify → `innerHTML`.
Student text and any load-failure path still use `textContent`.

### Error handling & graceful degradation

- `throwOnError: false` — malformed LaTeX renders in KaTeX's error style (red) instead of throwing
  and aborting the whole message.
- If KaTeX or the helper fails to load, `renderTutorMarkdown` falls back to plain
  `marked` + `DOMPurify` (and ultimately `textContent`). Math degrades to raw source; **chat never
  breaks**. This mirrors the existing `canRenderMarkdown` guard.

### Security / sanitizer verification

One explicit implementation task: confirm the vendored `DOMPurify` preserves KaTeX's output
(spans, MathML `<math>`/`<annotation>`, inline `style`/`class`). DOMPurify supports MathML by
default; widen the allowlist **minimally** only if a needed element/attribute is stripped. Do not
disable sanitization.

## Testing

- **Unit (helper):** feed the real transcript patterns — `\(\frac{a}{b}\)`, `\[\sum_{i=1}^n x_i\]`,
  `\(x^2\)`, `\times` — and assert KaTeX markup is produced (a `katex` class / rendered structure),
  not literal backslash source.
- **Currency regression:** assert `$500`, `$167, but also, the $`, `$0.50 (down from $` pass through
  as literal text with **no** math rendering.
- **Degradation:** with KaTeX absent, assert the helper falls back to marked+DOMPurify output.
- **End-to-end:** drive one real tutor reply containing math through the browser (Playwright) on
  `main_ui` and confirm rendered symbols on screen.

## Out of scope

- Changing the tutor prompt or its math output conventions (it already emits correct LaTeX).
- Rendering math in any non-chat surface (dashboards, exported transcripts) beyond the three UIs.
- Supporting `$…$` or `$$…$$` delimiters.
