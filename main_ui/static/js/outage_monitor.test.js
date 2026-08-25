"use strict";

// Unit tests for the client-side outage state machine. Run with:
//   node --test main_ui/static/js/outage_monitor.test.js
// No dependencies — uses Node's built-in test runner and assert.

const test = require("node:test");
const assert = require("node:assert/strict");

const { createOutageMonitor } = require("./outage_monitor.js");

// Build a monitor with recording test doubles. `confirm` decides what the
// confirmation probe resolves to; `cooldown` captures the elapse callback so a
// test can fire the cooldown by hand instead of waiting on a real timer.
function makeMonitor({ threshold = 3, confirm = true } = {}) {
  const calls = { show: 0, hide: 0, confirmCalls: 0, cooldownScheduled: 0, cooldownCancelled: 0 };
  let fireCooldown = null;
  const monitor = createOutageMonitor({
    threshold,
    confirmOutage: async () => {
      calls.confirmCalls += 1;
      return typeof confirm === "function" ? confirm() : confirm;
    },
    showOverlay: () => {
      calls.show += 1;
    },
    hideOverlay: () => {
      calls.hide += 1;
    },
    scheduleCooldown: (onElapsed) => {
      calls.cooldownScheduled += 1;
      fireCooldown = onElapsed;
      return () => {
        calls.cooldownCancelled += 1;
      };
    },
  });
  return { monitor, calls, fireCooldown: () => fireCooldown && fireCooldown() };
}

test("a single failure does not probe or show the note", async () => {
  const { monitor, calls } = makeMonitor();
  await monitor.recordFailure();
  assert.equal(monitor.consecutiveFailures(), 1);
  assert.equal(monitor.isDown(), false);
  assert.equal(calls.confirmCalls, 0, "must not probe below threshold");
  assert.equal(calls.show, 0);
});

test("an isolated blip is cleared by the next success", async () => {
  const { monitor, calls } = makeMonitor();
  await monitor.recordFailure();
  await monitor.recordFailure(); // 2 in a row, still below threshold 3
  monitor.recordSuccess();
  assert.equal(monitor.consecutiveFailures(), 0, "success resets the streak");
  assert.equal(monitor.isDown(), false);
  // A later single failure must not immediately trip — the streak restarts.
  await monitor.recordFailure();
  assert.equal(calls.confirmCalls, 0);
  assert.equal(calls.show, 0);
});

test("threshold consecutive failures + confirmed outage shows the note", async () => {
  const { monitor, calls } = makeMonitor({ confirm: true });
  await monitor.recordFailure();
  await monitor.recordFailure();
  await monitor.recordFailure();
  assert.equal(calls.confirmCalls, 1, "probes exactly once, at threshold");
  assert.equal(monitor.isDown(), true);
  assert.equal(calls.show, 1);
  assert.equal(calls.cooldownScheduled, 1, "arms the auto-clear cooldown");
});

test("threshold reached but probe says not-an-outage does NOT show the note", async () => {
  const { monitor, calls } = makeMonitor({ confirm: false });
  await monitor.recordFailure();
  await monitor.recordFailure();
  await monitor.recordFailure();
  assert.equal(calls.confirmCalls, 1);
  assert.equal(monitor.isDown(), false, "client-offline style failures don't blame AskTIM");
  assert.equal(calls.show, 0);
  assert.equal(monitor.consecutiveFailures(), 0, "streak reset so it won't trip on the next single fail");
});

test("cooldown elapsing auto-clears the note", async () => {
  const { monitor, calls, fireCooldown } = makeMonitor({ confirm: true });
  await monitor.recordFailure();
  await monitor.recordFailure();
  await monitor.recordFailure();
  assert.equal(monitor.isDown(), true);
  fireCooldown();
  assert.equal(monitor.isDown(), false);
  assert.equal(calls.hide, 1);
});

test("a success while down clears the note early and cancels the cooldown", async () => {
  const { monitor, calls } = makeMonitor({ confirm: true });
  await monitor.recordFailure();
  await monitor.recordFailure();
  await monitor.recordFailure();
  assert.equal(monitor.isDown(), true);
  monitor.recordSuccess();
  assert.equal(monitor.isDown(), false);
  assert.equal(calls.hide, 1);
  assert.equal(calls.cooldownCancelled, 1);
});

test("failures while already down do not re-probe or re-show", async () => {
  const { monitor, calls } = makeMonitor({ confirm: true });
  await monitor.recordFailure();
  await monitor.recordFailure();
  await monitor.recordFailure();
  assert.equal(calls.show, 1);
  await monitor.recordFailure();
  await monitor.recordFailure();
  assert.equal(calls.confirmCalls, 1, "no further probes while the note is up");
  assert.equal(calls.show, 1, "note is not shown again");
});

test("a burst of concurrent failures at threshold trips only once", async () => {
  const { monitor, calls } = makeMonitor({ confirm: true });
  await monitor.recordFailure();
  await monitor.recordFailure();
  // Fire the threshold-th and a couple more without awaiting between them.
  await Promise.all([
    monitor.recordFailure(),
    monitor.recordFailure(),
    monitor.recordFailure(),
  ]);
  assert.equal(calls.confirmCalls, 1, "the in-flight-probe guard prevents double probes");
  assert.equal(calls.show, 1);
});

test("re-trips after a recovery when failures resume", async () => {
  const { monitor, calls, fireCooldown } = makeMonitor({ confirm: true });
  await monitor.recordFailure();
  await monitor.recordFailure();
  await monitor.recordFailure();
  assert.equal(monitor.isDown(), true);
  fireCooldown(); // auto-clear
  assert.equal(monitor.isDown(), false);
  // Service still broken — a fresh streak must be able to trip again.
  await monitor.recordFailure();
  await monitor.recordFailure();
  await monitor.recordFailure();
  assert.equal(monitor.isDown(), true);
  assert.equal(calls.show, 2);
  assert.equal(calls.confirmCalls, 2);
});
