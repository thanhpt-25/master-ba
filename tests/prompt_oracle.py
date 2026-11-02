"""Frozen copy of the writer and QA user-message builders before spec 12 (oracle for Property 20).

Do not update this file when prompts change on purpose; a change to these strings without a
knowledge block is exactly what Property 20 must catch.
"""

from collections.abc import Sequence


def revision(
    previous_tag: str, previous_view: str, reason_line: str, listing: Sequence[str], closing: str
) -> str:
    items = "\n".join(f"- {f}" for f in listing)
    return (
        f"\n\n<{previous_tag}>\n{previous_view}\n</{previous_tag}>\n\n"
        f"{reason_line}\n{items}\n{closing}"
    )


def brd_user(numbered_intake: str, previous_view: str | None, feedback: Sequence[str]) -> str:
    user = f"<intake>\n{numbered_intake}\n</intake>"
    if previous_view is not None:
        user += revision(
            "previous_draft",
            previous_view,
            "The previous draft was rejected for these reasons:",
            feedback,
            "Return a corrected, complete draft.",
        )
    return user


def srs_user(brd_view: str, previous_view: str | None, feedback: Sequence[str]) -> str:
    user = f"<brd>\n{brd_view}\n</brd>"
    if previous_view is not None:
        user += revision(
            "previous_draft",
            previous_view,
            "The previous draft was rejected for these reasons:",
            feedback,
            "Return a corrected, complete SRS.",
        )
    return user


def design_user(srs_view: str, previous_view: str | None, feedback: Sequence[str]) -> str:
    user = f"<srs>\n{srs_view}\n</srs>"
    if previous_view is not None:
        user += revision(
            "previous_design",
            previous_view,
            "The previous design was sent back for these reasons:",
            feedback,
            "Return a corrected, complete design. Put the answer to every tester "
            "question into the description of the item it concerns and also list "
            "it in `answers`.",
        )
    return user


def tests_user(
    srs_view: str, design_view: str, previous_view: str | None, feedback: Sequence[str]
) -> str:
    user = f"<srs>\n{srs_view}\n</srs>\n\n<design>\n{design_view}\n</design>"
    if previous_view is not None:
        user += revision(
            "previous_tests",
            previous_view,
            "The previous tests were sent back for these reasons:",
            feedback,
            "Return corrected, complete tests.",
        )
    return user


def detail_user(basic_view: str, previous_view: str | None, feedback: Sequence[str]) -> str:
    user = f"<basic_design>\n{basic_view}\n</basic_design>"
    if previous_view is not None:
        user += revision(
            "previous_design",
            previous_view,
            "The previous detail design was sent back for these reasons:",
            feedback,
            "Return a corrected, complete detail design. Put the answer to every "
            "tester question into the spec of the item it concerns and also list "
            "it in `answers`.",
        )
    return user


def unit_tests_user(
    basic_view: str, detail_view: str, previous_view: str | None, feedback: Sequence[str]
) -> str:
    user = (
        f"<basic_design>\n{basic_view}\n</basic_design>\n\n"
        f"<detail_design>\n{detail_view}\n</detail_design>"
    )
    if previous_view is not None:
        user += revision(
            "previous_tests",
            previous_view,
            "The previous tests were sent back for these reasons:",
            feedback,
            "Return corrected, complete tests.",
        )
    return user


def qa_system(
    base: str, stage: str, checks: Sequence[tuple[str, str, str]], language_instruction: str
) -> str:
    listing = "\n".join(f"- {i} ({s}): {t}" for i, s, t in checks)
    return (
        f"{base}\n\n## Checklist for the {stage} stage\n\n{listing}\n\n"
        f"## Output language\n\n{language_instruction}"
    )


def qa_user(upstream: str, draft_view: str) -> str:
    return f"<upstream>\n{upstream}\n</upstream>\n\n<draft>\n{draft_view}\n</draft>"
