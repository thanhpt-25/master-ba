// The review box of a phase (spec 15 section 7), shared by the Overview cards and the document preview.

import { confirmDialog, h } from "../dom.js";
import { t } from "../i18n.js";

const ITEM_PREFIX = /^\s*(DOC-[A-Z_]+-\d{4}#item\.\d+)\s*:\s*(.*)$/;

// One comment per line; a line may start with an item ref (spec 15 section 7).
export function parseComments(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(ITEM_PREFIX);
      return match ? { ref: match[1], text: match[2].trim() } : { ref: null, text: line };
    });
}

// `ctx`: { approve(stage), reject(stage, comments), toast, openQuestions: n }.
export function reviewBox(stage, ctx, { placeholderRef = "DOC-SRS-0001#item.3" } = {}) {
  const comments = h("textarea", {
    id: `reject-${stage.key}`,
    rows: "3",
    maxlength: "20000",
    spellcheck: "false",
    "aria-label": t("Comments for rejecting {phase}, one per line", { phase: stage.title }),
    placeholder: t("{ref}: Split this obligation into two requirements.", { ref: placeholderRef }),
  });
  const approve = async () => {
    const open = ctx.openQuestions ?? 0;
    const warning = open ? ` ${t("{n} customer question(s) are still open; they stay open and later phases may not decide them.", { n: open })}` : "";
    const ok = await confirmDialog({
      title: t("Approve {phase}?", { phase: stage.title }),
      message: `${t("The next phase can then start.")}${warning}`,
      confirmLabel: t("Approve"),
    });
    if (!ok) return;
    ctx.approve(stage.key).catch((e) => ctx.toast(e.message, "error"));
  };
  const reject = () => {
    const parsed = parseComments(comments.value);
    if (!parsed.length) return ctx.toast(t("Write at least one comment."), "error");
    ctx.reject(stage.key, parsed).catch((e) => ctx.toast(e.message, "error"));
  };
  return h(
    "div",
    { class: "review-box" },
    h("p", { class: "hint" }, t("Waiting for your review.")),
    h("button", { class: "primary", type: "button", onClick: approve }, t("Approve")),
    h("label", { class: "sr-only", for: `reject-${stage.key}` }, t("Comments for rejecting {phase}, one per line", { phase: stage.title })),
    comments,
    h("p", { class: "hint" }, t("One comment per line. Start a line with an item ref to tie it to that item.")),
    h("button", { type: "button", onClick: reject }, t("Reject with comments")),
  );
}
