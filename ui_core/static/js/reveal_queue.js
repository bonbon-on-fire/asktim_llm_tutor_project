"use strict";

// Typewriter reveal queue.
//
// The tutor answer does not trickle in token-by-token: Claude spends a few
// seconds on hidden reasoning, then bursts the whole answer in ~30ms. GPT
// trickles progressively. This queue unifies both — text pushed in (all at
// once or in pieces) is revealed a few words at a time on a timer, so the
// student sees the answer type out instead of popping in as a block.
//
// Pure logic, no DOM and no real timers: the caller injects onReveal (what to
// do with each revealed chunk), schedule, and cancel. That keeps it unit
// testable with a fake clock. See reveal_queue.test.js.
//
// Options:
//   onReveal(chunk)  — called with each revealed piece of text (required).
//   schedule(fn, ms) — set a timer, returns an id (default setTimeout).
//   cancel(id)       — clear a timer by id (default clearTimeout).
//   tickMs           — ms between reveals (default 40).
//   charsPerTick     — target chars revealed per tick; the slice is extended
//                      to the next whitespace so words stay whole (default 10).
//   maxBacklog       — once pending exceeds this, slice size scales up so long
//                      answers still finish in ~1-2s instead of dragging on
//                      (default 300).

function createRevealQueue(options) {
  const opts = options || {};
  const onReveal = opts.onReveal;
  if (typeof onReveal !== "function") {
    throw new Error("createRevealQueue: onReveal callback is required");
  }
  const schedule =
    typeof opts.schedule === "function"
      ? opts.schedule
      : function (fn, ms) {
          return setTimeout(fn, ms);
        };
  const cancel =
    typeof opts.cancel === "function"
      ? opts.cancel
      : function (id) {
          clearTimeout(id);
        };
  const tickMs = typeof opts.tickMs === "number" && opts.tickMs > 0 ? opts.tickMs : 40;
  const baseChars =
    typeof opts.charsPerTick === "number" && opts.charsPerTick > 0 ? opts.charsPerTick : 10;
  const maxBacklog =
    typeof opts.maxBacklog === "number" && opts.maxBacklog > 0 ? opts.maxBacklog : 300;

  let pending = ""; // buffered text not yet revealed
  let timerId = null; // active tick timer, or null when idle
  let finishCb = null; // done callback, fired once pending drains
  let cancelled = false;

  function tickLoopActive() {
    return timerId !== null;
  }

  // How many chars to reveal this tick. Extend past baseChars to the next
  // whitespace so we never split a word, and accelerate when the backlog is
  // large so a long answer doesn't take many seconds to finish typing.
  function sliceLength() {
    let target = baseChars;
    if (pending.length > maxBacklog) {
      // Scale the slice up proportionally to the backlog: the further behind we
      // are, the bigger each bite, so drain time stays bounded.
      target = Math.ceil((baseChars * pending.length) / maxBacklog);
    }
    if (target >= pending.length) {
      return pending.length;
    }
    // Extend to the next whitespace boundary so words stay whole.
    let end = target;
    while (end < pending.length && !/\s/.test(pending.charAt(end - 1))) {
      end += 1;
    }
    return end;
  }

  function reveal() {
    const n = sliceLength();
    const chunk = pending.slice(0, n);
    pending = pending.slice(n);
    if (chunk.length > 0) {
      onReveal(chunk);
    }
  }

  function stopTimer() {
    if (timerId !== null) {
      cancel(timerId);
      timerId = null;
    }
  }

  function tick() {
    timerId = null;
    if (cancelled) {
      return;
    }
    if (pending.length > 0) {
      reveal();
    }
    if (pending.length > 0) {
      arm();
    } else if (finishCb) {
      const cb = finishCb;
      finishCb = null;
      cb();
    }
  }

  function arm() {
    if (timerId === null && !cancelled) {
      timerId = schedule(tick, tickMs);
    }
  }

  return {
    // Append text to reveal. Accepts bursts or trickles; ignores empty/falsy.
    push: function (text) {
      if (cancelled) {
        return;
      }
      if (typeof text !== "string" || text.length === 0) {
        return;
      }
      pending += text;
      arm();
    },

    // Signal the stream is complete. Drain whatever remains, then fire cb once.
    // If nothing is pending, cb fires immediately.
    finish: function (cb) {
      if (cancelled) {
        return;
      }
      finishCb = typeof cb === "function" ? cb : null;
      if (pending.length === 0 && !tickLoopActive()) {
        if (finishCb) {
          const done = finishCb;
          finishCb = null;
          done();
        }
      } else {
        arm();
      }
    },

    // Abort: stop revealing, drop buffered text, suppress the done callback.
    cancel: function () {
      cancelled = true;
      stopTimer();
      pending = "";
      finishCb = null;
    },

    // Chars still buffered (used by tests and by callers checking drain state).
    pendingLength: function () {
      return pending.length;
    },
  };
}

// Dual export: Node (unit tests) and browser (loaded via <script> before chat.js).
if (typeof module !== "undefined" && module.exports) {
  module.exports = { createRevealQueue };
}
if (typeof window !== "undefined") {
  window.createRevealQueue = createRevealQueue;
}
