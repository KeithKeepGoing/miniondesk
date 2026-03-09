"""Unit tests for config module."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_available_minions_defined():
    from host import config
    assert hasattr(config, "AVAILABLE_MINIONS")
    assert isinstance(config.AVAILABLE_MINIONS, list)
    assert len(config.AVAILABLE_MINIONS) >= 4
    assert "phil" in config.AVAILABLE_MINIONS


def test_dept_minion_map_complete():
    from host import config
    assert hasattr(config, "DEPT_MINION_MAP")
    for dept in ("hr", "it", "finance", "general"):
        assert dept in config.DEPT_MINION_MAP, f"Missing dept: {dept}"
    # All mapped minions should be in AVAILABLE_MINIONS
    for minion in config.DEPT_MINION_MAP.values():
        assert minion in config.AVAILABLE_MINIONS, f"Mapped minion '{minion}' not in AVAILABLE_MINIONS"


def test_default_minion_in_available():
    from host import config
    assert config.DEFAULT_MINION in config.AVAILABLE_MINIONS


def test_validate_returns_list():
    from host.config import validate
    result = validate()
    assert isinstance(result, list)
    # Should return warnings/errors as strings
    for item in result:
        assert isinstance(item, str)
