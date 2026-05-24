"""Unit tests for the categorization engine and rules CRUD.

Covers: priority ordering, first-match-wins, no-match fallback,
CRUD operations, and integration with the CSV parser's categorize().
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Bootstrap project root
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.accounting.categorization import (
    categorize_transaction,
    categorize_all_uncategorized,
    seed_rules_from_vba,
)
from modules.banking.csv_import import categorize as categorize_parsed
from modules.banking.rules import (
    create_rule,
    update_rule,
    delete_rule,
    get_rule,
    list_rules,
    match_pattern,
)


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture
def db():
    """Create an in-memory SQLite DB with the categorization_rules and
    transactions tables.  Yields a connection, then closes."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE categorization_rules ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  pattern TEXT NOT NULL UNIQUE,"
        "  category TEXT NOT NULL,"
        "  priority INTEGER NOT NULL DEFAULT 100,"
        "  is_active INTEGER NOT NULL DEFAULT 1,"
        "  created_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    conn.execute(
        "CREATE TABLE transactions ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  txn_date TEXT NOT NULL,"
        "  account TEXT,"
        "  account_type TEXT,"
        "  description TEXT,"
        "  amount REAL NOT NULL,"
        "  balance REAL,"
        "  expense_category TEXT,"
        "  txn_type TEXT,"
        "  project_id INTEGER,"
        "  month INTEGER,"
        "  source_row INTEGER,"
        "  imported_at TEXT NOT NULL DEFAULT (datetime('now')),"
        "  source TEXT DEFAULT 'excel_sync',"
        "  external_id TEXT,"
        "  bank_connection_id INTEGER,"
        "  auto_categorized INTEGER DEFAULT 0,"
        "  needs_review INTEGER DEFAULT 0,"
        "  sync_run_id INTEGER,"
        "  UNIQUE (txn_date, amount, description)"
        ")"
    )
    yield conn
    conn.close()


@pytest.fixture
def db_with_rules(db):
    """DB with a few test rules at different priorities."""
    db.execute(
        "INSERT INTO categorization_rules (pattern, category, priority) "
        "VALUES ('uber eats', 'Meals & Entertainment', 40)"
    )
    db.execute(
        "INSERT INTO categorization_rules (pattern, category, priority) "
        "VALUES ('uber technolog', 'Travel and Transportation', 45)"
    )
    db.execute(
        "INSERT INTO categorization_rules (pattern, category, priority) "
        "VALUES ('microsoft', 'Software Subscriptions', 50)"
    )
    db.execute(
        "INSERT INTO categorization_rules (pattern, category, priority) "
        "VALUES ('zelle payment from', 'Engineering Revenue', 20)"
    )
    db.execute(
        "INSERT INTO categorization_rules (pattern, category, priority) "
        "VALUES ('publix|walmart', 'Office Groceries', 80)"
    )
    db.commit()
    return db


# ====================================================================
# categorize_transaction
# ====================================================================

class TestCategorizeTransaction:
    def test_first_match_wins_by_priority(self, db_with_rules):
        """'uber eats' (priority 40) should match before 'uber technolog' (45)."""
        result = categorize_transaction(db_with_rules, "UBER EATS ORDER")
        assert result == "Meals & Entertainment"

    def test_case_insensitive(self, db_with_rules):
        result = categorize_transaction(db_with_rules, "microsoft office")
        assert result == "Software Subscriptions"

    def test_no_match_returns_none(self, db_with_rules):
        result = categorize_transaction(db_with_rules, "COMPLETELY UNKNOWN VENDOR")
        assert result is None

    def test_empty_description_returns_none(self, db_with_rules):
        result = categorize_transaction(db_with_rules, "")
        assert result is None

    def test_none_description_returns_none(self, db_with_rules):
        result = categorize_transaction(db_with_rules, None)
        assert result is None

    def test_regex_alternation(self, db_with_rules):
        """publix|walmart pattern should match either."""
        assert categorize_transaction(db_with_rules, "PUBLIX SUPER MARKETS") == "Office Groceries"
        assert categorize_transaction(db_with_rules, "WALMART STORE") == "Office Groceries"

    def test_inactive_rule_ignored(self, db):
        db.execute(
            "INSERT INTO categorization_rules (pattern, category, priority, is_active) "
            "VALUES ('test_pattern', 'Test Category', 10, 0)"
        )
        db.commit()
        result = categorize_transaction(db, "test_pattern match")
        assert result is None

    def test_invalid_regex_skipped(self, db):
        """Rules with invalid regex should be skipped, not crash."""
        db.execute(
            "INSERT INTO categorization_rules (pattern, category, priority) "
            "VALUES ('[invalid', 'Bad Rule', 10)"
        )
        db.execute(
            "INSERT INTO categorization_rules (pattern, category, priority) "
            "VALUES ('valid_pattern', 'Good Rule', 20)"
        )
        db.commit()
        result = categorize_transaction(db, "valid_pattern here")
        assert result == "Good Rule"


class TestCategorizeAllUncategorized:
    def test_categorizes_null_categories(self, db_with_rules):
        db_with_rules.execute(
            "INSERT INTO transactions (txn_date, description, amount) "
            "VALUES ('2026-05-01', 'UBER EATS ORDER', -25.00)"
        )
        db_with_rules.execute(
            "INSERT INTO transactions (txn_date, description, amount) "
            "VALUES ('2026-05-02', 'MICROSOFT OFFICE', -15.00)"
        )
        db_with_rules.commit()

        updated = categorize_all_uncategorized(db_with_rules)
        assert updated == 2

        rows = db_with_rules.execute(
            "SELECT description, expense_category FROM transactions ORDER BY id"
        ).fetchall()
        assert rows[0]["expense_category"] == "Meals & Entertainment"
        assert rows[1]["expense_category"] == "Software Subscriptions"

    def test_skips_already_categorized(self, db_with_rules):
        db_with_rules.execute(
            "INSERT INTO transactions (txn_date, description, amount, expense_category) "
            "VALUES ('2026-05-01', 'UBER EATS', -25.00, 'Already Set')"
        )
        db_with_rules.commit()

        updated = categorize_all_uncategorized(db_with_rules)
        assert updated == 0

    def test_returns_zero_when_nothing_to_do(self, db_with_rules):
        updated = categorize_all_uncategorized(db_with_rules)
        assert updated == 0


# ====================================================================
# categorize (from csv_import)
# ====================================================================

class TestCategorizeParsed:
    def test_marks_auto_categorized(self, db_with_rules):
        txns = [
            {"description": "UBER EATS", "txn_date": "2026-05-01", "amount": -25.0},
        ]
        result = categorize_parsed(txns, db_with_rules)
        assert result[0]["expense_category"] == "Meals & Entertainment"
        assert result[0]["auto_categorized"] == 1
        assert result[0]["needs_review"] == 0

    def test_marks_needs_review(self, db_with_rules):
        txns = [
            {"description": "UNKNOWN VENDOR XYZ", "txn_date": "2026-05-01", "amount": -10.0},
        ]
        result = categorize_parsed(txns, db_with_rules)
        assert result[0]["expense_category"] is None
        assert result[0]["auto_categorized"] == 0
        assert result[0]["needs_review"] == 1


# ====================================================================
# Rules CRUD
# ====================================================================

class TestRulesCRUD:
    def test_create_rule(self, db):
        rule_id = create_rule(db, "new_pattern", "New Category", 50)
        assert rule_id > 0
        row = db.execute(
            "SELECT * FROM categorization_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        assert row["pattern"] == "new_pattern"
        assert row["category"] == "New Category"
        assert row["priority"] == 50
        assert row["is_active"] == 1

    def test_create_rule_empty_pattern_raises(self, db):
        with pytest.raises(ValueError, match="Pattern must not be empty"):
            create_rule(db, "", "Category")

    def test_create_rule_empty_category_raises(self, db):
        with pytest.raises(ValueError, match="Category must not be empty"):
            create_rule(db, "pattern", "")

    def test_create_rule_invalid_regex_raises(self, db):
        with pytest.raises(ValueError, match="Invalid regex"):
            create_rule(db, "[invalid", "Category")

    def test_create_duplicate_raises_integrity_error(self, db):
        create_rule(db, "unique_pattern", "Cat A")
        with pytest.raises(sqlite3.IntegrityError):
            create_rule(db, "unique_pattern", "Cat B")

    def test_update_rule(self, db):
        rule_id = create_rule(db, "original", "Cat A", 50)
        updated = update_rule(
            db, rule_id, pattern="modified", category="Cat B", priority=10
        )
        assert updated is True
        row = get_rule(db, rule_id)
        assert row["pattern"] == "modified"
        assert row["category"] == "Cat B"
        assert row["priority"] == 10

    def test_update_rule_no_changes(self, db):
        rule_id = create_rule(db, "test", "Cat", 50)
        updated = update_rule(db, rule_id)
        assert updated is False

    def test_update_rule_invalid_regex_raises(self, db):
        rule_id = create_rule(db, "test", "Cat", 50)
        with pytest.raises(ValueError, match="Invalid regex"):
            update_rule(db, rule_id, pattern="[bad")

    def test_delete_rule(self, db):
        rule_id = create_rule(db, "to_delete", "Cat", 50)
        deleted = delete_rule(db, rule_id)
        assert deleted is True
        assert get_rule(db, rule_id) is None

    def test_delete_nonexistent_returns_false(self, db):
        deleted = delete_rule(db, 99999)
        assert deleted is False

    def test_get_rule_returns_dict(self, db):
        rule_id = create_rule(db, "test", "Cat", 50)
        rule = get_rule(db, rule_id)
        assert isinstance(rule, dict)
        assert rule["pattern"] == "test"

    def test_get_rule_nonexistent_returns_none(self, db):
        assert get_rule(db, 99999) is None

    def test_list_rules_ordered_by_priority(self, db):
        create_rule(db, "low_priority", "Cat A", 100)
        create_rule(db, "high_priority", "Cat B", 10)
        create_rule(db, "mid_priority", "Cat C", 50)

        rules = list_rules(db)
        priorities = [r["priority"] for r in rules]
        assert priorities == [10, 50, 100]

    def test_list_rules_active_only(self, db):
        create_rule(db, "active_rule", "Cat A", 10, is_active=True)
        create_rule(db, "inactive_rule", "Cat B", 20, is_active=False)

        all_rules = list_rules(db)
        assert len(all_rules) == 2

        active_rules = list_rules(db, active_only=True)
        assert len(active_rules) == 1
        assert active_rules[0]["pattern"] == "active_rule"

    def test_match_pattern_finds_match(self, db_with_rules):
        result = match_pattern(db_with_rules, "UBER EATS ORDER")
        assert result is not None
        assert result["category"] == "Meals & Entertainment"

    def test_match_pattern_no_match(self, db_with_rules):
        result = match_pattern(db_with_rules, "XYZZY NONEXISTENT")
        assert result is None

    def test_match_pattern_empty_returns_none(self, db):
        assert match_pattern(db, "") is None


# ====================================================================
# VBA seed rules
# ====================================================================

class TestSeedRules:
    def test_seed_idempotent(self, db):
        count1 = seed_rules_from_vba(db)
        assert count1 > 0
        count2 = seed_rules_from_vba(db)
        assert count2 == 0  # second run inserts nothing

    def test_seeded_rules_match_expected_categories(self, db):
        seed_rules_from_vba(db)
        # Spot check a few known patterns
        assert categorize_transaction(db, "UBER EATS ORDER") == "Meals & Entertainment"
        assert categorize_transaction(db, "MICROSOFT OFFICE 365") == "Software Subscriptions"
        assert categorize_transaction(db, "PUBLIX SUPER MARKETS") == "Office Groceries"
        assert categorize_transaction(db, "ZELLE PAYMENT FROM JOHN") == "Engineering Revenue"
