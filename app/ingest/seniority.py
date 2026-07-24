"""Seniority level inferred from a job title.

Title-based on purpose: most postings don't state explicit years (so the years
extractor is sparse), but the title almost always signals the level. We only need a
coarse label so a junior candidate can filter out roles above their level and the
student/intern roles they're not eligible for.
"""

from __future__ import annotations

import re

# Intern / working-student roles (often require current university enrolment).
_INTERN = re.compile(
    r"working student|werkstudent|\bintern(ship)?\b|praktikum|apprentice|"
    r"dual stud|graduate program|\btrainee\b|\bstudent\b|placement",
    re.IGNORECASE,
)
# Senior IC + management titles. Managers count as senior for an IC job seeker.
_SENIOR = re.compile(
    r"\bsenior\b|\bsr\.?\b|\bstaff\b|\bprincipal\b|\blead\b|head of|\bhead\b|"
    r"\bvp\b|vice president|\bdirector\b|\bchief\b|\bmanager\b|\bmgr\b",
    re.IGNORECASE,
)


def detect_seniority(title: str | None) -> str | None:
    """Return 'intern' or 'senior' when the title signals it, else None (mid/junior)."""
    if not title:
        return None
    if _INTERN.search(title):
        return "intern"
    if _SENIOR.search(title):
        return "senior"
    return None
