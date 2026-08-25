"use strict";

// Client-side outage detector for the AskTIM chat.
//
// Problem it solves: when the tutor pipeline is down or unresponsive during a
// large course, students see a hanging/failing chat with no explanation and
// email support in bulk. This watches the outcomes of their own /api/chat
// sends and, once it's confident the service (not just one request) is down,
// shows the same "AskTIM is temporarily down" note automatically — then clears
// it automatically after a cooldown so a recovered service becomes usable again
// with no human in the loop.
//
// The hard part is telling an *isolated* failed message from a *real* outage.
// Two mechanisms do that, and neither is the DOM:
//
//   1. A consecutive-failure streak, reset by any success. One failed send
//      leaves the streak at 1 (handled by the existing retry toast, not this).
//      Only `threshold` infra failures *in a row* — with no success between —
//      are even considered. The student's next working message zeroes it, so a
//      one-off blip can never escalate.
//
//   2. A confirmation probe (`confirmOutage`) run once the streak is reached,
//      before anything is shown. Its job is to avoid blaming AskTIM for the
//      student's own dropped connection. Only a positive confirmation trips the
//      overlay; otherwise the streak is treated as isolated and reset.
//
// This module is deliberately free of `document`, `fetch`, and timers: every
// side effect (showing/hiding the overlay, the confirmation probe, the cooldown
// timer) is injected, so the state machine is unit-testable in Node. chat.js
// supplies the real browser-backed implementations.

/**
 * @param {object} deps
 * @param {number} [deps.threshold=3]  Consecutive infra failures before the
 *   confirmation probe runs. Success resets the count to 0.
 * @param {() => Promise<boolean>} deps.confirmOutage  Resolves true when this
 *   really looks like a service outage (vs. the client being offline). Only a
 *   true result trips the overlay.
 * @param {() => void} deps.showOverlay  Reveal the "AskTIM is down" note.
 * @param {() => void} deps.hideOverlay  Remove the note.
 * @param {(onElapsed: () => void) => (() => void)} deps.scheduleCooldown
 *   Start the auto-clear cooldown; call `onElapsed` when it fires. Returns a
 *   canceller (invoked if the outage is cleared earlier by a success).
 */
function createOutageMonitor(deps) {
  const {
    threshold = 3,
    confirmOutage,
    showOverlay,
    hideOverlay,
    scheduleCooldown,
  } = deps;

  let consecutiveFailures = 0;
  let isDown = false;
  let cancelCooldown = null;
  // Guards against a burst of failures firing several overlapping probes while
  // the first `confirmOutage` await is still in flight.
  let confirming = false;

  function trip() {
    isDown = true;
    consecutiveFailures = 0;
    showOverlay();
    cancelCooldown = scheduleCooldown(clearOutage);
  }

  function clearOutage() {
    if (!isDown) {
      return;
    }
    isDown = false;
    consecutiveFailures = 0;
    if (cancelCooldown) {
      cancelCooldown();
      cancelCooldown = null;
    }
    hideOverlay();
  }

  // A completed tutor turn is the strongest possible proof of life: clear the
  // streak, and if we'd shown the note, take it down immediately.
  function recordSuccess() {
    consecutiveFailures = 0;
    if (isDown) {
      clearOutage();
    }
  }

  // Record one infra-shaped failure (5xx/503, server error frame, empty stream,
  // network/timeout). Callers must NOT feed user errors (login required, message
  // too long, conversation limit) or intentional aborts here — those aren't
  // outages and would poison the streak.
  async function recordFailure() {
    // While the note is up the cooldown owns clearing it; further failed retries
    // shouldn't re-probe. And never let overlapping probes double-trip.
    if (isDown || confirming) {
      return;
    }
    consecutiveFailures += 1;
    if (consecutiveFailures < threshold) {
      return;
    }
    confirming = true;
    let outage = false;
    try {
      outage = await confirmOutage();
    } catch (_) {
      // A probe that itself errors is ambiguous; stay conservative and don't
      // blame AskTIM on the strength of a failed probe.
      outage = false;
    } finally {
      confirming = false;
    }
    // A concurrent success may have cleared things while we awaited.
    if (isDown) {
      return;
    }
    if (outage) {
      trip();
    } else {
      // Confirmed not-an-outage (e.g. the client is offline): treat the streak
      // as isolated so it doesn't linger and trip on the next single failure.
      consecutiveFailures = 0;
    }
  }

  return {
    recordSuccess,
    recordFailure,
    isDown: () => isDown,
    consecutiveFailures: () => consecutiveFailures,
  };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { createOutageMonitor };
} else if (typeof window !== "undefined") {
  window.createOutageMonitor = createOutageMonitor;
}
