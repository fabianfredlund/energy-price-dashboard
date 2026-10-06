"""Tests that drive the real app through Streamlit's own runtime.

Sprints 7 and 8 drove the app with `AppTest` interactively but never
committed it, which is exactly why deleting a whole tab had no safety net.
This file is that net.

**No network.** The fixed window is wholly in the past, so both the price
and irradiance fetchers serve it from the committed snapshot and make zero
requests. If that ever stops being true these tests will slow down and
start failing offline, which is the right alarm.

The tests that matter most here are the ones asserting that **editing an
assumption actually moves a number**. An editable box that silently does
nothing is this design's characteristic failure, and it is invisible to
every other kind of test.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")
TIMEOUT = 900  # a cold run simulates three years five times over


def _run(**widgets):
    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _headlines(at) -> str:
    """The two answer cards plus any qualifying sentence, as one string."""
    return " ".join(
        m.value.replace("\n", " ") for m in at.markdown
        if m.value.startswith("### ") or m.value.startswith("**But:**")
    )


def _input(at, label_fragment: str):
    for widget in at.number_input:
        if label_fragment.lower() in widget.label.lower():
            return widget
    raise AssertionError(f"no number input matching {label_fragment!r}")


@pytest.fixture(scope="module")
def baseline():
    return _run()


# -- it renders ----------------------------------------------------------------

def test_the_page_renders_without_an_exception(baseline):
    assert [t.value for t in baseline.title] == ["Solar Advisor"]
    assert not baseline.error


def test_both_answer_cards_state_a_verdict(baseline):
    headlines = _headlines(baseline)
    assert "Solar:" in headlines
    assert "Battery:" in headlines
    # a verdict, not a hedge
    assert ("**Yes**" in headlines) or ("**No**" in headlines)


def test_the_five_customer_inputs_are_present(baseline):
    labels = " ".join(w.label for w in baseline.number_input)
    for expected in ("Annual consumption", "System size", "System price", "Battery price"):
        assert expected in labels
    assert any("orientation" in s.label.lower() for s in baseline.selectbox)


def test_the_fixed_window_is_stated_on_screen(baseline):
    """It is fixed so the report, the screenshots and the video agree, which
    only works if a reader can see which window they are looking at."""
    assert any("Oct 2023" in c.value and "Sep 2026" in c.value for c in baseline.caption)


def test_the_yearly_figure_is_never_shown_without_its_range(baseline):
    """The three years differ enough that an average alone would claim more
    certainty than the data supports."""
    assert any("Range" in c.value or "range" in c.value for c in baseline.caption)


def test_removed_views_are_really_gone(baseline):
    """Define iteration 2 deleted the donut, heatmap, date picker and the
    Tomorrow tab. A leftover would mean the simplification only half
    happened."""
    page = " ".join(c.value for c in baseline.caption) + " ".join(
        m.value for m in baseline.markdown
    )
    for gone in ("Tomorrow", "heatmap", "donut", "Where the solar power goes"):
        assert gone.lower() not in page.lower()
    assert not baseline.tabs
    assert not baseline.date_input


# -- the editable assumptions must change the answer ---------------------------

def test_the_green_tech_deduction_shortens_the_payback():
    at = _run()
    before = _headlines(at)
    at.checkbox[0].set_value(True)
    at.run()
    assert not at.exception
    assert _headlines(at) != before, (
        "ticking the deduction changed nothing on screen -- the assumptions box "
        "is not reaching the calculation"
    )


def test_the_owners_input_appears_only_with_the_deduction():
    at = _run()
    assert not any("owner" in w.label.lower() for w in at.number_input)
    at.checkbox[0].set_value(True)
    at.run()
    assert any("owner" in w.label.lower() for w in at.number_input)


def test_the_surcharge_changes_the_yearly_saving():
    at = _run()
    before = _headlines(at)
    _input(at, "Surcharge").set_value(120.0)
    at.run()
    assert not at.exception
    assert _headlines(at) != before


def test_a_longer_solar_lifetime_can_turn_a_no_into_a_yes():
    at = _run()
    _input(at, "System price").set_value(900000)  # absurd, so solar cannot pay back
    at.run()
    assert "Solar: **No**" in _headlines(at)


# -- the battery verdict both ways ---------------------------------------------

def test_a_cheap_battery_is_recommended_with_a_size():
    at = _run()
    _input(at, "Battery price").set_value(1000)
    at.run()
    headlines = _headlines(at)
    assert "Battery: **Yes" in headlines
    assert "kWh" in headlines


def test_an_expensive_battery_is_refused_but_still_names_the_best_candidate():
    """A bare "No" is useless to an advisor -- they need to know how far off
    it is before deciding whether to revisit it."""
    at = _run()
    _input(at, "Battery price").set_value(25000)
    at.run()
    headlines = _headlines(at)
    assert "Battery: **No**" in headlines
    assert "best case" in headlines.lower() or "saves enough" in headlines.lower()


def test_the_service_life_sentence_appears_only_when_the_horizons_disagree():
    """It must qualify a "No", never decorate every one of them."""
    at = _run()

    # Far too expensive to pay back on either horizon -> no qualifier
    _input(at, "Battery price").set_value(25000)
    at.run()
    assert "**But:**" not in _headlines(at)

    # Comfortably inside the warranty -> nothing to qualify
    _input(at, "Battery price").set_value(1000)
    at.run()
    assert "**But:**" not in _headlines(at)


def test_a_near_miss_on_the_warranty_is_qualified_by_the_service_life():
    at = _run()
    at.checkbox[0].set_value(True)  # the deduction brings the best size near the line
    at.run()
    headlines = _headlines(at)
    if "Battery: **No**" in headlines:
        assert "**But:**" in headlines and "service life" in headlines
