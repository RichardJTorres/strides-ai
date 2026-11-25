"""The planning principles reach both planners (chat coach and plan generation), endurance only."""

import pytest

from strides_ai.coach import build_system
from strides_ai.coaching_principles import PLANNING_PRINCIPLES, planning_principles
from strides_ai.plan_generation import plan_generation_system_prompt


@pytest.mark.parametrize("mode", ["running", "cycling", "hybrid"])
def test_endurance_coach_and_planner_get_the_principles(mode):
    assert "## Planning Principles" in str(build_system("", [], mode=mode))
    assert PLANNING_PRINCIPLES in plan_generation_system_prompt(mode=mode)


def test_lifting_gets_no_endurance_principles():
    assert planning_principles("lifting") == ""
    assert "## Planning Principles" not in str(build_system("", [], mode="lifting"))
    assert "## Planning Principles" not in plan_generation_system_prompt(mode="lifting")


def test_principles_start_from_proven_level_and_treat_off_weeks_as_down_weeks():
    text = PLANNING_PRINCIPLES
    assert "proven weekly level" in text
    assert "An off week already is the down week" in text
    assert "longest run of the last 30 days" in text
    assert "advisory" in text
