import pytest
from anime_vault.config import Settings


def test_missing_owner_fails_closed(monkeypatch):
    monkeypatch.setenv('BOT_TOKEN','placeholder')
    monkeypatch.setenv('MONGODB_URI','mongodb://localhost')
    monkeypatch.delenv('OWNER_TELEGRAM_ID',raising=False)
    with pytest.raises(ValueError, match='OWNER_TELEGRAM_ID'):
        Settings.from_env()
