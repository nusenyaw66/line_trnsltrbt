"""Tests for subscription Firestore persistence (Task 5)."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

UTC = timezone.utc
FUTURE = datetime(2027, 1, 1, tzinfo=UTC)
PAST = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
def subscriptions_json_path(tmp_path, monkeypatch):
    path = tmp_path / "subscriptions.json"
    monkeypatch.setenv("SUBSCRIPTIONS_JSON_PATH", str(path))
    return path


def _mock_firestore_unavailable():
    return patch(
        "firestore_client._get_db",
        side_effect=Exception("Firestore unavailable"),
    )


def test_get_user_subscription_defaults_json_fallback(subscriptions_json_path):
    with _mock_firestore_unavailable():
        import firestore_client
        from firestore_client import get_user_subscription

        settings = get_user_subscription("U123")

    assert settings["subscribed"] is False
    assert settings["subscription_expires_at"] is None
    assert settings["plan_type"] is None


def test_save_user_subscription_persists_to_json(subscriptions_json_path):
    with _mock_firestore_unavailable():
        from firestore_client import get_user_subscription, save_user_subscription

        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": FUTURE.isoformat(),
                "plan_type": "premium",
            },
        )
        settings = get_user_subscription("U123")

    assert settings["subscribed"] is True
    assert settings["plan_type"] == "premium"

    stored = json.loads(subscriptions_json_path.read_text(encoding="utf-8"))
    assert stored["users"]["U123"]["subscribed"] is True


def test_save_group_activation_persists_to_json(subscriptions_json_path):
    with _mock_firestore_unavailable():
        from firestore_client import get_group_activation, save_group_activation

        save_group_activation(
            "G456",
            {
                "subscription_activated_by_user_id": "U123",
                "subscription_expires_at": FUTURE.isoformat(),
            },
        )
        settings = get_group_activation("G456")

    assert settings["subscription_activated_by_user_id"] == "U123"
    assert settings["subscription_expires_at"] == FUTURE.isoformat()


def test_save_user_subscription_writes_to_firestore_when_available(subscriptions_json_path):
    mock_doc = MagicMock()
    mock_doc.exists = False
    mock_doc_ref = MagicMock()
    mock_doc_ref.get.return_value = mock_doc
    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_doc_ref
    mock_db = MagicMock()
    mock_db.collection.return_value = mock_collection

    with patch("firestore_client._get_db", return_value=mock_db):
        from firestore_client import save_user_subscription

        save_user_subscription("U123", {"subscribed": True, "plan_type": "premium"})

    mock_db.collection.assert_called_with("user_subscriptions")
    mock_doc_ref.set.assert_called_once()
    saved = mock_doc_ref.set.call_args[0][0]
    assert saved["subscribed"] is True
    assert saved["plan_type"] == "premium"


def test_save_group_activation_writes_to_firestore_when_available(subscriptions_json_path):
    mock_doc = MagicMock()
    mock_doc.exists = False
    mock_doc_ref = MagicMock()
    mock_doc_ref.get.return_value = mock_doc
    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_doc_ref
    mock_db = MagicMock()
    mock_db.collection.return_value = mock_collection

    with patch("firestore_client._get_db", return_value=mock_db):
        from firestore_client import save_group_activation

        save_group_activation(
            "G456",
            {"subscription_activated_by_user_id": "U123"},
        )

    mock_db.collection.assert_called_with("group_activations")
    saved = mock_doc_ref.set.call_args[0][0]
    assert saved["subscription_activated_by_user_id"] == "U123"
