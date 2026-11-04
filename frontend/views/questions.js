import { badge, clear, confirmDialog, empty, field, h } from "../dom.js";

const ORIGIN = { agent: "Question", qa_blocker: "QA objection" };

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
      toast(done.dr ? `Recorded as ${done.dr.id}` : "Withdrawn");
      await draw();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function form(q) {
    const answer = h("textarea", { id: `answer-${q.id}`, rows: "3", maxlength: "2000", spellcheck: "false", required: true });
    const source = h("input", { type: "text", id: `source-${q.id}`, name: "source", maxlength: "500", autocomplete: "off", placeholder: "Tanaka, meeting 2026-11-02…" });
    const answerField = field("Answer", answer, "Recorded as an approved decision record that every later run uses.");
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
      const ok = await confirmDialog({ title: `Withdraw ${q.id}?`, message: "It is closed without a decision.", confirmLabel: "Withdraw", danger: true });
      if (ok) act(`${q.id}/withdraw`);
    };
    return h(
      "form",
      {
        class: "q-answer",
        onSubmit: (event) => {
          event.preventDefault();
          if (!answer.value.trim()) {
            setError("Write an answer before recording it.");
            answer.focus();
            return;
          }
          return act(`${q.id}/answer`, { answer: answer.value, source: source.value.trim() || null });
        },
      },
      answerField,
      field("Who said it, and where (optional)", source),
      h("div", { class: "toolbar" },
        h("button", { type: "submit", class: "primary" }, "Record answer"),
        h("button", { type: "button", onClick: withdraw }, "Withdraw"),
      ),
    );
  }

  function card(q) {
    return h(
      "article",
      { class: "panel question", "aria-labelledby": `q-${q.id}` },
      h("div", { class: "vcard-head" }, h("h2", { id: `q-${q.id}` }, h("code", {}, q.id), " ", ORIGIN[q.origin]), badge(q.status)),
      h("p", { class: "prose" }, q.text),
      q.refs.length ? h("p", {}, h("strong", {}, "About: "), q.refs.map((r) => refLink(pid, r))) : null,
      h("p", { class: "muted" }, `Raised by ${q.stage} run `, h("code", {}, q.run_id), ` on ${q.asked_on}`),
      q.status === "answered"
        ? h(
            "div",
            {},
            h("p", { class: "prose" }, h("strong", {}, "Answer: "), q.answer),
            h("p", { class: "muted" }, `Recorded by ${q.answered_by} on ${q.answered_on}${q.source ? ` · ${q.source}` : ""} · `, h("a", { href: `#/p/${pid}/drs/${q.dr_id}` }, h("code", {}, q.dr_id))),
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
      h("h1", {}, "Questions for the customer"),
      h("p", { class: "muted" }, `${open.length} open, ${closed.length} closed. Agents record here what only the customer can settle; they do not wait for the answer.`),
      ...(all.length ? [...open, ...closed].map(card) : [empty("No questions yet.")]),
    );
  }

  await draw();
}
