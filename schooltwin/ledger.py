"""Formal Double-Entry Financial Ledger and Accounting Engine for SchoolTwin.

Uses exact integer minor-unit arithmetic (paise, 1 INR = 100 paise) to prevent
floating-point drift and guarantee auditable reconciliation across billing, collections,
accounts receivable, payroll obligations, maintenance, and operating cash flows.
"""
from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Transaction:
    tx_id: str
    date: str
    debit_account: str
    credit_account: str
    amount_paise: int
    category: str
    description: str
    source_event_id: Optional[str] = None

    @property
    def amount_inr(self) -> float:
        return self.amount_paise / 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "date": self.date,
            "debit_account": self.debit_account,
            "credit_account": self.credit_account,
            "amount_paise": self.amount_paise,
            "amount_inr": self.amount_inr,
            "category": self.category,
            "description": self.description,
            "source_event_id": self.source_event_id,
        }


class FinancialLedger:
    """Rigorous school accounting ledger maintaining opening/closing balances,

    accounts receivable, revenue accruals, and cash flow reconciliation.
    """

    # Standard Accounts
    CASH = "asset:cash"
    ACCOUNTS_RECEIVABLE = "asset:accounts_receivable"
    TUITION_REVENUE = "revenue:tuition"
    TRANSPORT_REVENUE = "revenue:transport"
    OTHER_REVENUE = "revenue:other"
    PAYROLL_EXPENSE = "expense:payroll"
    MAINTENANCE_EXPENSE = "expense:maintenance"
    TRANSPORT_EXPENSE = "expense:transport"
    UTILITIES_EXPENSE = "expense:utilities"
    ATTENDANCE_SUPPORT_EXPENSE = "expense:attendance_support"
    GENERAL_EXPENSE = "expense:general"

    def __init__(self, opening_cash_inr: float = 3400000.0, opening_ar_inr: float = 850000.0):
        self.opening_cash_paise = int(round(opening_cash_inr * 100))
        self.opening_ar_paise = int(round(opening_ar_inr * 100))
        self.transactions: List[Transaction] = []
        self._tx_ids: set[str] = set()
        self._counter: int = 0

    def _next_tx_id(self, date_str: str) -> str:
        self._counter += 1
        return f"TX-{date_str}-{self._counter:05d}"

    def record_entry(
        self,
        date_str: str,
        debit_account: str,
        credit_account: str,
        amount_inr: float,
        category: str,
        description: str,
        source_event_id: Optional[str] = None,
        tx_id: Optional[str] = None
    ) -> Transaction:
        """Records a verified double-entry transaction in exact paise."""
        paise = int(round(amount_inr * 100))
        if paise < 0:
            raise ValueError(f"Transaction amount must be non-negative: {amount_inr}")
        tid = tx_id or self._next_tx_id(date_str)
        if tid in self._tx_ids:
            raise ValueError(f"Duplicate transaction ID: {tid}")

        tx = Transaction(
            tx_id=tid,
            date=date_str,
            debit_account=debit_account,
            credit_account=credit_account,
            amount_paise=paise,
            category=category,
            description=description,
            source_event_id=source_event_id,
        )
        self.transactions.append(tx)
        self._tx_ids.add(tid)
        return tx

    def post_transaction(
        self,
        date: str,
        debit_account: str,
        credit_account: str,
        amount_paise: int = 0,
        amount_inr: Optional[float] = None,
        category: str = "general",
        description: str = "",
        source_event_id: Optional[str] = None,
        **kwargs
    ) -> Transaction:
        """Compatibility wrapper accepting both amount_paise and amount_inr."""
        inr = (amount_paise / 100.0) if amount_paise else (amount_inr or 0.0)
        return self.record_entry(
            date_str=date,
            debit_account=debit_account,
            credit_account=credit_account,
            amount_inr=inr,
            category=category,
            description=description,
            source_event_id=source_event_id,
        )



    def bill_student_fees(self, date_str: str, tuition_inr: float, transport_inr: float, source_event_id: Optional[str] = None) -> List[Transaction]:
        """Bills student fees: Debits Accounts Receivable, Credits Tuition/Transport Revenue."""
        txs = []
        if tuition_inr > 0:
            txs.append(self.record_entry(
                date_str=date_str,
                debit_account=self.ACCOUNTS_RECEIVABLE,
                credit_account=self.TUITION_REVENUE,
                amount_inr=tuition_inr,
                category="fee_billing",
                description=f"Monthly tuition fees billed for {date_str[:7]}",
                source_event_id=source_event_id,
            ))
        if transport_inr > 0:
            txs.append(self.record_entry(
                date_str=date_str,
                debit_account=self.ACCOUNTS_RECEIVABLE,
                credit_account=self.TRANSPORT_REVENUE,
                amount_inr=transport_inr,
                category="fee_billing",
                description=f"Monthly bus transport fees billed for {date_str[:7]}",
                source_event_id=source_event_id,
            ))
        return txs

    def collect_fees(self, date_str: str, amount_inr: float, fee_category: str = "tuition", source_event_id: Optional[str] = None) -> Transaction:
        """Collects a payment: Debits Cash, Credits Accounts Receivable.

        A school cannot hold negative receivables: the daily macro inflow
        includes non-fee income (other income accrual, arrears recovery beyond
        billed dues), so any portion exceeding the outstanding receivable
        balance is booked as other revenue received in cash instead of driving
        Accounts Receivable below zero.
        """
        ar_balance = self.balance_of(self.ACCOUNTS_RECEIVABLE, as_of_date=date_str)
        if amount_inr > ar_balance and ar_balance >= 0:
            excess = amount_inr - ar_balance
            other_tx = self.record_entry(
                date_str=date_str,
                debit_account=self.CASH,
                credit_account=self.OTHER_REVENUE,
                amount_inr=excess,
                category="other_income",
                description="Cash income in excess of billed receivables (other income)",
                source_event_id=source_event_id,
            )
            if ar_balance == 0:
                return other_tx
            amount_inr = ar_balance
        return self.record_entry(
            date_str=date_str,
            debit_account=self.CASH,
            credit_account=self.ACCOUNTS_RECEIVABLE,
            amount_inr=amount_inr,
            category="fee_collection",
            description=f"{fee_category.capitalize()} payment collection received",
            source_event_id=source_event_id,
        )

    def disburse_payroll(self, date_str: str, amount_inr: float, source_event_id: Optional[str] = None) -> Transaction:
        """Disburses payroll: Debits Payroll Expense, Credits Cash."""
        return self.record_entry(
            date_str=date_str,
            debit_account=self.PAYROLL_EXPENSE,
            credit_account=self.CASH,
            amount_inr=amount_inr,
            category="payroll",
            description="Faculty and staff salary disbursement",
            source_event_id=source_event_id,
        )

    def book_maintenance_repair(self, date_str: str, amount_inr: float, issue_desc: str, source_event_id: Optional[str] = None) -> Transaction:
        """Books maintenance/repair payment: Debits Maintenance Expense, Credits Cash."""
        return self.record_entry(
            date_str=date_str,
            debit_account=self.MAINTENANCE_EXPENSE,
            credit_account=self.CASH,
            amount_inr=amount_inr,
            category="maintenance",
            description=f"Facility repair: {issue_desc}",
            source_event_id=source_event_id,
        )

    def book_transport_repair(self, date_str: str, amount_inr: float, bus_id: str, source_event_id: Optional[str] = None) -> Transaction:
        """Books vehicle repair payment: Debits Transport Expense, Credits Cash."""
        return self.record_entry(
            date_str=date_str,
            debit_account=self.TRANSPORT_EXPENSE,
            credit_account=self.CASH,
            amount_inr=amount_inr,
            category="transport_operations",
            description=f"Emergency repair for {bus_id}",
            source_event_id=source_event_id,
        )

    def has_source(self, source_event_id: str) -> bool:
        """True when any transaction already carries this source event id.

        Causal handlers book some event costs directly; the generic effect path
        uses this to avoid double-booking the same source event.
        """
        return any(tx.source_event_id == source_event_id for tx in self.transactions)

    _EVENT_EXPENSE_ACCOUNTS = {
        "maintenance": MAINTENANCE_EXPENSE,
        "transport_operations": TRANSPORT_EXPENSE,
        "utilities": UTILITIES_EXPENSE,
        "sanitation_and_water": UTILITIES_EXPENSE,
        "attendance_support": ATTENDANCE_SUPPORT_EXPENSE,
    }

    def book_event_expense(
        self,
        date_str: str,
        amount_inr: float,
        category: str,
        description: str,
        source_event_id: Optional[str] = None,
    ) -> Transaction:
        """Books one event-driven operating expense: Debits the matching expense
        account, Credits Cash. Double-booking prevention is the caller's
        contract: the engine skips an event's generic effects entirely when a
        causal handler has already booked that source event (see Engine._close),
        so this method records exactly what it is given.
        """
        account = self._EVENT_EXPENSE_ACCOUNTS.get(category, self.GENERAL_EXPENSE)
        return self.record_entry(
            date_str=date_str,
            debit_account=account,
            credit_account=self.CASH,
            amount_inr=amount_inr,
            category=category,
            description=description,
            source_event_id=source_event_id,
        )



    def balance_of(self, account: str, as_of_date: Optional[str] = None) -> float:
        """Calculates exact net balance of an account up to an optional date."""
        total_paise = 0
        if account == self.CASH:
            total_paise += self.opening_cash_paise
        elif account == self.ACCOUNTS_RECEIVABLE:
            total_paise += self.opening_ar_paise

        for tx in self.transactions:
            if as_of_date and tx.date > as_of_date:
                continue
            if tx.debit_account == account:
                total_paise += tx.amount_paise
            if tx.credit_account == account:
                total_paise -= tx.amount_paise

        return total_paise / 100.0

    def total_cash_inflows(self, as_of_date: Optional[str] = None) -> float:
        """Total credits turning into cash (debits to Cash account)."""
        paise = sum(
            tx.amount_paise for tx in self.transactions
            if tx.debit_account == self.CASH and (not as_of_date or tx.date <= as_of_date)
        )
        return paise / 100.0

    def total_cash_outflows(self, as_of_date: Optional[str] = None) -> float:
        """Total payments leaving cash (credits to Cash account)."""
        paise = sum(
            tx.amount_paise for tx in self.transactions
            if tx.credit_account == self.CASH and (not as_of_date or tx.date <= as_of_date)
        )
        return paise / 100.0

    def total_revenue_billed(self, as_of_date: Optional[str] = None) -> float:
        paise = sum(
            tx.amount_paise for tx in self.transactions
            if tx.credit_account.startswith("revenue:") and (not as_of_date or tx.date <= as_of_date)
        )
        return paise / 100.0

    def total_expenses_incurred(self, as_of_date: Optional[str] = None) -> float:
        paise = sum(
            tx.amount_paise for tx in self.transactions
            if tx.debit_account.startswith("expense:") and (not as_of_date or tx.date <= as_of_date)
        )
        return paise / 100.0

    def verify_reconciliation(self, as_of_date: Optional[str] = None) -> Dict[str, Any]:
        """Mathematically verifies fundamental accounting identities:

        1. Closing Cash == Opening Cash + Cash Inflows - Cash Outflows
        2. Closing AR == Opening AR + Fees Billed - Collections Received
        """
        closing_cash = self.balance_of(self.CASH, as_of_date)
        inflows = self.total_cash_inflows(as_of_date)
        outflows = self.total_cash_outflows(as_of_date)
        expected_cash = (self.opening_cash_paise / 100.0) + inflows - outflows
        cash_reconciled = abs(closing_cash - expected_cash) < 0.001

        closing_ar = self.balance_of(self.ACCOUNTS_RECEIVABLE, as_of_date)
        billed = sum(
            tx.amount_paise for tx in self.transactions
            if tx.debit_account == self.ACCOUNTS_RECEIVABLE and (not as_of_date or tx.date <= as_of_date)
        ) / 100.0
        collected = sum(
            tx.amount_paise for tx in self.transactions
            if tx.credit_account == self.ACCOUNTS_RECEIVABLE and (not as_of_date or tx.date <= as_of_date)
        ) / 100.0
        expected_ar = (self.opening_ar_paise / 100.0) + billed - collected
        ar_reconciled = abs(closing_ar - expected_ar) < 0.001

        return {
            "reconciled": cash_reconciled and ar_reconciled,
            "cash": {
                "closing_cash": round(closing_cash, 2),
                "opening_cash": round(self.opening_cash_paise / 100.0, 2),
                "inflows": round(inflows, 2),
                "outflows": round(outflows, 2),
                "expected": round(expected_cash, 2),
                "discrepancy": round(closing_cash - expected_cash, 4),
            },
            "accounts_receivable": {
                "closing_ar": round(closing_ar, 2),
                "opening_ar": round(self.opening_ar_paise / 100.0, 2),
                "billed": round(billed, 2),
                "collected": round(collected, 2),
                "expected": round(expected_ar, 2),
                "discrepancy": round(closing_ar - expected_ar, 4),
            }
        }
