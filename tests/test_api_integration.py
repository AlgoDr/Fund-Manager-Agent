"""Integration / regression tests for the Voice Spend Manager API.

Covers the three-expense transcript regression case plus CRUD and budget
endpoints. These tests hit the real FastAPI app (TestClient) and a real
SQLite database.
"""
import os
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from server import app, USER_ID

IST = ZoneInfo("Asia/Kolkata")
TODAY_ISO = datetime.now(IST).date().isoformat()
THREE_EXPENSE_TRANSCRIPT = (
    "Today I spent 350 rupees for Uber, 40 rupees for Samosa Pao, "
    "and 200 rupees for lunch."
)


def _init_schema(db_path):
    """Run schema.sql against a fresh SQLite database."""
    import sqlite3

    schema_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "schema.sql",
    )
    with open(schema_file) as f:
        schema_sql = f.read()
    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a TestClient with a temporary SQLite database initialized from schema.sql."""
    db_file = tmp_path / "test_voice_spend.db"
    monkeypatch.setattr("services.database.DB_PATH", db_file)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    _init_schema(db_file)
    with TestClient(app) as c:
        yield c


class TestDraftRegression:
    """Regression test for the three-expense transcript."""

    def test_three_expense_draft(self, client):
        """Direct /api/draft returns three expenses, provider is groq."""
        resp = client.post(
            "/api/draft",
            json={"transcript": THREE_EXPENSE_TRANSCRIPT},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["provider_used"] == "groq", body
        assert body["ready_to_confirm"] is True
        expenses = body["expenses"]
        assert len(expenses) == 3, f"Expected 3 expenses, got {len(expenses)}"

        amounts = {e["amount_paise"] for e in expenses}
        assert 35000 in amounts, f"35000 paise not in {amounts}"
        assert 4000 in amounts, f"4000 paise not in {amounts}"
        assert 20000 in amounts, f"20000 paise not in {amounts}"

        merchants = {e["merchant"] for e in expenses}
        assert "Uber" in merchants, f"Uber not in {merchants}"

        today = datetime.now(IST).date().isoformat()
        for e in expenses:
            if e["resolved_date"] is not None:
                assert e["resolved_date"] == today, f"Date {e['resolved_date']} != {today}"

    def test_draft_does_not_persist(self, client):
        """Draft endpoint must not write to the expenses table."""
        client.post("/api/draft", json={"transcript": THREE_EXPENSE_TRANSCRIPT})
        resp = client.get("/api/expenses/today")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0, "Draft should not persist"


class TestCRUD:
    """Create, read, update, delete for expenses."""

    def test_full_crud_flow(self, client):
        # First confirm some expenses so we have something to CRUD
        confirm_resp = client.post(
            "/api/confirm",
            json={
                "expenses": [
                    {
                        "amount_paise": 35000,
                        "currency": "INR",
                        "category": "Transport",
                        "merchant": "Uber",
                        "note": "Office ride",
                        "spent_at": TODAY_ISO,
                        "source_transcript": "test",
                    }
                ],
                "idempotency_key": "test-key-1",
            },
        )
        assert confirm_resp.status_code == 200
        expense_id = confirm_resp.json()["transaction_ids"][0]

        # Read
        get_resp = client.get(f"/api/expenses/{expense_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["merchant"] == "Uber"

        # List
        list_resp = client.get("/api/expenses")
        assert list_resp.status_code == 200
        assert list_resp.json()["count"] == 1

        # Update
        update_resp = client.put(
            f"/api/expenses/{expense_id}",
            json={"merchant": "Ola", "note": "Updated note"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["merchant"] == "Ola"
        assert update_resp.json()["note"] == "Updated note"

        # Delete
        del_resp = client.delete(f"/api/expenses/{expense_id}")
        assert del_resp.status_code == 200

        # Verify deletion
        get_resp2 = client.get(f"/api/expenses/{expense_id}")
        assert get_resp2.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/expenses/does-not-exist")
        assert resp.status_code == 404

    def test_update_nonexistent_returns_404(self, client):
        resp = client.put(
            "/api/expenses/does-not-exist",
            json={"merchant": "X"},
        )
        assert resp.status_code == 404


class TestBudgets:
    """Budget set/list with 80%/100% warnings."""

    def test_set_and_list_budget(self, client):
        """Set a Food budget of 5000 rupees for Nov 2026."""
        set_resp = client.post(
            "/api/budgets",
            json={
                "category": "Food",
                "month": "2026-11",
                "amount_paise": 500000,
            },
        )
        assert set_resp.status_code == 200
        body = set_resp.json()
        assert body["category"] == "Food"
        assert body["month"] == "2026-11"
        assert body["amount_paise"] == 500000

        list_resp = client.get("/api/budgets?month=2026-11")
        assert list_resp.status_code == 200
        budgets = list_resp.json()["budgets"]
        assert len(budgets) == 1
        assert budgets[0]["category"] == "Food"
        assert budgets[0]["warning"] is None

    def test_invalid_month_format(self, client):
        resp = client.post(
            "/api/budgets",
            json={
                "category": "Food",
                "month": "November-2026",
                "amount_paise": 1000,
            },
        )
        assert resp.status_code == 400

    def test_invalid_category(self, client):
        resp = client.post(
            "/api/budgets",
            json={
                "category": "NotACategory",
                "month": "2026-11",
                "amount_paise": 1000,
            },
        )
        assert resp.status_code == 400

    def test_budget_warning_at_80_percent(self, client):
        """Spend 4000 rupees on Food (80% of 5000 budget)."""
        client.post(
            "/api/confirm",
            json={
                "expenses": [
                    {
                        "amount_paise": 400000,
                        "currency": "INR",
                        "category": "Food",
                        "merchant": "Restaurant",
                        "note": "Dinner",
                        "spent_at": TODAY_ISO,
                        "source_transcript": "test",
                    }
                ],
                "idempotency_key": "budget-test-1",
            },
        )
        client.post(
            "/api/budgets",
            json={
                "category": "Food",
                "month": "2026-11",
                "amount_paise": 500000,
            },
        )
        list_resp = client.get("/api/budgets?month=2026-11")
        budgets = list_resp.json()["budgets"]
        food_budget = [b for b in budgets if b["category"] == "Food"][0]
        assert food_budget["actual_spent_paise"] == 400000
        assert food_budget["percent_used"] == 80.0
        assert food_budget["warning"] == "80% budget warning"

    def test_budget_warning_at_100_percent(self, client):
        """Spend exactly 5000 rupees on Food (100% of 5000 budget)."""
        client.post(
            "/api/confirm",
            json={
                "expenses": [
                    {
                        "amount_paise": 500000,
                        "currency": "INR",
                        "category": "Food",
                        "merchant": "Restaurant",
                        "note": "Big dinner",
                        "spent_at": TODAY_ISO,
                        "source_transcript": "test",
                    }
                ],
                "idempotency_key": "budget-test-2",
            },
        )
        client.post(
            "/api/budgets",
            json={
                "category": "Food",
                "month": "2026-11",
                "amount_paise": 500000,
            },
        )
        list_resp = client.get("/api/budgets?month=2026-11")
        budgets = list_resp.json()["budgets"]
        food_budget = [b for b in budgets if b["category"] == "Food"][0]
        assert food_budget["percent_used"] == 100.0
        assert food_budget["warning"] == "100% budget reached"


class TestTodayEndpoint:
    """Test the existing /api/expenses/today endpoint."""

    def test_today_returns_expenses(self, client):
        client.post(
            "/api/confirm",
            json={
                "expenses": [
                    {
                        "amount_paise": 35000,
                        "currency": "INR",
                        "category": "Transport",
                        "merchant": "Uber",
                        "note": "Test",
                        "spent_at": TODAY_ISO,
                        "source_transcript": "test",
                    }
                ],
                "idempotency_key": "today-test-1",
            },
        )
        resp = client.get("/api/expenses/today")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] >= 1
        assert body["total_rupees"] > 0