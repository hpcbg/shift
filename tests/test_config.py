import textwrap

from shift_sim.config import deep_merge, load_config, parse_clock, load_yaml


def test_deep_merge_override_wins():
    base = {"a": 1, "b": {"c": 2, "d": 3}}
    over = {"b": {"c": 20}, "e": 5}
    out = deep_merge(base, over)
    assert out["b"]["c"] == 20      # overridden
    assert out["b"]["d"] == 3       # preserved
    assert out["a"] == 1 and out["e"] == 5
    assert base["b"]["c"] == 2      # original not mutated


def test_lists_replaced_not_merged():
    out = deep_merge({"x": [1, 2, 3]}, {"x": [9]})
    assert out["x"] == [9]


def test_parse_clock():
    assert parse_clock("18:30") == 18.5
    assert parse_clock("24:00") == 24.0
    assert parse_clock(6) == 6.0


def test_default_config_has_six_buildings():
    cfg = load_config()
    assert len(cfg["buildings"]) == 6
    ids = {b["id"] for b in cfg["buildings"]}
    assert "admin_building" in ids
    # exactly one non-participating building in the default scenario
    non = [b for b in cfg["buildings"] if not b["flexibility_participation"]]
    assert len(non) == 1


def test_missing_local_override_tolerated(tmp_path):
    base = tmp_path / "config.yaml"
    base.write_text(textwrap.dedent("""
        simulation: {start_time: "2026-01-15 00:00", horizon_hours: 1, time_step_minutes: 30}
        value: 7
    """), encoding="utf-8")
    cfg = load_config(base, local_path=tmp_path / "does_not_exist.yaml")
    assert cfg["value"] == 7
