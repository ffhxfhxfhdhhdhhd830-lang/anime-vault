from types import SimpleNamespace

import pytest
from anime_vault.bot import authorized


class Users:
    def __init__(self, user=None): self.user=user
    async def find_one(self, query): return self.user if self.user and self.user.get('user_id')==query['user_id'] else None


def ctx(owner=1, allow=(), record=None):
    db=SimpleNamespace(authorized_users=Users(record))
    return SimpleNamespace(application=SimpleNamespace(bot_data={'settings':SimpleNamespace(owner_id=owner,allowed_user_ids=allow),'db':SimpleNamespace(db=db)}))


@pytest.mark.asyncio
async def test_owner_is_authorized():
    assert await authorized(SimpleNamespace(effective_user=SimpleNamespace(id=1)),ctx())


@pytest.mark.asyncio
async def test_approved_normal_user_is_authorized():
    record={'user_id':2,'role':'USER','active':True}
    assert await authorized(SimpleNamespace(effective_user=SimpleNamespace(id=2)),ctx(record=record))


@pytest.mark.asyncio
async def test_environment_allowlist_is_authorized():
    assert await authorized(SimpleNamespace(effective_user=SimpleNamespace(id=3)),ctx(allow=(3,)))


@pytest.mark.asyncio
async def test_unknown_user_is_denied():
    class Message:
        async def reply_text(self,text): return None
    update=SimpleNamespace(effective_user=SimpleNamespace(id=8),effective_message=Message(),callback_query=None)
    assert not await authorized(update,ctx())


@pytest.mark.asyncio
async def test_admin_only_access_requires_owner():
    update=SimpleNamespace(effective_user=SimpleNamespace(id=2),callback_query=None,effective_message=None)
    assert not await authorized(update,ctx(record={'user_id':2,'role':'ADMIN','active':True}),owner=True)
    assert await authorized(SimpleNamespace(effective_user=SimpleNamespace(id=1)),ctx(),owner=True)
