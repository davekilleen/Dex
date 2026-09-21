"""A weak fuzzy person match must refuse rather than write to the wrong page.

Field report (2026-09-21): create_task was called with
people=["Jake Walpole", "Stephen Hender"]. There is no Jake Walpole page. The
resolver's best fuzzy candidate was Mark Wallace at 0.67, it resolved with no
ambiguity flag, and a Related Tasks row was written onto Mark Wallace's page.
Nothing errored.

That is worse than a visible failure. Person pages feed meeting prep, context
injection and the people index, so a wrong link propagates into later
briefings, and the task itself looks correctly created.

The existing guards cover ambiguity (several candidates) and near-ties (top two
within 0.05). Neither fires when there is exactly one weak candidate.
"""

from __future__ import annotations

import pytest

from core.mcp import work_server


def _person(name: str, score: float) -> dict:
    return {
        'name': name,
        'path': f"05-Areas/People/External/{name.replace(' ', '_')}.md",
        '_score': score,
    }


def test_the_reported_mismatch_is_refused() -> None:
    """Jake Walpole must not resolve to Mark Wallace."""
    assert not work_server._fuzzy_person_match_is_safe(
        'Jake Walpole', _person('Mark Wallace', 0.67)
    )


@pytest.mark.parametrize(
    ('query', 'name', 'score'),
    [
        ('Stephen Hendr', 'Stephen Hender', 0.96),
        ('Aaldert Oosthuzen', 'Aaldert Oosthuizen', 0.97),
        ('Jevgenijs Jelistratov', 'Jevgenijs Jelistratovs', 0.80),
        ('Sriran Rajan', 'Sriram Rajan', 0.92),
        ('Arvind Ananda', 'Arvind Anandam', 0.80),
    ],
)
def test_genuine_near_misses_still_resolve(query: str, name: str, score: float) -> None:
    """Real dictation and typo cases, measured on a live vault."""
    assert work_server._fuzzy_person_match_is_safe(query, _person(name, score))


def test_a_strong_score_with_a_different_given_name_is_refused() -> None:
    """The score alone is not enough; the given name has to agree."""
    assert not work_server._fuzzy_person_match_is_safe(
        'Robert Smithson', _person('Daphne Smithson', 0.85)
    )


def test_single_token_queries_fall_back_to_the_score() -> None:
    """A first-name-only query has no surname to compare, so score decides."""
    assert work_server._fuzzy_person_match_is_safe('Deepak', _person('Deepak Gupta', 0.9))
    assert not work_server._fuzzy_person_match_is_safe('Deepak', _person('Deepak Gupta', 0.4))


def test_a_missing_or_unparseable_score_is_refused() -> None:
    assert not work_server._fuzzy_person_match_is_safe('Someone', {'name': 'Some One'})
    assert not work_server._fuzzy_person_match_is_safe(
        'Someone', {'name': 'Some One', '_score': 'high'}
    )
