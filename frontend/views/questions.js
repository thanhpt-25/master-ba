import { badge, clear, confirmDialog, empty, field, h, pageHeader } from "../dom.js";
import { N_, t } from "../i18n.js";

const ORIGIN = { agent: N_("Question"), qa_blocker: N_("QA objection") };
export const STAGE_NAMES = {
  BRD: N_("BRD"),
  SRS: N_("SRS"),
  BASIC_DESIGN: N_("Basic Design"),
  DETAIL_DESIGN: N_("Detail Design"),
  TEST_IT: N_("Integration tests (IT)"),
  TEST_ST: N_("System tests (ST)"),
  TEST_UT: N_("Unit tests (UT)"),
  TEST_UAT: N_("UAT"),
};

function refLink(pid, ref) {
  const chip = h("code", { class: "chip" }, ref);
  if (/^REQ-\d{4}$/.test(ref)) return h("a", { href: `#/p/${pid}/trace/${ref}` }, chip);
  const doc = ref.match(/^(DOC-[A-Z_]+-\d{4})#item\.\d+$/);
  return doc ? h("a", { href: `#/p/${pid}/documents/${doc[1]}` }, chip) : chip;
}

export async function render({ main, api, params, me, toast }) {
  const pid = params.pid;
  const canAct = ["approver", "admin"].includes(me.role);

  async function act(path, body) {
    try {
      const done = await api.post(`/projects/${pid}/questions/${path}`, body);
      const affected = done.dr?.affected_documents?.length ?? 0;
      const note = done.job ? t(": updating the affected documents") : affected ? "" : t(": a fact for later runs, no stored document is affected");
      toast(done.dr ? `${t("Recorded as {id}", { id: done.dr.id })}${note}` : t("Withdrawn"));
      if (done.propagation_note) toast(done.propagation_note, "error");
      await draw();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function form(q) {
    const answer = h("textarea", { id: `answer-${q.id}`, rows: "3", maxlength: "2000", spellcheck: "false", required: true });
    const source = h("input", { type: "text", id: `source-${q.id}`, name: "source", maxlength: "500", autocomplete: "off", placeholder: t("Tanaka, meeting 2026-11-02…") });
    const answerField = field(t("Answer"), answer, t("Recorded as an approved decision record that every later run uses. When it reaches a stored document, that document is updated (automatically in projects set to automatic updates)."));
    const setError = (msg) => {
      answerField.classList.toggle("invalid", Boolean(msg));
      answerField.querySelector(".field-error")?.remove();
      if (msg) {
        answer.setAttribute("aria-invalid", "true");
        answerField.append(h("p", { class: "field-error", role: "alert" }, msg));
      } else {
        answer.removeAttribute("aria-invalid");
      }
    };
    answer.addEventListener("input", () => { if (answer.value.trim()) setError(null); });
    const withdraw = async () => {
      const ok = await confirmDialog({ title: t("Withdraw {id}?", { id: q.id }), message: t("It is closed without a decision."), confirmLabel: t("Withdraw"), danger: true });
      if (ok) act(`${q.id}/withdraw`);
    };
    return h(
      "form",
      {
        class: "q-answer",
        onSubmit: (event) => {
          event.preventDefault();
          if (!answer.value.trim()) {
            setError(t("Write an answer before recording it."));
            answer.focus();
            return;
          }
          return act(`${q.id}/answer`, { answer: answer.value, source: source.value.trim() || null });
        },
      },
      answerField,
      field(t("Who said it, and where (optional)"), source),
      h("div", { class: "toolbar" },
        h("button", { type: "submit", class: "primary" }, t("Record answer")),
        h("button", { type: "button", onClick: withdraw }, t("Withdraw")),
      ),
    );
  }

  function card(q) {
    return h(
      "article",
      { class: "panel question", "aria-labelledby": `q-${q.id}` },
      h("div", { class: "vcard-head" }, h("h2", { id: `q-${q.id}` }, h("code", {}, q.id), " ", t(ORIGIN[q.origin])), badge(q.status)),
      h("p", { class: "prose" }, q.text),
      q.refs.length ? h("p", {}, h("strong", {}, t("About: ")), q.refs.map((r) => refLink(pid, r))) : null,
      h("p", { class: "muted" }, t("Raised by the {stage} run", { stage: t(STAGE_NAMES[q.stage] ?? q.stage) }), " ", h("code", {}, q.run_id), ` · ${q.asked_on}`),
      q.status === "answered"
        ? h(
            "div",
            {},
            h("p", { class: "prose" }, h("strong", {}, t("Answer: ")), q.answer),
            h("p", { class: "muted" }, `${t("Recorded by {name} on {date}", { name: q.answered_by, date: q.answered_on })}${q.source ? ` · ${q.source}` : ""} · `, h("a", { href: `#/p/${pid}/drs/${q.dr_id}` }, h("code", {}, q.dr_id))),
          )
        : null,
      q.status === "open" && canAct ? form(q) : null,
    );
  }

  async function draw() {
    const all = await api.get(`/projects/${pid}/questions`);
    const open = all.filter((q) => q.status === "open");
    const closed = all.filter((q) => q.status !== "open");
    clear(main).append(
      pageHeader(t("Questions for the customer"), t("{open} open, {closed} closed. A QA blocker pauses its run until you answer or withdraw it; other questions remain informational.", { open: open.length, closed: closed.length })),
      ...(all.length ? [...open, ...closed].map(card) : [empty(t("No questions yet."))]),
    );
  }

  await draw();
}
