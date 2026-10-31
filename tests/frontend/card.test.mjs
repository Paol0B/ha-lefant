import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const cardUrl = new URL("../../custom_components/lefant/frontend/lefant-vacuum-card.js", import.meta.url);

globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => undefined, define: () => {} };
globalThis.window = globalThis;
globalThis.document = { querySelector: () => null };

const { STRINGS, langOf, roomProgress, translate } = await import(cardUrl);

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
