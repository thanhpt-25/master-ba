// Dialog tests: confirmDialog resolve paths, focus trap, and shortcutsDialog.
// Run with: node --test  (from the frontend directory)
import { test } from "node:test";
import assert from "node:assert/strict";
import { install } from "./dom-shim.js";

const env = install();
const dom = await import("../dom.js");

function overlay() {
  return document.body.querySelector(".dialog-overlay");
}

test("confirmDialog mounts an alertdialog with the title and message", async () => {
  env.reset();
  const p = dom.confirmDialog({ title: "Delete?", message: "This is permanent." });
  const card = overlay().querySelector(".dialog");
  assert.ok(card);
  assert.equal(card.getAttribute("role"), "alertdialog");
  assert.equal(card.getAttribute("aria-modal"), "true");
  assert.match(card.textContent, /Delete\?/);
  assert.match(card.textContent, /permanent/);
  // clean up: cancel
  card.querySelectorAll("button")[0].click();
  assert.equal(await p, false);
});

test("confirmDialog resolves true when confirm is pressed", async () => {
  env.reset();
  const p = dom.confirmDialog({ title: "Go?", confirmLabel: "Yes" });
  const buttons = overlay().querySelectorAll(".dialog-actions button");
  const confirm = [...buttons].find((b) => b.textContent === "Yes");
  confirm.click();
  assert.equal(await p, true);
  assert.equal(overlay(), null, "overlay is removed after confirm");
});

test("confirmDialog resolves false when cancel is pressed", async () => {
  env.reset();
  const p = dom.confirmDialog({ title: "Go?", cancelLabel: "No" });
  const cancel = [...overlay().querySelectorAll("button")].find((b) => b.textContent === "No");
  cancel.click();
  assert.equal(await p, false);
  assert.equal(overlay(), null);
});

test("confirmDialog resolves false and closes on Escape", async () => {
  env.reset();
  const p = dom.confirmDialog({ title: "Go?" });
  assert.ok(overlay());
  const event = env.fireKey("keydown", "Escape");
  assert.equal(await p, false);
  assert.ok(event.defaultPrevented);
  assert.equal(overlay(), null);
});

test("confirmDialog danger flag marks the confirm button", async () => {
  env.reset();
  const p = dom.confirmDialog({ title: "Delete?", confirmLabel: "Delete", danger: true });
  const danger = [...overlay().querySelectorAll("button")].find((b) => b.className.includes("danger"));
  assert.ok(danger, "danger button present");
  assert.equal(danger.textContent, "Delete");
  danger.click();
  assert.equal(await p, true);
});

test("opening a second dialog closes the first", async () => {
  env.reset();
  const first = dom.confirmDialog({ title: "First" });
  dom.shortcutsDialog([{ keys: "?", description: "help" }]);
  // exactly one overlay remains
  assert.equal(document.body.querySelectorAll(".dialog-overlay").length, 1);
  // the first promise settled false when it was force-closed
  assert.equal(await first, false);
});

test("shortcutsDialog lists every shortcut and closes on its button", () => {
  env.reset();
  dom.shortcutsDialog([
    { keys: "?", description: "Show help" },
    { keys: "P", description: "Pause polling" },
  ]);
  const card = overlay().querySelector(".dialog.shortcuts");
  assert.ok(card);
  assert.equal(card.getAttribute("aria-modal"), "true");
  assert.equal(card.querySelectorAll(".shortcut-list dt").length, 2);
  assert.match(card.textContent, /Pause polling/);
  const close = [...card.querySelectorAll("button")].find((b) => b.textContent === "Close");
  close.click();
  assert.equal(overlay(), null);
});

test("dialog focus trap wraps Tab within the card's focusable elements", () => {
  env.reset();
  dom.confirmDialog({ title: "Go?", confirmLabel: "Yes", cancelLabel: "No" });
  const card = overlay().querySelector(".dialog");
  const buttons = card.querySelectorAll("button");
  const first = buttons[0];
  const last = buttons[buttons.length - 1];
  // Move focus to the last, Tab forward should wrap to first.
  last.focus();
  const fwd = env.fireKey("keydown", "Tab");
  assert.ok(fwd.defaultPrevented);
  assert.equal(document.activeElement, first);
  // Move focus to the first, Shift+Tab should wrap to last.
  first.focus();
  const back = env.fireKey("keydown", "Tab", { shiftKey: true });
  assert.ok(back.defaultPrevented);
  assert.equal(document.activeElement, last);
});
