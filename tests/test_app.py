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


# The battery price widget is a flat SEK quote for a 10 kWh reference
# battery (see config.BATTERY_PRICE_REFERENCE_KWH), not a per-kWh rate --
# an advisor has a quote, not a rate card. These multiply a target
# per-kWh rate by 10 so the test's intent (cheap / expensive) stays
# readable without each call site repeating the reference size.
CHEAP_BATTERY_SEK = 1000 * 10     # 1 000 SEK/kWh equivalent -- pays back fast
EXPENSIVE_BATTERY_SEK = 25000 * 10  # 25 000 SEK/kWh equivalent -- never pays back


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


def test_other_battery_income_field_exists_and_defaults_to_zero():
    at = _run()
    field = _input(at, "support services")
    assert field.value == 0


def test_entering_other_battery_income_can_flip_a_no_to_a_yes():
    """The round-trip the No card's own suggestion promises: at the default
    price the card names an extra-income figure that would flip the verdict
    -- entering comfortably more than that must actually flip it."""
    at = _run()
    before = _headlines(at)
    assert "Battery: **No**" in before  # the default verdict, per the Test finding

    _input(at, "support services").set_value(5000.0)  # ample headroom over the ~884 needed
    at.run()
    assert not at.exception
    headlines = _headlines(at)
    assert headlines != before
    assert "Battery: **Yes" in headlines


# -- the battery verdict both ways ---------------------------------------------

def test_a_cheap_battery_is_recommended_with_a_size_and_no_qualifier():
    """Comfortably inside the warranty too, so there is nothing to disclose."""
    at = _run()
    _input(at, "Battery price").set_value(CHEAP_BATTERY_SEK)
    at.run()
    headlines = _headlines(at)
    assert "Battery: **Yes" in headlines
    assert "kWh" in headlines
    assert "**But:**" not in headlines


def test_an_expensive_battery_is_refused_but_still_names_the_best_candidate():
    """A bare "No" is useless to an advisor -- they need to know how far off
    it is before deciding whether to revisit it."""
    at = _run()
    _input(at, "Battery price").set_value(EXPENSIVE_BATTERY_SEK)
    at.run()
    headlines = _headlines(at)
    assert "Battery: **No**" in headlines
    assert "best case" in headlines.lower() or "saves enough" in headlines.lower()


def test_a_no_verdict_states_what_extra_income_would_flip_it():
    """**Test finding, 2026-10-06:** the old sentence here only ever fired to
    say "service life rescues this No" and was absent otherwise. Judging
    against the service life directly retired that message; this one takes
    its place and is normal for a 'No', not a rare qualifier -- it's the
    concrete number for the 'what would it take' conversation."""
    at = _run()
    _input(at, "Battery price").set_value(EXPENSIVE_BATTERY_SEK)
    at.run()
    headlines = _headlines(at)
    assert "Battery: **No**" in headlines
    assert "**But:**" in headlines
    assert "SEK/year" in headlines
    assert "Other battery income" in headlines


def test_a_battery_past_warranty_but_inside_service_life_is_a_yes_with_a_note():
    """Verified live: default price + the deduction lands the best size at 12
    years -- past the 10-year warranty, inside the 15-year service life. This
    is the exact case a 10-year-only verdict got wrong."""
    at = _run()
    at.checkbox[0].set_value(True)
    at.run()
    headlines = _headlines(at)
    assert "Battery: **Yes" in headlines
    assert "**But:**" in headlines
    assert "warranty" in headlines and "service life" in headlines
