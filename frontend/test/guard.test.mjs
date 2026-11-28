import { test } from "node:test";
import assert from "node:assert/strict";
import { findingsNote, parseTerms } from "../views/guard.js";

test("findingsNote counts the kinds and is null when nothing was found", () => {
  assert.equal(findingsNote([]), null);
  assert.equal(findingsNote(undefined), null);
  const note = findingsNote([{ kind: "email" }, { kind: "email" }, { kind: "phone" }]);
  assert.match(note, /3/);
  assert.match(note, /×2/);
});

test("parseTerms splits lines and commas, drops short words and repeats", () => {
  assert.deepEqual(parseTerms("ABC銀行\nabc銀行, X,  Contoso 、Fabrikam"), ["ABC銀行", "Contoso", "Fabrikam"]);
});
