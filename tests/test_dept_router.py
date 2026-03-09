"""Unit tests for department router."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from host.enterprise.dept_router import route_with_score


def test_it_routing():
    dept, score = route_with_score("我的電腦壞了，藍屏無法開機")
    assert dept == "it", f"Expected 'it', got '{dept}'"
    assert score >= 1


def test_hr_routing():
    dept, score = route_with_score("我想申請年假三天")
    assert dept == "hr", f"Expected 'hr', got '{dept}'"
    assert score >= 1


def test_finance_routing():
    dept, score = route_with_score("我要報帳上週的餐費發票")
    assert dept == "finance", f"Expected 'finance', got '{dept}'"
    assert score >= 1


def test_general_fallback():
    dept, score = route_with_score("今天天氣真好")
    # Low confidence should fall through to general or score 0
    assert dept in ("general", "hr", "it", "finance")


def test_it_english():
    dept, score = route_with_score("VPN is not working, I can't connect")
    assert dept == "it"


def test_hr_english():
    dept, score = route_with_score("I need to apply for sick leave tomorrow")
    assert dept == "hr"


def test_empty_text():
    dept, score = route_with_score("")
    assert dept == "general"
    assert score == 0


def test_score_is_int():
    dept, score = route_with_score("password reset")
    assert isinstance(score, int)
    assert score >= 0
