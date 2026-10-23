import copy

import pytest
from pydantic import ValidationError

from matchsense.schemas import PITCH_LENGTH, PITCH_WIDTH, MatchState
from matchsense.state_text import state_to_text


def test_valid_state(state_dict):
    s = MatchState.model_validate(state_dict)
    assert len(s.us) == 5 and len(s.them) == 5


@pytest.mark.parametrize("mutate", [
    lambda d: d["us"].pop(),                                     # 4 players
    lambda d: d["us"][1].update(role="GK"),                       # two goalkeepers
    lambda d: d.update(time_remaining_s=d["match_length_s"] + 1),  # more time than the match
    lambda d: d.update(stamina=1.5),
    lambda d: d["ball"].update(x=99),                            # off the pitch
    lambda d: d.update(possession="nobody"),
])
def test_invalid_states(state_dict, mutate):
    d = copy.deepcopy(state_dict)
    mutate(d)
    with pytest.raises(ValidationError):
        MatchState.model_validate(d)


def _mirror(d):
    m = copy.deepcopy(d)
    m["attack_direction"] = "left" if d["attack_direction"] == "right" else "right"
    m["ball"] = {"x": PITCH_LENGTH - d["ball"]["x"], "y": PITCH_WIDTH - d["ball"]["y"]}
    for side in ("us", "them"):
        for p in m[side]:
            p["x"], p["y"] = PITCH_LENGTH - p["x"], PITCH_WIDTH - p["y"]
    return m


def test_direction_normalisation_gives_identical_text():
    from matchsense.scenarios import scenarios

    for item in scenarios():
        a = MatchState.model_validate(item["state"])
        b = MatchState.model_validate(_mirror(item["state"]))
        assert state_to_text(a) == state_to_text(b), item["id"]


def test_text_contains_key_facts(state_dict):
    t = state_to_text(MatchState.model_validate(state_dict))
    assert "level at 1-1" in t and "We have the ball" in t and "Objective:" in t
    assert "x=" not in t  # no raw coordinates
