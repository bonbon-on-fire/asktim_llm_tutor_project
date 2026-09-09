"use strict";

// Unit tests for the typewriter reveal queue. Run with:
//   node --test ui_core/static/js/reveal_queue.test.js
// No dependencies — Node's built-in test runner + a hand-driven fake clock.

const test = require("node:test");
const assert = require("node:assert/strict");

const { createRevealQueue } = require("./reveal_queue.js");

// A manual clock: createRevealQueue takes injected schedule/cancel, so tests
// drive time by hand instead of waiting on real timers. advance(ms) fires every
// callback due at-or-before the new "now", including ones scheduled during the
// advance (that's how the tick loop re-arms itself).
function makeClock() {
  let seq = 0;
  let now = 0;
  const scheduled = new Map(); // id -> { fn, time }
  return {
    schedule(fn, ms) {
      const id = ++seq;
      scheduled.set(id, { fn, time: now + ms });
      return id;
    },
    cancel(id) {
      scheduled.delete(id);
    },
    advance(ms) {
      const target = now + ms;
      let guard = 0;
      while (true) {
        if (guard++ > 100000) throw new Error("clock advance did not settle");
        let next = null;
        for (const [id, item] of scheduled) {
          if (item.time <= target && (next === null || item.time < next[1].time)) {
            next = [id, item];
          }
        }
        if (!next) break;
        scheduled.delete(next[0]);
        // Step the clock forward to this timer's fire time before running it, so
        // a callback that re-arms (tick loop) schedules relative to a correct now.
        now = next[1].time;
        next[1].fn();
      }
      now = target;
    },
    outstanding: () => scheduled.size,
  };
}

// Build a queue wired to a clock and a recorder that concatenates every reveal.
function makeQueue(opts = {}) {
  const clock = makeClock();
  const reveals = [];
  const q = createRevealQueue(
    Object.assign(
      {
        onReveal: (text) => reveals.push(text),
        schedule: clock.schedule,
        cancel: clock.cancel,
        tickMs: 40,
        charsPerTick: 12,
        maxBacklog: 300,
      },
      opts,
    ),
  );
  return { q, clock, reveals, revealed: () => reveals.join("") };
}

test("a single bursty push is revealed in several chunks, not all at once", () => {
  const { q, clock, reveals } = makeQueue();
  const text = "Gradient descent takes small steps downhill to shrink the loss.";
  q.push(text); // Claude-style: whole answer arrives at once
  clock.advance(2000);
  assert.ok(reveals.length >= 4, `expected a progressive reveal, got ${reveals.length} chunk(s)`);
});

test("everything pushed is revealed exactly once, in order", () => {
  const { q, clock, revealed } = makeQueue();
  const text = "The quick brown fox jumps over the lazy dog, and then some more text.";
  q.push(text);
  clock.advance(5000);
  assert.equal(revealed(), text);
});

test("each chunk is a few words, not the whole thing", () => {
  const { q, clock, reveals } = makeQueue();
  const text = "one two three four five six seven eight nine ten eleven twelve";
  q.push(text);
  clock.advance(5000);
  // No single chunk should swallow the entire answer.
  for (const c of reveals) {
    assert.ok(c.length < text.length, `a chunk revealed the whole answer at once: "${c}"`);
  }
});

test("finish() drains the rest, then fires the done callback once (after buffer empty)", () => {
  const { q, clock, revealed } = makeQueue();
  let doneCalls = 0;
  let pendingWhenDone = -1;
  q.push("Answer text that is still mid-typewriter when done arrives.");
  clock.advance(80); // let a little reveal happen, buffer not yet empty
  assert.ok(q.pendingLength() > 0, "precondition: buffer should still hold text");
  q.finish(() => {
    doneCalls += 1;
    pendingWhenDone = q.pendingLength();
  });
  clock.advance(5000);
  assert.equal(doneCalls, 1, "done callback must fire exactly once");
  assert.equal(pendingWhenDone, 0, "done callback must fire only after the buffer is drained");
  assert.equal(revealed(), "Answer text that is still mid-typewriter when done arrives.");
});

test("finish() with nothing pending fires the callback immediately", () => {
  const { q } = makeQueue();
  let called = false;
  q.finish(() => {
    called = true;
  });
  assert.equal(called, true, "empty finish should not wait on a tick");
});

test("a large backlog accelerates so it drains in a bounded number of ticks", () => {
  const { q, clock, revealed } = makeQueue();
  const big = "x".repeat(3000);
  q.push(big);
  let ticks = 0;
  // Advance one tick at a time and count how many it takes to fully drain.
  while (q.pendingLength() > 0 && ticks < 500) {
    clock.advance(40);
    ticks += 1;
  }
  assert.equal(revealed(), big);
  assert.ok(ticks < 60, `backlog should accelerate; took ${ticks} ticks for 3000 chars`);
});

test("progressive pushes (GPT-style trickle) reveal in order and stay drained", () => {
  const { q, clock, revealed } = makeQueue();
  const words = ["Hello ", "there ", "friend ", "how ", "are ", "you"];
  for (const w of words) {
    q.push(w);
    clock.advance(40);
  }
  clock.advance(2000);
  assert.equal(revealed(), words.join(""));
});

test("cancel() stops further reveals, clears the buffer, and blocks the done callback", () => {
  const { q, clock, revealed } = makeQueue();
  let doneCalled = false;
  q.push("This answer is aborted partway because the student switched chats.");
  clock.advance(80);
  const revealedSoFar = revealed();
  q.finish(() => {
    doneCalled = true;
  });
  q.cancel();
  clock.advance(5000);
  assert.equal(revealed(), revealedSoFar, "no reveals should happen after cancel()");
  assert.equal(q.pendingLength(), 0, "cancel() clears the buffer");
  assert.equal(doneCalled, false, "cancel() must not fire the done callback");
  assert.equal(clock.outstanding(), 0, "cancel() leaves no scheduled timer running");
});

test("empty / falsy pushes are ignored", () => {
  const { q, clock, reveals } = makeQueue();
  q.push("");
  q.push(null);
  q.push(undefined);
  clock.advance(1000);
  assert.equal(reveals.length, 0);
  assert.equal(q.pendingLength(), 0);
});
