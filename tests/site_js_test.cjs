"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

function classList(...initial) {
  const classes = new Set(initial);
  return {
    add: (...names) => names.forEach((name) => classes.add(name)),
    contains: (name) => classes.has(name),
    remove: (...names) => names.forEach((name) => classes.delete(name)),
  };
}

test("forecast rollovers advance the hero, rows, and counts", () => {
  const RealDate = Date;
  let offset = 60 * 60 * 1000;
  class ShiftedDate extends RealDate {
    constructor(...args) {
      super(...(args.length ? args : [RealDate.now() + offset]));
    }

    static now() {
      return RealDate.now() + offset;
    }
  }

  const targets = [30, 120].map((minutes) =>
    new RealDate(RealDate.now() + minutes * 60 * 1000).toISOString(),
  );
  const headings = targets.map(() => ({
    firstChild: { nodeType: 3, textContent: "Expected " },
  }));
  const timeNodes = targets.map((target) => ({
    dateTime: target,
    textContent: target,
    cloneNode() {
      return { ...this };
    },
  }));
  const rows = targets.map((_, index) => ({
    classList: classList(),
    querySelector: (selector) =>
      ({ h4: headings[index], time: timeNodes[index] })[selector] ?? null,
  }));
  const countdowns = targets.map((target, index) => ({
    dataset: { countdown: target },
    textContent: "",
    title: "",
    closest: () => rows[index],
  }));
  const futureValue = { textContent: "2" };
  const recentValue = { textContent: "0" };
  const heroLabel = { textContent: "Next modelled Earth arrival · last check" };
  const heroDetail = { textContent: "Predicted Kp 6" };
  const heroValue = {
    child: timeNodes[0],
    replaceChildren(child) {
      this.child = child;
    },
  };
  const hero = {
    dataset: { heroArrival: targets[0] },
    classList: classList("hero-signal--arrival"),
    querySelector: (selector) =>
      ({ small: heroLabel, p: heroDetail, strong: heroValue })[selector] ?? null,
  };
  const healthLabel = { textContent: "Last check healthy" };
  const health = {
    dataset: {
      generated: new RealDate(RealDate.now() + offset).toISOString(),
      freshHours: "3",
    },
    classList: classList("feed-chip--healthy"),
    querySelector: () => healthLabel,
  };

  global.Date = ShiftedDate;
  global.Node = { TEXT_NODE: 3 };
  let intervalCallback = null;
  global.window = {
    setInterval: (callback) => {
      intervalCallback = callback;
      return 0;
    },
  };
  global.document = {
    querySelectorAll: (selector) => (selector === "[data-countdown]" ? countdowns : []),
    querySelector: (selector) =>
      ({
        "[data-feed-health]": health,
        "[data-metric='future'] dd": futureValue,
        "[data-metric='recent'] dd": recentValue,
        "[data-hero-arrival]": hero,
      })[selector] ?? null,
  };

  try {
    require("../src/nasa_space_weather/site_assets/site.js");
    assert.equal(headings[0].firstChild.textContent, "Forecast time ");
    assert.equal(headings[1].firstChild.textContent, "Expected ");
    assert.match(countdowns[0].textContent, /ago$/);
    assert.match(countdowns[1].textContent, /^in /);
    assert.equal(hero.dataset.heroArrival, targets[1]);
    assert.equal(heroValue.child.dateTime, targets[1]);
    assert.equal(heroLabel.textContent, "Next modelled Earth arrival · last check");
    assert.equal(heroDetail.textContent, "Another future forecast remains in the CME outlook.");
    assert.equal(futureValue.textContent, "1");
    assert.equal(recentValue.textContent, "1");

    offset = 3 * 60 * 60 * 1000;
    intervalCallback();
    assert.equal(headings[1].firstChild.textContent, "Forecast time ");
    assert.equal(heroLabel.textContent, "Modelled arrival time · last check");
    assert.equal(heroDetail.textContent, "Forecast time passed; awaiting the next hourly check.");
    assert.equal(futureValue.textContent, "0");
    assert.equal(recentValue.textContent, "2");
  } finally {
    global.Date = RealDate;
    delete global.Node;
    delete global.window;
    delete global.document;
  }
});
