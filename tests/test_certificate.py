"""复审到期规则：+3 年、闰日回退、已有值优先。"""
from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.certificate import review_due


def test_plus_years():
    assert review_due("2026-06-24") == date(2029, 6, 24)
    assert review_due("2026-06-24", years=2) == date(2028, 6, 24)


def test_leap_day():
    assert review_due("2024-02-29") == date(2027, 2, 28)


def test_existing_wins():
    assert review_due("2020-01-01", existing="2030-12-31") == date(2030, 12, 31)
    assert review_due("", existing="") is None


if __name__ == "__main__":
    test_plus_years()
    test_leap_day()
    test_existing_wins()
    print("ok: test_certificate")
