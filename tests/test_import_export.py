import asyncio
import json

import pytest
from anime_vault.import_export import apply_import, parse_export, preview_import


def sample(uid=77):
    return json.dumps({'schema_version':1,'user_id':uid,'library':[{'title_id':'av:1','status':'WATCHING','progress':4,'rating':8,'notes':'nice','favourite':True}]}).encode()


def test_valid_export_is_parsed_for_its_owner():
    row=parse_export(sample(),77)[0]
    assert row['title_id']=='av:1' and row['rating']==8 and row['favourite'] is True


def test_export_cannot_target_another_user():
    with pytest.raises(ValueError,match='different Telegram user'):
        parse_export(sample(99),77)


@pytest.mark.parametrize('change',[
    {'status':'NOT_WATCHED'}, {'progress':-1}, {'rating':11}, {'favourite':'yes'}, {'notes':3}
])
def test_invalid_library_fields_are_rejected(change):
    data={'schema_version':1,'user_id':77,'library':[{'title_id':'av:1','status':'WATCHING','progress':0,'rating':None,'notes':'','favourite':False,**change}]}
    with pytest.raises(ValueError): parse_export(json.dumps(data).encode(),77)


def test_duplicate_title_ids_are_rejected():
    data={'schema_version':1,'user_id':77,'library':[{'title_id':'av:1','status':'WATCHED'},{'title_id':'av:1','status':'WATCHED'}]}
    with pytest.raises(ValueError,match='unique'): parse_export(json.dumps(data).encode(),77)


def test_oversized_import_is_rejected():
    with pytest.raises(ValueError,match='5 MB'): parse_export(b'x'*(5_000_001),77)


class Result:
    def __init__(self,upserted_id=None,matched_count=0): self.upserted_id=upserted_id; self.matched_count=matched_count

class Titles:
    async def find_one(self,q): return {'_id':q['_id']} if q['_id']=='av:1' else None

class Library:
    def __init__(self): self.docs={(77,'av:1'):{'user_id':77,'title_id':'av:1','status':'WATCHED','rating':10,'notes':'keep'}}
    async def find_one(self,q): return self.docs.get((q['user_id'],q['title_id']))
    async def update_one(self,q,update,upsert=False):
        key=(q['user_id'],q['title_id'])
        if key in self.docs: return Result(matched_count=1)
        self.docs[key]=update['$setOnInsert']; return Result(upserted_id=key)

class DB:
    def __init__(self): self.titles=Titles(); self.user_library=Library()

def test_import_preview_and_apply_never_overwrite_existing_entry():
    async def run():
        db=DB(); rows=[{'title_id':'av:1','status':'PLAN_TO_WATCH','rating':None,'progress':0}]
        report=await preview_import(db,77,rows)
        assert report=={'inserted':0,'updated':0,'skipped':1,'rejected':0}
        result=await apply_import(db,77,rows)
        assert result['skipped']==1
        assert db.user_library.docs[(77,'av:1')]['status']=='WATCHED'
        assert db.user_library.docs[(77,'av:1')]['rating']==10
    import asyncio; asyncio.run(run())
