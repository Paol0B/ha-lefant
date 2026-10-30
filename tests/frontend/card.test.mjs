import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const cardUrl = new URL("../../custom_components/lefant/frontend/lefant-vacuum-card.js", import.meta.url);

globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => undefined, define: () => {} };
globalThis.window = globalThis;
globalThis.document = { querySelector: () => null };

const { STRINGS, langOf, translate } = await import(cardUrl);

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
