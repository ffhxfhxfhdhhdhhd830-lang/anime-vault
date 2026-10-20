import asyncio
from copy import deepcopy

from anime_vault.catalog import entries
from anime_vault.models import Status
from anime_vault.services import CatalogService


class Result:
    def __init__(self, inserted_id=None): self.upserted_id = inserted_id


class FakeTitles:
    def __init__(self): self.docs = {}
    async def find_one(self, query): return deepcopy(self.docs.get(query['_id']))
    async def update_one(self, query, update, upsert=False):
        key=query['_id']; existed=key in self.docs
        if '$setOnInsert' in update and not existed: self.docs[key]=deepcopy(update['$setOnInsert'])
        elif '$set' in update and existed: self.docs[key].update(deepcopy(update['$set']))
        elif '$set' in update and not existed and upsert: self.docs[key]=deepcopy(update['$set'])
        return Result(None if existed else key)
    async def count_documents(self, query): return sum(1 for key in query['_id']['$in'] if key in self.docs)


class FakeDB:
    def __init__(self): self.titles=FakeTitles(); self.user_library=FakeLibrary()

class FakeLibrary:
    def __init__(self): self.docs={}
    async def update_one(self,query,update,upsert=False):
        key=(query['user_id'],query['title_id'])
        if key in self.docs: return Result()
        self.docs[key]=deepcopy(update['$setOnInsert']); return Result(key)

class Cursor:
    def __init__(self, rows): self.rows=rows
    def limit(self, n): self.rows=self.rows[:n]; return self
    async def to_list(self, length=None): return deepcopy(self.rows[:length])

class MetadataTitles(FakeTitles):
    def find(self, query):
        return Cursor([doc for doc in self.docs.values() if doc.get('metadata_status')==query.get('metadata_status')])


def test_seed_is_idempotent_and_only_fills_missing_fields():
    async def run():
        db=FakeDB(); service=CatalogService(db); data=entries()
        db.user_library.docs[(999,'av:existing')]={'user_id':999,'title_id':'av:existing','status':'WATCHED','rating':10,'notes':'keep'}
        prior_library=deepcopy(db.user_library.docs)
        # Existing entries and user library data live in separate collections by design.
        title=data[0]
        db.titles.docs[title['_id']]={**deepcopy(title), 'genres':['Drama'], 'synopsis':'Existing', 'updated_at':'original'}
        first=await service.seed(data)
        assert len(db.titles.docs)==145
        assert first['database_total']==145
        assert db.titles.docs[title['_id']]['genres']==['Drama']
        assert db.titles.docs[title['_id']]['synopsis']=='Existing'
        assert db.user_library.docs==prior_library
        second=await service.seed(data)
        assert second['newly_inserted']==0
        assert len(db.titles.docs)==145
        dry=await service.seed(data,dry_run=True)
        assert dry['newly_inserted']==0
    asyncio.run(run())


def test_personal_defaults_never_set_over_existing_status():
    # Explicitly documents the catalog/library separation and the safe default.
    assert Status.PLAN_TO_WATCH.value == 'PLAN_TO_WATCH'


def test_adding_title_twice_creates_one_personal_entry():
    async def run():
        db=FakeDB(); svc=CatalogService(db); tid=entries()[0]['_id']
        assert await svc.add_to_library(17,tid) is True
        assert await svc.add_to_library(17,tid) is False
        assert len(db.user_library.docs)==1
        assert db.user_library.docs[(17,tid)]['status']=='PLAN_TO_WATCH'
    asyncio.run(run())


def test_metadata_provider_enriches_only_missing_fields():
    from anime_vault.services import MetadataEnricher
    class Provider:
        async def search(self, title):
            return {'id':123,'idMal':456,'title':{'english':title,'romaji':title,'native':'原題'},'genres':['Drama'],
                    'description':'Provider plot','episodes':12,'seasonYear':2020,'siteUrl':'https://anilist.co/anime/123',
                    'coverImage':{'large':'https://img.example/poster.jpg'},'studios':{'nodes':[{'name':'Studio'}]},'averageScore':81}
    async def run():
        db=FakeDB(); db.titles=MetadataTitles(); doc=entries()[0]
        doc['synopsis']='User supplied synopsis'; db.titles.docs[doc['_id']]=deepcopy(doc)
        updated,failed=await MetadataEnricher(db,Provider()).enrich_incomplete()
        saved=db.titles.docs[doc['_id']]
        assert (updated,failed)==(1,0)
        assert saved['synopsis']=='User supplied synopsis'
        assert saved['genres']==['Drama']
        assert saved['external_ids']=={'anilist':123,'mal':456}
    asyncio.run(run())


def test_failed_metadata_lookup_is_counted_and_retryable():
    from anime_vault.services import MetadataEnricher
    class Broken:
        async def search(self, title): raise TimeoutError()
    async def run():
        db=FakeDB(); db.titles=MetadataTitles(); doc=entries()[0]; db.titles.docs[doc['_id']]=deepcopy(doc)
        updated,failed=await MetadataEnricher(db,Broken()).enrich_incomplete()
        assert (updated,failed)==(0,1)
        assert db.titles.docs[doc['_id']]['metadata_status']=='incomplete'
    asyncio.run(run())


def test_local_recommendations_rank_matching_genres_and_exclude_library():
    class Query:
        def __init__(self, rows): self.rows=rows
        def limit(self,n): self.rows=self.rows[:n]; return self
        async def to_list(self,length=None): return deepcopy(self.rows[:length])
    class ReadLibrary:
        def find(self,query,projection=None): return Query([{'user_id':42,'title_id':'av:seed','status':'WATCHED','rating':9,'favourite':True}])
    class Titles:
        docs=[{'_id':'av:seed','title':'Seed','genres':['Drama'],'studios':['Studio']},
              {'_id':'av:similar','title':'Similar','genres':['Drama'],'studios':[]},
              {'_id':'av:other','title':'Other','genres':['Comedy'],'studios':[]}]
        def find(self,query):
            cond=query['_id'];
            if '$in' in cond: rows=[x for x in self.docs if x['_id'] in cond['$in']]
            else: rows=[x for x in self.docs if x['_id'] not in cond.get('$nin',[])]
            return Query(rows)
    class DB:
        user_library=ReadLibrary(); titles=Titles()
    async def run():
        result=await CatalogService(DB()).recommendations(42)
        assert [x['_id'] for x in result]==['av:similar']
        assert result[0]['recommendation_reason']=='Drama'
    asyncio.run(run())


def test_anilist_provider_retries_rate_limit(monkeypatch):
    import asyncio
    from anime_vault.services import AniListProvider
    class Response:
        def __init__(self,status): self.status_code=status
        def raise_for_status(self):
            if self.status_code>=400: raise RuntimeError('http failure')
        def json(self): return {'data':{'Media':{'id':1}}}
    class Client:
        def __init__(self): self.calls=0
        async def post(self,*args,**kwargs):
            self.calls+=1; return Response(429 if self.calls==1 else 200)
    async def no_sleep(_): return None
    monkeypatch.setattr(asyncio,'sleep',no_sleep)
    async def run():
        client=Client(); result=await AniListProvider(client).search('Seed')
        assert result=={'id':1} and client.calls==2
    asyncio.run(run())
