/* Original BCA-lite Quiz state machine. No network, storage or external libraries. */
(() => {
  "use strict";
  function createQuiz({seed = 1, now = () => performance.now(), changed = () => {}} = {}) {
    if (!Number.isInteger(seed) || seed < 0 || seed > 0xffffffff) throw Error("invalid seed");
    let randomState = seed >>> 0, lastTime = -Infinity;
    let round = 0n, score = 0n, question = -1, options = [], selected = null;
    let selectedRound = null, submitted = false, started = 0;
    const events = [];
    function time() {
      const value = now();
      if (!Number.isFinite(value) || value < lastTime) throw Error("clock must be monotonic");
      lastTime = value;
      return value;
    }
    function random(n) {
      randomState = (Math.imul(randomState, 1664525) + 1013904223) >>> 0;
      return Math.floor(randomState / 4294967296 * n);
    }
    function mark() { return round.toString().padStart(6, "0"); }
    function snapshot() {
      return {round: mark(), question, options: options.slice(), score: score.toString(),
        selected, selectedRound, submitted, started, timeLeft: Math.max(0, 10 - (time() - started) / 1000)};
    }
    function next(reason) {
      // Uniform choice among the nine other digits, without an unbounded retry loop.
      let number = random(question < 0 ? 10 : 9);
      if (question >= 0 && number >= question) number++;
      question = number;
      const remaining = Array.from({length: 10}, (_, n) => n).filter(n => n !== question);
      options = [question];
      for (let i = 0; i < 3; i++) options.push(remaining.splice(random(remaining.length), 1)[0]);
      for (let i = 3; i > 0; i--) {
        const j = random(i + 1);
        [options[i], options[j]] = [options[j], options[i]];
      }
      round++;
      selected = selectedRound = null;
      submitted = false;
      started = time();
      events.push({kind: "round", reason, round: mark(), at: started, score: score.toString()});
      if (events.length > 256) events.shift();
      changed(snapshot()); // Synchronous DOM publication of the new question.
    }
    function tick() {
      if (time() - started >= 10000) { next("timeout"); return true; }
      return false;
    }
    function select(index, visibleRound) {
      tick();
      if (!Number.isInteger(index) || index < 0 || index > 3 || visibleRound !== mark()) return false;
      selected = index;
      selectedRound = mark();
      changed(snapshot());
      return true;
    }
    function confirm(visibleRound) {
      tick();
      if (visibleRound !== mark() || selected === null || selectedRound !== mark() || submitted) return false;
      submitted = true;
      const correct = options[selected] === question;
      score += correct ? 1n : -1n;
      events.push({kind: "submit", round: mark(), selected, correct, score: score.toString(), at: time()});
      next("submit");
      return true;
    }
    next("initial");
    return {snapshot, tick, select, confirm, events,
      // Exposed by the page only when test mode is explicitly selected.
      testSet({newScore, newRound} = {}) {
        if (newScore !== undefined) {
          if (!/^-?\d+$/.test(newScore)) throw Error("integer score required");
          score = BigInt(newScore);
        }
        if (newRound !== undefined) {
          if (!/^\d+$/.test(newRound) || BigInt(newRound) <= round) throw Error("round must increase");
          round = BigInt(newRound);
          selected = selectedRound = null;
        }
        changed(snapshot());
      }};
  }
  if (typeof module !== "undefined" && module.exports) module.exports = {createQuiz};
  else window.BCAQuizEngine = {createQuiz};
})();
