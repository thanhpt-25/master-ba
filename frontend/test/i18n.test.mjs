// Every word a view shows has a Japanese entry, and the catalog holds no stale entry (spec 19 section 15).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { JA } from "../i18n-ja.js";

const ROOT = new URL("..", import.meta.url).pathname;
const CALL = /\b(?:t|tr|N_)\(\s*"((?:[^"\\]|\\.)*)"/g;

function sources() {
  const files = ["app.js", "api.js", "dom.js", "i18n.js", "charts.js", "palette.js"].map((f) => join(ROOT, f));
  for (const f of readdirSync(join(ROOT, "views"))) if (f.endsWith(".js")) files.push(join(ROOT, "views", f));
  return files;
}

function used() {
  const keys = new Map();
  for (const file of sources()) {
    for (const match of readFileSync(file, "utf8").matchAll(CALL)) keys.set(JSON.parse(`"${match[1]}"`), file);
  }
  return keys;
}

test("every UI string has a Japanese translation", () => {
  const missing = [...used().keys()].filter((k) => !(k in JA));
  assert.deepEqual(missing, []);
});

test("the Japanese catalog has no entry that no view uses", () => {
  const keys = used();
  const stale = Object.keys(JA).filter((k) => !keys.has(k));
  assert.deepEqual(stale, []);
});

test("translations keep every {placeholder} of the English text", () => {
  const names = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
  const broken = Object.entries(JA).filter(([en, ja]) => names(en).join() !== names(ja).join()).map(([en]) => en);
  assert.deepEqual(broken, []);
});

// A parameter or local named `t` hides the translator, so a later `t("…")` throws
// "t is not a function" (the template viewer did this with `open(company, t)`).
test("no source shadows the translator t", () => {
  const SHADOW = /[(,]\s*t\s*\)\s*=>|[(,]\s*t\s*,[^()]*\)\s*=>|(?:^|[^\w.$])t\s*=>|\b(?:const|let|var)\s+t\s*=|function\s*\w*\s*\(\s*(?:[^)]*,\s*)?t\s*[,)=]/m;
  const offenders = [];
  for (const file of sources()) {
    readFileSync(file, "utf8").split("\n").forEach((line, i) => {
      if (SHADOW.test(line)) offenders.push(`${file.slice(ROOT.length)}:${i + 1}`);
    });
  }
  assert.deepEqual(offenders, []);
});
