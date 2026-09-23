"""Does this page say anything about that objective?

The question a run aimed at the objectives with no question has to answer
before it writes anything, and the reason it lives in its own module: the
answer is a pure function of two strings, so it can be tested without a
generator, without a database and without a network call.

The answer here is plain lexical overlap, not a model, and the modesty of that
tool is the point. It never decides that a question exists - only whether a page
is worth looking at for an objective. A bad guess therefore costs a page read
for nothing, or an objective reported as uncovered that a cleverer search would
have matched: a visible gap, which is what this feature exists to produce, and
never an invented question, which is what it must not.
"""

from __future__ import annotations

import re

#: Words too common to be evidence that a page is about an objective. Short and
#: bilingual on purpose: the material is Spanish, a certification syllabus often
#: is not, and a stopword list long enough to be interesting is one that starts
#: throwing away real terms.
_STOPWORDS = frozenset(
    "about and for from into that the their them then there these this using "
    "with when which como cuando para por que sobre una uno los las del desde "
    "entre esta este esto".split()
)

#: Shortest word taken as a term. Below this almost everything is an article or
#: a bare number, and a match on one of those is evidence of nothing.
_MIN_TERM_LENGTH = 4


def terms(text: str) -> frozenset[str]:
    """The meaningful words of ``text``, lowercased and stripped of plurals.

    Stripping plurals is the one piece of morphology worth having: without it
    "Search skillsets" shares nothing with a page writing "a skillset enriches
    documents", and the gap is reported as "no material covers this" while the
    notes sit right there.
    """
    words = re.findall(r"[^\W_]+", text.lower())
    return frozenset(
        word[:-1] if len(word) > _MIN_TERM_LENGTH and word.endswith("s") else word
        for word in words
        if len(word) >= _MIN_TERM_LENGTH and word not in _STOPWORDS
    )


__all__ = ["terms"]
