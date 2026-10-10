"""Money. Anchor mode reads the story's own ledger; generate mode rebuilds it from the story's assumptions."""
import calendar
from datetime import date


class Finance:
    def __init__(self, story, ov):
        self.story, self.ov = story, ov
        led = story.ledger
        self.mca = led["monthly_collection_assumptions"]
        self.cash = float(led["opening_cash_balance_inr"])
        self.ar = float(led["opening_accounts_receivable_inr"])
        self.monthly = led["monthly_summary"]
        # average daily accrual per account per month, from the story's accrual ledger
        acc = {}
        for r in led["expense_accrual_ledger"]:
            acc.setdefault((r["date"][:7], r["account"]), 0.0)
            acc[(r["date"][:7], r["account"])] += r["amount_inr"]
        self.acc = acc
        self.shape = {m: self._shape(v["tuition_collections"]) for m, v in ((v["month"], v) for v in self.mca.values())}

    @staticmethod
    def _shape(d):
        tot = sum(d.values()) or 1
        return {k: v / tot for k, v in d.items()}

    def story_day(self, iso):
        f = self.story.by_date[iso]["finance"]
        self.cash, self.ar = f["closing_cash_balance_inr"], f["accounts_receivable_closing_inr"]
        return {"cash": self.cash, "inflow": f["cash_inflows_inr"], "outflow": f["cash_outflows_inr"],
                "accrual": f["total_expense_accrual_inr"], "ar": self.ar,
                "accounts": f["expense_accruals_inr"]}

    def model_day(self, iso, roll_net_tuition, extra_costs, payroll_extra=0.0, fee_delta=0.0, transport_delta=0.0):
        m = iso[:7]
        dim = calendar.monthrange(int(iso[:4]), int(iso[5:7]))[1]
        mc = next((v for v in self.mca.values() if v["month"] == m), None)
        if mc is None:
            # Fallback to May collection assumptions per Decision D2 (labelled assumed)
            mc = next((v for v in self.mca.values() if v["month"] == "2026-05"), list(self.mca.values())[-1])

        coll_ratio = mc["tuition_collection_ratio_assumed"]
        due = mc["tuition_due"] * (1 + fee_delta)
        m_shape = self.shape.get(m, {})
        m_other = self.monthly.get(m) or self.monthly.get("2026-05", list(self.monthly.values())[-1])
        inflow = (due * coll_ratio * m_shape.get(iso, 1 / dim)
                  + mc["transport_due"] * (1 + transport_delta) * mc["transport_collection_ratio_assumed"] * self._tshape(mc, iso)
                  + mc.get("arrears_recovery", {}).get(iso, 0)
                  + m_other["other_income_accrual_inr"] / dim)

        acc_m = m if any(mm == m for (mm, _) in self.acc.keys()) else "2026-05"
        accounts = {a: v / dim for (mm, a), v in self.acc.items() if mm == acc_m}
        accounts["payroll"] = accounts.get("payroll", 0) + payroll_extra / dim
        for acct, amt in extra_costs:
            accounts[acct] = accounts.get(acct, 0) + amt
        accrual = sum(accounts.values())

        if hasattr(self.story, "by_date") and isinstance(self.story.by_date, dict) and iso in self.story.by_date:
            ref = self.story.by_date[iso]["finance"]          # the school's payment calendar
        elif hasattr(self.story, "days") and self.story.days:
            ref = self.story.days[-1].get("finance", {})
        else:
            ref = {}

        ref_outflow = ref.get("cash_outflows_inr", accrual)
        ref_accrual = ref.get("total_expense_accrual_inr", accrual)
        outflow = ref_outflow * accrual / max(ref_accrual, 1) if ref_accrual else accrual
        self.cash += inflow - outflow
        return {"cash": round(self.cash), "inflow": round(inflow), "outflow": round(outflow),
                "accrual": round(accrual), "ar": round(self.ar), "accounts": {k: round(v) for k, v in accounts.items()}}

    @staticmethod
    def _tshape(mc, iso):
        d = mc["transport_collections"]
        return d.get(iso, 0) / (sum(d.values()) or 1)
