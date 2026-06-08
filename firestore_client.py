"""Firestore persistence for subscriptions with local JSON fallback (Task 5)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, cast

from google.cloud.firestore_v1 import Client
from google.cloud.firestore_v1.base_document import DocumentSnapshot

USER_SUBSCRIPTIONS_COLLECTION = "user_subscriptions"
GROUP_ACTIVATIONS_COLLECTION = "group_activations"

_db_client: Optional[Client] = None


def _subscriptions_json_path() -> str:
    return os.getenv(
        "SUBSCRIPTIONS_JSON_PATH",
        os.path.join(os.path.dirname(__file__), "subscriptions.json"),
    )


def _default_user_subscription() -> Dict[str, Any]:
    return {
        "subscribed": False,
        "subscription_expires_at": None,
        "plan_type": None,
        "subscription_activated_at": None,
    }


def _default_group_activation() -> Dict[str, Any]:
    return {
        "subscription_activated_by_user_id": None,
        "subscription_activated_at": None,
        "subscription_expires_at": None,
    }


def _merge_settings(defaults: Dict[str, Any], data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = defaults.copy()
    merged.update(data or {})
    return merged


def _get_db() -> Client:
    global _db_client
    if _db_client is None:
        database_id = os.getenv("FIRESTORE_DATABASE_ID", "line-trnsltrbt-db")
        _db_client = Client(database=database_id)
    return _db_client


def _load_json_store() -> Dict[str, Any]:
    try:
        with open(_subscriptions_json_path(), "r", encoding="utf-8") as store_file:
            data = json.load(store_file)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"ERROR loading subscriptions from JSON fallback: {e}")
        return {}


def _save_json_store(store: Dict[str, Any]) -> None:
    try:
        with open(_subscriptions_json_path(), "w", encoding="utf-8") as store_file:
            json.dump(store, store_file, indent=2, ensure_ascii=False)
            store_file.write("\n")
    except Exception as e:
        print(f"ERROR saving subscriptions to JSON fallback: {e}")
        raise


def _get_from_json(section: str, doc_id: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    store = _load_json_store()
    section_data = store.get(section, {})
    if not isinstance(section_data, dict):
        section_data = {}
    return _merge_settings(defaults, section_data.get(doc_id))


def _save_to_json(section: str, doc_id: str, data: Dict[str, Any]) -> None:
    store = _load_json_store()
    section_data = store.get(section, {})
    if not isinstance(section_data, dict):
        section_data = {}
    section_data[doc_id] = data
    store[section] = section_data
    _save_json_store(store)


def _get_firestore_doc(collection: str, doc_id: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    db = _get_db()
    doc_ref = db.collection(collection).document(doc_id)
    doc = cast(DocumentSnapshot, doc_ref.get())
    if doc.exists:
        return _merge_settings(defaults, doc.to_dict())
    return defaults.copy()


def _set_firestore_doc(collection: str, doc_id: str, data: Dict[str, Any]) -> None:
    db = _get_db()
    doc_ref = db.collection(collection).document(doc_id)
    doc_ref.set(data)


def get_user_subscription(user_id: str) -> Dict[str, Any]:
    """Load personal subscription fields from Firestore with JSON fallback."""
    defaults = _default_user_subscription()
    try:
        return _get_firestore_doc(USER_SUBSCRIPTIONS_COLLECTION, user_id, defaults)
    except Exception as e:
        print(f"ERROR loading user subscription from Firestore: {e}")
        return _get_from_json("users", user_id, defaults)


def save_user_subscription(user_id: str, updates: Dict[str, Any]) -> None:
    """Persist personal subscription fields to Firestore and JSON fallback."""
    current = get_user_subscription(user_id)
    current.update(updates)

    firestore_error: Optional[Exception] = None
    try:
        _set_firestore_doc(USER_SUBSCRIPTIONS_COLLECTION, user_id, current)
    except Exception as e:
        firestore_error = e
        print(f"ERROR saving user subscription to Firestore: {e}")

    try:
        _save_to_json("users", user_id, current)
    except Exception:
        if firestore_error is not None:
            raise firestore_error
        raise

    if firestore_error is not None:
        return


def get_group_activation(group_id: str) -> Dict[str, Any]:
    """Load group activation fields from Firestore with JSON fallback."""
    defaults = _default_group_activation()
    try:
        return _get_firestore_doc(GROUP_ACTIVATIONS_COLLECTION, group_id, defaults)
    except Exception as e:
        print(f"ERROR loading group activation from Firestore: {e}")
        return _get_from_json("groups", group_id, defaults)


def save_group_activation(group_id: str, updates: Dict[str, Any]) -> None:
    """Persist group activation fields to Firestore and JSON fallback."""
    current = get_group_activation(group_id)
    current.update(updates)

    firestore_error: Optional[Exception] = None
    try:
        _set_firestore_doc(GROUP_ACTIVATIONS_COLLECTION, group_id, current)
    except Exception as e:
        firestore_error = e
        print(f"ERROR saving group activation to Firestore: {e}")

    try:
        _save_to_json("groups", group_id, current)
    except Exception:
        if firestore_error is not None:
            raise firestore_error
        raise

    if firestore_error is not None:
        return
