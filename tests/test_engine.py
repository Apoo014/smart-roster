import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app import engine as E  # noqa: E402

NOV = E.month_dates(2026, 11)
SUN = date(2026, 11, 15)      # a Sunday
HOL = date(2026, 11, 8)       # public holiday used in tests (also a Sunday)


def make_ctx(**kw):
    ctx = E.Context(
        employees={1: dict(name="Rahul", active=True, pod_id=1, capacity=2),
                   2: dict(name="Priya", active=True, pod_id=1, capacity=2),
                   3: dict(name="Sneha", active=True, pod_id=1, capacity=2),
                   4: dict(name="Floater", active=True, pod_id=1, capacity=2)},
        holidays={HOL}, brand_pod={1: 1, 2: 1, 3: 1},
        brand_names={1: "Brand A", 2: "Brand B", 3: "Brand C"},
        process_names={1: "CS", 2: "ACC", 3: "NDR"})
    for k, v in kw.items():
        setattr(ctx, k, v)
    return ctx


def gaps(ctx, entries, dates=NOV):
    return [c for c in E.compute_conflicts(ctx, entries, dates) if c["type"] == E.COVERAGE_GAP]


class EngineTests(unittest.TestCase):
    def test_single_resource_365_sunday_off_creates_gap(self):
        ctx = make_ctx(assignments=[(1, 1, 1), (1, 1, 2), (1, 1, 3)],
                       rules={(1, p): dict(calendar=E.CAL_365, min_staff=1) for p in (1, 2, 3)},
                       weekly_offs={1: {6}})
        g = gaps(ctx, E.generate_entries(ctx, NOV))
        sundays = [d for d in NOV if d.weekday() == 6]
        self.assertEqual(len(g), 3 * len(sundays))
        self.assertTrue(all(c["severity"] == E.CRITICAL for c in g))
        self.assertTrue(all(c["date"].weekday() == 6 for c in g))
        self.assertIn("Rahul (on weekly off)", g[0]["description"])
        self.assertIn("Floater", g[0]["suggestion"])

    def test_sunday_closed_brand_has_no_gap_when_off_is_sunday(self):
        ctx = make_ctx(assignments=[(1, 1, 1)],
                       rules={(1, 1): dict(calendar=E.CAL_SUNDAY_HOLIDAY_OFF, min_staff=1)},
                       weekly_offs={1: {6}})
        entries = E.generate_entries(ctx, NOV)
        self.assertEqual(gaps(ctx, entries), [])
        self.assertEqual([e.status for e in entries if e.date == SUN], [E.O])

    def test_holiday_rules(self):
        ctx = make_ctx(assignments=[(1, 1, 1), (2, 2, 1)],
                       rules={(1, 1): dict(calendar=E.CAL_365, min_staff=1),
                              (2, 1): dict(calendar=E.CAL_HOLIDAY_OFF, min_staff=1)})
        entries = E.generate_entries(ctx, NOV)
        by = {(e.brand_id, e.date): e.status for e in entries}
        self.assertEqual(by[(1, HOL)], E.W)
        self.assertEqual(by[(2, HOL)], E.H)
        self.assertEqual(gaps(ctx, entries), [])

    def test_multi_resource_covers_weekly_off(self):
        ctx = make_ctx(assignments=[(2, 2, 1), (3, 2, 1)],
                       rules={(2, 1): dict(calendar=E.CAL_365, min_staff=1)},
                       weekly_offs={2: {6}, 3: {2}})
        self.assertEqual(gaps(ctx, E.generate_entries(ctx, NOV)), [])

    def test_min_staff_two_with_one_on_leave(self):
        ctx = make_ctx(assignments=[(2, 2, 1), (3, 2, 1)],
                       rules={(2, 1): dict(calendar=E.CAL_365, min_staff=2)},
                       leaves={3: [(date(2026, 11, 10), date(2026, 11, 11), "Casual")]})
        g = gaps(ctx, E.generate_entries(ctx, NOV))
        self.assertEqual({c["date"].day for c in g}, {10, 11})
        self.assertIn("short by 1", g[0]["description"])

    def test_leave_after_generation_is_incremental(self):
        ctx = make_ctx(assignments=[(1, 1, 1)], rules={(1, 1): dict(calendar=E.CAL_365, min_staff=1)})
        entries = E.generate_entries(ctx, NOV)
        self.assertEqual(gaps(ctx, entries), [])
        ctx.leaves = {1: [(date(2026, 11, 20), date(2026, 11, 21), "Sick")]}
        changed, _ = E.recompute_statuses(ctx, entries, 1, date(2026, 11, 20), date(2026, 11, 21))
        self.assertEqual(len(changed), 2)
        cells = {(e.brand_id, e.process_id, e.date) for e in changed}
        g = E.compute_conflicts(ctx, entries, NOV, cells=cells, emp_dates=set())
        self.assertEqual({c["date"].day for c in g}, {20, 21})
        self.assertEqual(sum(1 for e in entries if e.status == E.L), 2)

    def test_multi_brand_employee_and_overload(self):
        ctx = make_ctx(assignments=[(1, 1, 1), (1, 2, 1), (1, 3, 1)],
                       rules={(b, 1): dict(calendar=E.CAL_365, min_staff=1) for b in (1, 2, 3)})
        ctx.employees[1]["capacity"] = 2
        c = E.compute_conflicts(ctx, E.generate_entries(ctx, NOV), NOV)
        self.assertTrue(any(x["type"] == E.OVERLOAD for x in c))
        ctx.employees[1]["capacity"] = 3
        c = E.compute_conflicts(ctx, E.generate_entries(ctx, NOV), NOV)
        self.assertFalse(any(x["type"] == E.OVERLOAD for x in c))

    def test_manual_edit_violations_and_cover(self):
        ctx = make_ctx(assignments=[(1, 1, 1)], rules={(1, 1): dict(calendar=E.CAL_365, min_staff=1)},
                       weekly_offs={1: {6}})
        entries = E.generate_entries(ctx, NOV)
        sun = next(e for e in entries if e.date == SUN)
        sun.status = E.W
        sun.manual = True
        res = E.compute_conflicts(ctx, [sun], NOV, cells={(1, 1, SUN)}, emp_dates={(1, SUN)})
        self.assertEqual({c["type"] for c in res}, {E.WEEKLY_OFF_VIOLATION})
        sun.status = E.O
        cover = E.Entry(4, 1, 1, SUN, E.W, cover=True, manual=True)
        res = E.compute_conflicts(ctx, entries + [cover], NOV, cells={(1, 1, SUN)}, emp_dates={(4, SUN)})
        self.assertEqual(res, [])

    def test_invalid_assignment(self):
        ctx = make_ctx(assignments=[(1, 1, 1)], rules={(1, 1): dict(calendar=E.CAL_365, min_staff=1)})
        bad = E.Entry(2, 1, 1, SUN, E.W)
        res = E.compute_conflicts(ctx, [bad], NOV, cells=set(), emp_dates={(2, SUN)})
        self.assertEqual([c["type"] for c in res], [E.INVALID_ASSIGNMENT])

    def test_coverage_stats(self):
        ctx = make_ctx(assignments=[(1, 1, 1)], rules={(1, 1): dict(calendar=E.CAL_365, min_staff=1)},
                       weekly_offs={1: {6}})
        s = E.coverage_stats(ctx, E.generate_entries(ctx, NOV), NOV)
        self.assertEqual(s["required"], 30)
        self.assertEqual(s["covered"], 25)      # 5 Sundays in Nov 2026
        self.assertEqual(s["per_brand"][1]["percent"], round(100 * 25 / 30, 1))

    def test_consecutive_days_low_severity(self):
        ctx = make_ctx(assignments=[(1, 1, 1)], rules={(1, 1): dict(calendar=E.CAL_365, min_staff=1)})
        c = E.compute_conflicts(ctx, E.generate_entries(ctx, NOV), NOV)
        self.assertTrue(any(x["type"] == E.CONSECUTIVE_WORK and x["severity"] == E.LOW for x in c))


if __name__ == "__main__":
    unittest.main()
