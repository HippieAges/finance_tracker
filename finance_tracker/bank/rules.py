"""Merchant → category rules for bank transaction import."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

CONFIG_DIR = Path.home() / ".config" / "finance_tracker"
RULES_PATH = CONFIG_DIR / "merchant_rules.json"

# (substring pattern, category name) — first case-insensitive match wins.
DEFAULT_MERCHANT_RULES: List[Tuple[str, str]] = [
    # Dining
    ("chipotle", "Dining"),
    ("starbucks", "Dining"),
    ("mcdonald", "Dining"),
    ("doordash", "Dining"),
    ("uber eats", "Dining"),
    ("ubereats", "Dining"),
    ("restaurant", "Dining"),
    ("cafe", "Dining"),
    ("coffee", "Dining"),
    # Groceries
    ("ralphs", "Groceries"),
    ("trader joe", "Groceries"),
    ("whole foods", "Groceries"),
    ("aldi", "Groceries"),
    ("costco", "Groceries"),
    ("safeway", "Groceries"),
    ("kroger", "Groceries"),
    ("grocery", "Groceries"),
    # Subscriptions
    ("medium.com", "Subscriptions"),
    ("medium", "Subscriptions"),
    ("amazon prime", "Subscriptions"),
    ("prime video", "Subscriptions"),
    ("netflix", "Subscriptions"),
    ("spotify", "Subscriptions"),
    ("disney+", "Subscriptions"),
    ("disney plus", "Subscriptions"),
    ("hulu", "Subscriptions"),
    ("youtube premium", "Subscriptions"),
    ("apple.com/bill", "Subscriptions"),
    ("icloud", "Subscriptions"),
    # Gas
    ("shell", "Gas"),
    ("chevron", "Gas"),
    ("arco", "Gas"),
    ("76 ", "Gas"),
    ("gas station", "Gas"),
    ("exxon", "Gas"),
    ("mobil", "Gas"),
    # Transport
    ("uber", "Transport"),
    ("lyft", "Transport"),
    ("metro", "Transport"),
    # Parking
    ("parking meter", "Parking"),
    ("parking", "Parking"),
    # Utilities
    ("pg&e", "Utilities"),
    ("pge", "Utilities"),
    ("edison", "Utilities"),
    ("verizon", "Utilities"),
    ("at&t", "Utilities"),
    ("att ", "Utilities"),
    ("comcast", "Utilities"),
    ("spectrum", "Utilities"),
    # Games
    ("steam", "Games"),
    ("playstation", "Games"),
    ("xbox", "Games"),
    ("nintendo", "Games"),
    # Income
    ("paycheck", "Salary"),
    ("direct dep", "Salary"),
    ("direct deposit", "Salary"),
    ("payroll", "Salary"),
    ("gusto", "Salary"),
    ("adp", "Salary"),
]

# Plaid personal_finance_category.primary → app category
PLAID_PFC_FALLBACK = {
    "INCOME": "Other income",
    "TRANSFER_IN": "Other income",
    "FOOD_AND_DRINK": "Dining",
    "TRANSPORTATION": "Transport",
    "TRAVEL": "Transport",
    "RENT_AND_UTILITIES": "Utilities",
    "MEDICAL": "Healthcare",
    "ENTERTAINMENT": "Games",
    "GENERAL_SERVICES": "Other Expenses",
    "GENERAL_MERCHANDISE": "Other Expenses",
    "HOME_IMPROVEMENT": "Other Expenses",
    "PERSONAL_CARE": "Other Expenses",
    "GOVERNMENT_AND_NON_PROFIT": "Other Expenses",
    "BANK_FEES": "Other Expenses",
    "LOAN_PAYMENTS": "Other Expenses",
}


def default_rules_payload() -> dict:
    return {
        "rules": [{"pattern": p, "category": c} for p, c in DEFAULT_MERCHANT_RULES],
        "plaid_pfc_fallback": dict(PLAID_PFC_FALLBACK),
    }


def ensure_rules_file() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not RULES_PATH.exists():
        RULES_PATH.write_text(
            json.dumps(default_rules_payload(), indent=2),
            encoding="utf-8",
        )
        return RULES_PATH

    # Merge any new default patterns the user doesn't already have.
    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    existing = {
        (str(r.get("pattern", "")).lower(), str(r.get("category", "")))
        for r in data.get("rules", [])
    }
    changed = False
    rules = list(data.get("rules", []))
    for pattern, category in DEFAULT_MERCHANT_RULES:
        key = (pattern.lower(), category)
        # Also skip if same pattern maps to any category already.
        if any(p == pattern.lower() for p, _ in existing):
            continue
        rules.append({"pattern": pattern, "category": category})
        existing.add(key)
        changed = True
    fallback = data.get("plaid_pfc_fallback") or {}
    for k, v in PLAID_PFC_FALLBACK.items():
        if k not in fallback:
            fallback[k] = v
            changed = True
    if changed:
        data["rules"] = rules
        data["plaid_pfc_fallback"] = fallback
        RULES_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return RULES_PATH


def load_rules() -> tuple[list[tuple[str, str]], dict[str, str]]:
    ensure_rules_file()
    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    rules = [
        (str(r["pattern"]).lower(), str(r["category"]))
        for r in data.get("rules", [])
        if r.get("pattern") and r.get("category")
    ]
    fallback = {
        str(k).upper(): str(v)
        for k, v in data.get("plaid_pfc_fallback", PLAID_PFC_FALLBACK).items()
    }
    return rules, fallback
