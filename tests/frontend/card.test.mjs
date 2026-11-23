import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const cardUrl = new URL("../../custom_components/lefant/frontend/lefant-vacuum-card.js", import.meta.url);

globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => undefined, define: () => {} };
globalThis.window = globalThis;
globalThis.document = { querySelector: () => null };

const { STRINGS, langOf, placeLabels, roomProgress, translate } = await import(cardUrl);

test("Italian for it and it-IT, English for any other language", () => {
  const lang = (language) => langOf({ locale: { language } });
  assert.equal(lang("it"), "it");
  assert.equal(lang("it-IT"), "it");
  assert.equal(lang("en"), "en");
  assert.equal(lang("de"), "en");
  assert.equal(langOf({ language: "it" }), "it");
  assert.equal(langOf(undefined), "en");
});

test("placeholders are filled", () => {
  assert.equal(translate("en", "clean_many", { n: 3 }), "Clean 3 rooms");
  assert.equal(translate("it", "clean_many", { n: 3 }), "Pulisci 3 stanze");
  assert.equal(translate("it", "editor.merge_ask", { a: "Kitchen", b: "Hall" }), "Unire Kitchen e Hall in una stanza sola?");
  assert.equal(translate("en", "status.charging"), "Charging");
  assert.equal(translate("en", "status.unknown_code"), undefined);
});

test("both languages have the same keys", () => {
  const keys = (node, prefix = "") => Object.entries(node).flatMap(([k, v]) =>
    v && typeof v === "object" && !Array.isArray(v) ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`]);
  assert.deepEqual(keys(STRINGS.en).sort(), keys(STRINGS.it).sort());
});

test("every key the card uses exists in both languages", () => {
  const source = readFileSync(cardUrl, "utf8");
  const direct = [...source.matchAll(/(?:_t\(|translate\([^,]+, )"([\w.]+)"/g)].map((m) => m[1]);
  const columns = [...source.matchAll(/"((\w+)\.\w+)"/g)].filter((m) => typeof STRINGS.en[m[2]] === "object").map((m) => m[1]);
  assert.ok(direct.length > 100 && columns.length > 50);
  for (const key of [...direct, ...columns]) {
    for (const lang of ["en", "it"]) assert.notEqual(translate(lang, key), undefined, `${lang}: ${key}`);
  }
});

test("labels of rooms side by side are pushed apart, the others stay put", () => {
  const rooms = [
    { id: 1, name: "Big bathroom", area: 7.9, label: [160, 38] },
    { id: 2, name: "Small bathroom", area: 4.2, label: [200, 38] },
    { id: 3, name: "Kitchen", area: 17.7, label: [300, 70] },
  ];
  for (const wide of [true, false]) {
    const spots = placeLabels(rooms, wide);
    assert.deepEqual(spots[3], [300, 70]);
    const [[x1, y1], [x2, y2]] = [spots[1], spots[2]];
    // apart along x (beyond half of both name widths) or along y (beyond one label height)
    const size = wide ? 8.5 : 11;
    const apart = Math.abs(x1 - x2) >= ((12 + 14) * size * 0.6 + 8) / 2 - 1e-9 || Math.abs(y1 - y2) >= (wide ? 31 : 23) - 1e-9;
    assert.ok(apart, `${wide}: ${spots[1]} ${spots[2]}`);
    assert.ok(x1 <= 160 && x2 >= 200 && y1 === 38 && y2 >= 38, "they move apart, never up");
  }
  assert.deepEqual(placeLabels([], true), {});
});

test("room in progress estimated from the area cleaned, in the order sent", () => {
  const areas = { 1: 15, 2: 8, 3: 4, 4: 16 };
  const states = (cleaned, repeats) => roomProgress([1, 2, 3, 4], areas, cleaned, repeats).map((p) => p.state);
  assert.deepEqual(states(0), ["current", "todo", "todo", "todo"]);
  assert.deepEqual(states(14), ["current", "todo", "todo", "todo"]);
  assert.deepEqual(states(20), ["done", "current", "todo", "todo"]);
  assert.deepEqual(states(28), ["done", "done", "done", "current"]);
  assert.deepEqual(states(60), ["done", "done", "done", "current"]);
  assert.deepEqual(states(20, 2), ["current", "todo", "todo", "todo"]);
  assert.equal(roomProgress([1, 5], areas, 10), null);
  assert.equal(roomProgress([1], areas, NaN), null);
  for (const lang of ["en", "it"]) {
    for (const state of ["done", "current", "todo"]) assert.notEqual(translate(lang, `job_room.${state}`), undefined);
    for (const key of ["job_estimate_hint", "estimated_room", "map_note_job"]) assert.notEqual(translate(lang, key), undefined);
  }
});

test("floor plan placed in meters from the dock", async () => {
  const { floorplanBox } = await import(cardUrl);
  const plan = { image: "/local/plan.svg", dark_image: "/local/plan-dark.svg", bounds: [-1, -0.5, 2, 1] };
  assert.deepEqual(floorplanBox(plan, [100, 50], false), { href: "/local/plan.svg", x: 80, y: 40, width: 60, height: 30 });
  assert.equal(floorplanBox(plan, [100, 50], true).href, "/local/plan-dark.svg");
  assert.equal(floorplanBox({ image: "/local/plan.svg", bounds: [0, 0, 1, 1] }, [0, 0], true).href, "/local/plan.svg");
  assert.equal(floorplanBox(undefined, [0, 0]), null);
  assert.equal(floorplanBox({ image: "/local/plan.svg", bounds: [1, 0, 0, 1] }, [0, 0]), null);
  assert.equal(floorplanBox({ image: "/local/plan.svg", bounds: [0, 0, "x", 1] }, [0, 0]), null);
  assert.equal(floorplanBox(plan, undefined), null);
});
