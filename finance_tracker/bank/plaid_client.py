"""Plaid API client and credential/item persistence."""

from __future__ import annotations

import calendar
import json
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import plaid
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from finance_tracker.bank.categorize import BankTransaction

CONFIG_DIR = Path.home() / ".config" / "finance_tracker"
CREDENTIALS_PATH = CONFIG_DIR / "plaid_credentials.json"
ITEMS_PATH = CONFIG_DIR / "plaid_items.json"

# Client ID / secret are kept in process memory only — never written to disk.
_SESSION_CREDENTIALS: Optional[PlaidCredentials] = None
# Linked bank access tokens are also session-only. Manage Banks starts empty
# every time the app is restarted.
_SESSION_ITEMS: List[LinkedItem] = []

ENV_HOSTS = {
    "sandbox": plaid.Environment.Sandbox,
    # Development host is still used by Plaid; newer plaid-python only exposes Sandbox/Production enums.
    "development": "https://development.plaid.com",
    "production": plaid.Environment.Production,
}


@dataclass
class PlaidCredentials:
    client_id: str
    secret: str
    env: str = "sandbox"

    def is_complete(self) -> bool:
        return bool(self.client_id and self.secret and self.env in ENV_HOSTS)


@dataclass
class LinkedItem:
    item_id: str
    access_token: str
    institution_name: str = ""
    cursor: str = ""
    enabled: bool = True


def clear_persisted_credentials() -> None:
    """Delete any legacy on-disk Plaid API key file if present."""
    try:
        if CREDENTIALS_PATH.exists():
            CREDENTIALS_PATH.unlink()
    except OSError:
        pass


def clear_persisted_items() -> None:
    """Delete any legacy on-disk linked-bank item file if present."""
    try:
        if ITEMS_PATH.exists():
            ITEMS_PATH.unlink()
    except OSError:
        pass


def load_credentials() -> Optional[PlaidCredentials]:
    """Return session-only credentials (not loaded from disk)."""
    clear_persisted_credentials()
    return _SESSION_CREDENTIALS


def set_session_credentials(creds: PlaidCredentials) -> None:
    """Keep credentials in memory for this app session only; never write to disk."""
    global _SESSION_CREDENTIALS
    clear_persisted_credentials()
    if not creds.is_complete():
        raise ValueError("Client ID, secret, and a valid environment are required.")
    _SESSION_CREDENTIALS = PlaidCredentials(
        client_id=creds.client_id.strip(),
        secret=creds.secret.strip(),
        env=creds.env.strip().lower(),
    )


def clear_session_credentials() -> None:
    global _SESSION_CREDENTIALS
    _SESSION_CREDENTIALS = None
    clear_persisted_credentials()


def load_items() -> List[LinkedItem]:
    clear_persisted_items()
    return list(_SESSION_ITEMS)


def save_items(items: List[LinkedItem]) -> None:
    global _SESSION_ITEMS
    clear_persisted_items()
    _SESSION_ITEMS = list(items)


def clear_session_items() -> None:
    global _SESSION_ITEMS
    _SESSION_ITEMS = []
    clear_persisted_items()


def upsert_item(item: LinkedItem) -> None:
    items = load_items()
    for i, existing in enumerate(items):
        if existing.item_id == item.item_id or existing.access_token == item.access_token:
            item.enabled = True
            items[i] = item
            save_items(items)
            return
    item.enabled = True
    items.append(item)
    save_items(items)


def set_item_enabled(item_id: str, enabled: bool) -> None:
    items = load_items()
    for item in items:
        if item.item_id == item_id:
            item.enabled = enabled
            break
    save_items(items)


def remove_item(item_id: str) -> None:
    items = [i for i in load_items() if i.item_id != item_id]
    save_items(items)


def load_enabled_items() -> List[LinkedItem]:
    return [i for i in load_items() if i.enabled]


def linked_institution_summary(*, enabled_only: bool = True) -> str:
    items = load_enabled_items() if enabled_only else load_items()
    if not items:
        return "No banks linked" if not enabled_only else "No banks selected for import"
    parts = []
    for i in items:
        label = i.institution_name or i.item_id
        if not enabled_only and not i.enabled:
            label = f"{label} (excluded)"
        parts.append(label)
    return " + ".join(parts)


class PlaidClient:
    def __init__(self, creds: Optional[PlaidCredentials] = None) -> None:
        self.creds = creds or load_credentials()
        if self.creds is None or not self.creds.is_complete():
            raise RuntimeError(
                "Plaid credentials missing. Use Plaid settings to add client_id and secret."
            )
        configuration = plaid.Configuration(
            host=ENV_HOSTS[self.creds.env],
            api_key={
                "clientId": self.creds.client_id,
                "secret": self.creds.secret,
            },
        )
        api_client = plaid.ApiClient(configuration)
        self.api = plaid_api.PlaidApi(api_client)

    def create_link_token(self, client_user_id: Optional[str] = None) -> str:
        request = LinkTokenCreateRequest(
            products=[Products("transactions")],
            client_name="Monthly Finance Tracker",
            country_codes=[CountryCode("US")],
            language="en",
            user=LinkTokenCreateRequestUser(
                client_user_id=client_user_id or f"finance-tracker-{uuid.uuid4()}"
            ),
        )
        response = self.api.link_token_create(request)
        return response["link_token"]

    def exchange_public_token(
        self,
        public_token: str,
        institution_name: str = "",
    ) -> LinkedItem:
        request = ItemPublicTokenExchangeRequest(public_token=public_token)
        response = self.api.item_public_token_exchange(request)
        item = LinkedItem(
            item_id=response["item_id"],
            access_token=response["access_token"],
            institution_name=institution_name or "Linked bank",
            cursor="",
        )
        upsert_item(item)
        # Kick /transactions/sync once so the product starts preparing data.
        try:
            self._prime_sync(item)
        except Exception:
            pass
        return item

    def _prime_sync(self, item: LinkedItem) -> None:
        for attempt in range(3):
            try:
                response = self.api.transactions_sync(
                    TransactionsSyncRequest(access_token=item.access_token)
                )
                item.cursor = response["next_cursor"] or ""
                upsert_item(item)
                return
            except plaid.ApiException as exc:
                body = {}
                try:
                    body = json.loads(exc.body)
                except Exception:
                    pass
                if body.get("error_code") in {
                    "PRODUCT_NOT_READY",
                    "INSTITUTION_NOT_READY",
                } and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise

    def fetch_month_transactions(
        self,
        year: int,
        month: int,
        items: Optional[List[LinkedItem]] = None,
    ) -> List[BankTransaction]:
        linked = items if items is not None else load_enabled_items()
        if not linked:
            raise RuntimeError(
                "No banks selected for import. Connect a bank or re-enable one under Manage banks."
            )

        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        all_txns: List[BankTransaction] = []

        for item in linked:
            all_txns.extend(
                self._transactions_for_range(item, start, end, retries=4)
            )
        return all_txns

    def _transactions_for_range(
        self,
        item: LinkedItem,
        start: date,
        end: date,
        *,
        retries: int = 4,
    ) -> List[BankTransaction]:
        last_error: Optional[Exception] = None
        for attempt in range(retries):
            try:
                return self._paginate_get(item, start, end)
            except plaid.ApiException as exc:
                last_error = exc
                body = {}
                try:
                    body = json.loads(exc.body)
                except Exception:
                    pass
                if body.get("error_code") in {
                    "PRODUCT_NOT_READY",
                    "INSTITUTION_NOT_READY",
                } and attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    try:
                        self._prime_sync(item)
                    except Exception:
                        pass
                    continue
                raise
        if last_error:
            raise last_error
        return []

    def _paginate_get(
        self,
        item: LinkedItem,
        start: date,
        end: date,
    ) -> List[BankTransaction]:
        offset = 0
        page_size = 500
        collected: List[BankTransaction] = []
        total = None
        while total is None or offset < total:
            request = TransactionsGetRequest(
                access_token=item.access_token,
                start_date=start,
                end_date=end,
                options=TransactionsGetRequestOptions(
                    count=page_size,
                    offset=offset,
                    include_personal_finance_category=True,
                ),
            )
            response = self.api.transactions_get(request)
            raw_txns = list(response["transactions"])
            total = int(response["total_transactions"])
            for raw in raw_txns:
                collected.append(self._normalize(raw, item.institution_name))
            offset += len(raw_txns)
            if not raw_txns:
                break
        return collected

    @staticmethod
    def _normalize(raw: Any, institution: str) -> BankTransaction:
        if hasattr(raw, "to_dict"):
            data = raw.to_dict()
        elif isinstance(raw, dict):
            data = raw
        else:
            data = dict(raw)

        date_val = data.get("date") or data.get("authorized_date")
        if isinstance(date_val, datetime):
            txn_date = date_val.date()
        elif isinstance(date_val, date):
            txn_date = date_val
        else:
            txn_date = date.fromisoformat(str(date_val)[:10])

        pfc = data.get("personal_finance_category") or {}
        if hasattr(pfc, "to_dict"):
            pfc = pfc.to_dict()
        pfc_primary = None
        pfc_detailed = None
        if isinstance(pfc, dict):
            pfc_primary = pfc.get("primary")
            pfc_detailed = pfc.get("detailed")

        merchant = data.get("merchant_name")
        return BankTransaction(
            date=txn_date,
            amount=float(data.get("amount") or 0),
            name=str(data.get("name") or ""),
            merchant_name=str(merchant) if merchant is not None else None,
            pending=bool(data.get("pending")),
            pfc_primary=str(pfc_primary) if pfc_primary else None,
            pfc_detailed=str(pfc_detailed) if pfc_detailed else None,
            institution=institution or None,
        )
