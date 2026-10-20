from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from bson import ObjectId

from .catalog import entries
from .models import Status, now_utc
from .services import CatalogService, MetadataEnricher
from .import_export import apply_import, parse_export, preview_import

log = logging.getLogger(__name__)
CATEGORY_LABELS = {
 "romance_movies":"🎬 Romance Movies", "action_fantasy_movies":"⚔️ Action / Fantasy Movies",
 "psychological_movies":"🧠 Psychological Movies", "action_adventure_series":"🔥 Action / Adventure Series",
 "psychological_series":"♟ Psychological Series", "romance_series":"💗 Romance Series",
 "fantasy_isekai_series":"✨ Fantasy / Isekai", "comedy_slice_of_life_series":"😂 Comedy / Slice of Life",
 "sports_music_series":"🏆 Sports / Music", "horror_thriller_series":"👻 Horror / Thriller"}
PAGE_SIZE = 8

def keyboard(rows): return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in rows])
def valid_title_id(value: str) -> bool: return bool(re.fullmatch(r'av:[0-9a-f]{20}', value))

def main_keyboard():
    return keyboard([[('🔎 Search Anime','search'),('📚 My Library','lib:0')], [('📝 Plan to Watch','status:PLAN_TO_WATCH'),('▶ Currently Watching','status:WATCHING')],
      [('✅ Watched','status:WATCHED'),('❤️ Favourites','favs:0')], [('🎌 Recommendation Catalog','catalog')],
      [('📊 My Statistics','stats'),('🎲 Random Anime','random')], [('💡 Recommend for Me','recommend')],
      [('🗂 Custom Lists','lists'),('⚙ Settings','settings')], [('📺 Where to Watch','where')]])

async def authorized(update: Update, context: ContextTypes.DEFAULT_TYPE, *, owner=False) -> bool:
    user = update.effective_user
    if not user: return False
    cfg = context.application.bot_data['settings']; db = context.application.bot_data['db'].db
    uid = user.id
    allowed = uid == cfg.owner_id or uid in cfg.allowed_user_ids
    if not allowed:
        record = await db.authorized_users.find_one({'user_id': uid, 'active': True})
        allowed = bool(record)
    if owner and uid != cfg.owner_id:
        allowed = False
    if not allowed:
        if update.callback_query: await update.callback_query.answer('Access denied.', show_alert=True)
        elif update.effective_message: await update.effective_message.reply_text('Access denied.')
        return False
    return True

async def start(update, context):
    if await authorized(update, context): await update.effective_message.reply_text('Welcome to Anime Vault. Your library is private.', reply_markup=main_keyboard())
async def help_command(update, context):
    if await authorized(update, context): await update.effective_message.reply_text('/search <title>, /add <title>, /library, /watchlist, /watching, /watched, /onhold, /dropped, /continue, /recent, /progress <title> <episodes>, /rate <title> <1-10>, /review <title> <text>, /rewatch <title>, /history, /recommend, /similar <title>, /genres, /lists, /create_list <name>, /rename_list old | new, /delete_list <name>, /move_list_item list | title | position, /where_to_watch <title>, /export, /import, /stats, /settings, /reminders, /cancel. Owner: /allow, /revoke, /users, /role, /backup, /health, /adminstats, /seed_catalog, /catalog_stats, /enrich_catalog, /catalog_incomplete, /add_recommendations_to_library.')
async def menu(update, context):
    if await authorized(update, context): await update.effective_message.reply_text('Anime Vault', reply_markup=main_keyboard())
async def settings_cmd(update, context):
    if await authorized(update, context):
        await context.application.bot_data['db'].db.user_settings.update_one({'user_id': update.effective_user.id}, {'$setOnInsert': {'region':context.application.bot_data['settings'].region,'timezone':context.application.bot_data['settings'].timezone}}, upsert=True)
        await update.effective_message.reply_text('Settings: region defaults to configured region; timezone follows your configured preference. Use /setregion IN to change it.')
async def setregion(update, context):
    if not await authorized(update, context): return
    region = context.args[0].upper() if context.args else ''
    if not re.fullmatch('[A-Z]{2}', region): return await update.effective_message.reply_text('Use a two-letter region code, e.g. /setregion IN')
    await context.application.bot_data['db'].db.user_settings.update_one({'user_id':update.effective_user.id},{'$set':{'region':region}},upsert=True)
    await update.effective_message.reply_text(f'Region saved: {region}. Availability still requires a configured authorized provider.')

async def show_page(update, context, *, category=None, query='', page=0, library=False, status=None, favourites=False):
    uid=update.effective_user.id; db=context.application.bot_data['db'].db; catalog=CatalogService(db)
    if library or status or favourites:
        filt={'user_id':uid}
        if status: filt['status']=status
        if favourites: filt['favourite']=True
        rows=await db.user_library.find(filt).sort('added_at',-1).skip(page*PAGE_SIZE).limit(PAGE_SIZE).to_list(length=PAGE_SIZE)
        docs=[]
        for row in rows:
            title=await db.titles.find_one({'_id':row['title_id']})
            if title: title['_personal_status']=row.get('status'); title['_personal_favourite']=row.get('favourite',False); docs.append(title)
        count=await db.user_library.count_documents(filt)
    else: docs,count=await catalog.search(query,category,page,PAGE_SIZE)
    lines=[]; buttons=[]
    for doc in docs:
        genres=', '.join(doc.get('genres',[])) or 'Genres unavailable'
        personal=f" | {doc['_personal_status']}" if doc.get('_personal_status') else ''
        lines.append(f"• {doc['title']} ({doc.get('release_year','year unknown')}) — {doc.get('format','unknown')}; {genres}{personal}")
        buttons.append([(doc['title'][:24],f"d:{doc['_id']}")])
    nav=[]
    if page: nav.append(('◀ Previous', f"p:{page-1}:{category or '-'}:{'l' if library else 'c'}"))
    if (page+1)*PAGE_SIZE < count: nav.append(('Next ▶',f"p:{page+1}:{category or '-'}:{'l' if library else 'c'}"))
    if nav: buttons.append(nav)
    if not docs: lines=['No matching titles found.']
    markup=InlineKeyboardMarkup([[InlineKeyboardButton(t,d) for t,d in row] for row in buttons]) if buttons else None
    text=f"{CATEGORY_LABELS.get(category, 'Anime Vault results')} — {count} title(s), page {page+1}\n\n"+'\n'.join(lines)
    if update.callback_query: await update.callback_query.edit_message_text(text,reply_markup=markup)
    else: await update.effective_message.reply_text(text,reply_markup=markup)

async def search(update, context):
    if not await authorized(update, context): return
    q=' '.join(context.args).strip()
    if not q: return await update.effective_message.reply_text('Use /search <title>.')
    await show_page(update,context,query=q)
async def add(update, context):
    if not await authorized(update, context): return
    q=' '.join(context.args).strip()
    if not q: return await update.effective_message.reply_text('Use /add <title>.')
    await show_page(update,context,query=q)
async def library(update, context):
    if await authorized(update, context): await show_page(update,context,library=True)
async def status_cmd(update,context,status):
    if await authorized(update,context): await show_page(update,context,status=status)
async def watchlist(update,context): await status_cmd(update,context,Status.PLAN_TO_WATCH.value)
async def watching(update,context): await status_cmd(update,context,Status.WATCHING.value)
async def watched(update,context): await status_cmd(update,context,Status.WATCHED.value)
async def onhold(update,context): await status_cmd(update,context,Status.ON_HOLD.value)
async def dropped(update,context): await status_cmd(update,context,Status.DROPPED.value)
async def favs(update,context):
    if await authorized(update,context): await show_page(update,context,favourites=True)

async def catalog(update, context):
    rows=[[ (label,f'cat:{key}') ] for key,label in CATEGORY_LABELS.items()]
    rows += [[('🔎 Search Catalog','csearch')],[('📚 Add All Recommendations','bulk:preview')],[('📊 Catalog Statistics','catstats')],[('🔙 Back to Menu','home')]]
    text='🎌 Recommendation Catalog\nBrowse curated categories or search the shared catalog.'
    if update.callback_query: await update.callback_query.edit_message_text(text,reply_markup=keyboard(rows))
    else: await update.effective_message.reply_text(text,reply_markup=keyboard(rows))

async def callback(update, context):
    q=update.callback_query
    if not await authorized(update,context): return
    await q.answer()
    data=q.data or ''
    if len(data.encode('utf-8'))>64: return await q.edit_message_text('Invalid action.')
    if data=='home': return await q.edit_message_text('Anime Vault',reply_markup=main_keyboard())
    if data=='catalog': return await catalog(update,context)
    if data.startswith('cat:'):
        if data[4:] not in CATEGORY_LABELS: return await q.edit_message_text('Invalid category.')
        return await show_page(update,context,category=data[4:])
    if data=='search' or data=='csearch':
        context.user_data['await_search']=True; return await q.edit_message_text('Send a title or genre to search. Use /cancel to stop.')
    if data.startswith('p:'):
        try: _,p,cat,kind=data.split(':',3); page=int(p)
        except ValueError: return await q.edit_message_text('Invalid page.')
        if page<0 or page>10000 or cat not in {'-',*CATEGORY_LABELS} or kind not in {'c','l'}: return await q.edit_message_text('Invalid page.')
        return await show_page(update,context,category=None if cat=='-' else cat,page=page,library=kind=='l')
    if data.startswith('d:'):
        tid=data[2:]
        if not valid_title_id(tid): return await q.edit_message_text('Invalid title.')
        title=await context.application.bot_data['db'].db.titles.find_one({'_id':tid})
        if not title: return await q.edit_message_text('This title is no longer available.')
        entry=await context.application.bot_data['db'].db.user_library.find_one({'user_id':update.effective_user.id,'title_id':tid})
        summary=f"{title['title']}\nFormat: {title['format']}\nGenres: {', '.join(title.get('genres',[])) or 'Unknown'}\nYear: {title.get('release_year','Unknown')}\nStatus: {entry.get('status') if entry else 'Not in your library'}\n\n{title.get('synopsis') or 'Synopsis unavailable.'}"
        links=[]
        for url in title.get('official_links',[]):
            if isinstance(url,str) and url.startswith('https://'): links.append([InlineKeyboardButton('External info',url=url)])
        await q.edit_message_text(summary,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('➕ Add to Library',callback_data=f'a:{tid}')],[InlineKeyboardButton('▶ Watching',callback_data=f's:{tid}:WATCHING'),InlineKeyboardButton('✅ Watched',callback_data=f's:{tid}:WATCHED')],[InlineKeyboardButton('❤️ Favourite',callback_data=f'f:{tid}')],[InlineKeyboardButton('📋 Add to Custom List',callback_data=f'lc:{tid}')],*links,[InlineKeyboardButton('🔙 Catalog',callback_data='catalog')]]) )
        return
    if data.startswith('a:'):
        if not valid_title_id(data[2:]): return await q.edit_message_text('Invalid title.')
        db=context.application.bot_data['db'].db
        if not await db.titles.find_one({'_id':data[2:]}): return await q.edit_message_text('Title not found.')
        ok=await CatalogService(db).add_to_library(update.effective_user.id,data[2:])
        return await q.edit_message_text('Added to Plan to Watch.' if ok else 'Already in your library.')
    if data.startswith('s:'):
        try: _,tid,new_status=data.split(':',2)
        except ValueError: return await q.edit_message_text('Invalid status action.')
        if not valid_title_id(tid): return await q.edit_message_text('Invalid title.')
        if new_status not in Status.__members__: return await q.edit_message_text('Invalid status.')
        db=context.application.bot_data['db'].db
        if not await db.titles.find_one({'_id':tid}): return await q.edit_message_text('Title not found.')
        await CatalogService(db).add_to_library(update.effective_user.id,tid)
        await db.user_library.update_one({'user_id':update.effective_user.id,'title_id':tid},{'$set':{'status':new_status,'updated_at':now_utc(),**({'completed_at':now_utc()} if new_status=='WATCHED' else {})}})
        if new_status=='WATCHED':
            await db.watch_history.insert_one({'user_id':update.effective_user.id,'title_id':tid,'event':'completed','created_at':now_utc()})
        return await q.edit_message_text(f'Status updated: {new_status}.')
    if data.startswith('f:'):
        uid=update.effective_user.id; tid=data[2:]
        if not valid_title_id(tid): return await q.edit_message_text('Invalid title.')
        db=context.application.bot_data['db'].db
        if not await db.titles.find_one({'_id':tid}): return await q.edit_message_text('Title not found.')
        await CatalogService(db).add_to_library(uid,tid)
        entry=await db.user_library.find_one({'user_id':uid,'title_id':tid})
        await db.user_library.update_one({'user_id':uid,'title_id':tid},{'$set':{'favourite':not entry.get('favourite',False)}})
        return await q.edit_message_text('Favourite updated.')
    if data.startswith('lc:'):
        uid=update.effective_user.id; tid=data[3:]
        if not valid_title_id(tid): return await q.edit_message_text('Invalid title.')
        if not await context.application.bot_data['db'].db.titles.find_one({'_id':tid}): return await q.edit_message_text('Title not found.')
        items=await context.application.bot_data['db'].db.custom_lists.find({'user_id':uid}).to_list(length=100)
        if not items: return await q.edit_message_text('Create a list first with /create_list <name>.')
        return await q.edit_message_text('Choose a list:',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(row['name'][:30],callback_data=f"la:{row['_id']}:{tid}")] for row in items]))
    if data.startswith('la:'):
        parts=data.split(':',2)
        if len(parts)!=3 or len(parts[1])!=24 or not valid_title_id(parts[2]): return await q.edit_message_text('Invalid list selection.')
        try: list_id=ObjectId(parts[1])
        except Exception: return await q.edit_message_text('Invalid list selection.')
        result=await context.application.bot_data['db'].db.custom_lists.update_one({'_id':list_id,'user_id':update.effective_user.id},{'$addToSet':{'title_ids':parts[2]}})
        return await q.edit_message_text('Added to list.' if result.matched_count else 'List not found.')
    if data.startswith('lv:'):
        try: list_id=ObjectId(data[3:])
        except Exception: return await q.edit_message_text('Invalid list.')
        row=await context.application.bot_data['db'].db.custom_lists.find_one({'_id':list_id,'user_id':update.effective_user.id})
        if not row: return await q.edit_message_text('List not found.')
        title_docs=await context.application.bot_data['db'].db.titles.find({'_id':{'$in':row.get('title_ids',[])}}).to_list(length=100)
        title_map={t['_id']:t for t in title_docs}; titles=[title_map[tid] for tid in row.get('title_ids',[]) if tid in title_map]
        buttons=[[InlineKeyboardButton(t['title'][:28],callback_data=f"d:{t['_id']}")] for t in titles]
        buttons.append([InlineKeyboardButton('Delete List',callback_data=f"ld:{row['_id']}")])
        return await q.edit_message_text(f"{row['name']} ({len(titles)} titles)",reply_markup=InlineKeyboardMarkup(buttons))
    if data.startswith('ld:'):
        try: list_id=ObjectId(data[3:])
        except Exception: return await q.edit_message_text('Invalid list.')
        row=await context.application.bot_data['db'].db.custom_lists.find_one({'_id':list_id,'user_id':update.effective_user.id})
        if not row: return await q.edit_message_text('List not found.')
        return await q.edit_message_text(f"Delete custom list ‘{row['name']}’? Its anime and library records will remain.",reply_markup=keyboard([[('Confirm delete',f'ldc:{row["_id"]}'),('Cancel','lists')]]))
    if data.startswith('ldc:'):
        try: list_id=ObjectId(data[4:])
        except Exception: return await q.edit_message_text('Invalid list.')
        result=await context.application.bot_data['db'].db.custom_lists.delete_one({'_id':list_id,'user_id':update.effective_user.id})
        return await q.edit_message_text('List deleted.' if result.deleted_count else 'List not found.')
    if data=='bulk:preview':
        if update.effective_user.id!=context.application.bot_data['settings'].owner_id: return await q.edit_message_text('Owner only.')
        total=await context.application.bot_data['db'].db.titles.count_documents({}); existing=await context.application.bot_data['db'].db.user_library.count_documents({'user_id':update.effective_user.id})
        return await q.edit_message_text(f'Add missing recommendations to your Plan to Watch?\nCatalog: {total}; your library: {existing}. Existing statuses and progress are preserved.',reply_markup=keyboard([[('Confirm','bulk:confirm'),('Cancel','catalog')]]))
    if data=='bulk:confirm':
        if update.effective_user.id!=context.application.bot_data['settings'].owner_id: return await q.edit_message_text('Owner only.')
        a,b=await CatalogService(context.application.bot_data['db'].db).bulk_add(update.effective_user.id)
        return await q.edit_message_text(f'Complete. Added {a}; already present {b}.')
    if data in ('lib:0','status:PLAN_TO_WATCH','status:WATCHING','status:WATCHED','favs:0'):
        if data=='lib:0': return await show_page(update,context,library=True)
        if data.startswith('status:'): return await show_page(update,context,status=data.split(':')[1])
        return await show_page(update,context,favourites=True)
    if data=='stats': return await stats(update,context)
    if data=='recommend': return await recommendation_view(update,context)
    if data=='random':
        row=await context.application.bot_data['db'].db.user_library.aggregate([{'$match':{'user_id':update.effective_user.id,'status':'PLAN_TO_WATCH'}},{'$sample':{'size':1}}]).to_list(length=1)
        return await q.edit_message_text('No Plan to Watch titles yet.' if not row else (await context.application.bot_data['db'].db.titles.find_one({'_id':row[0]['title_id']}))['title'])
    if data=='catstats':
        lines=[]
        for key,label in CATEGORY_LABELS.items(): lines.append(f"{label}: {await context.application.bot_data['db'].db.titles.count_documents({'categories':key})}")
        return await q.edit_message_text('\n'.join(lines))
    if data=='import:cancel':
        context.user_data.pop('pending_import',None)
        return await q.edit_message_text('Import cancelled.')
    if data=='import:confirm':
        rows=context.user_data.pop('pending_import',None)
        if rows is None: return await q.edit_message_text('Import preview expired. Send the file again.')
        report=await apply_import(context.application.bot_data['db'].db,update.effective_user.id,rows)
        return await q.edit_message_text('Import complete. '+'; '.join(f'{k}: {v}' for k,v in report.items()))
    return

async def text_search(update,context):
    if not await authorized(update,context): return
    if context.user_data.pop('await_search',False): return await show_page(update,context,query=update.effective_message.text)

async def stats(update,context):
    if not await authorized(update,context): return
    uid=update.effective_user.id; db=context.application.bot_data['db'].db
    rows=await db.user_library.find({'user_id':uid}).limit(5000).to_list(length=5000)
    counts={s.value:sum(1 for r in rows if r.get('status')==s.value) for s in Status}
    ids=[r['title_id'] for r in rows]; titles=await db.titles.find({'_id':{'$in':ids}}).to_list(length=5000) if ids else []
    formats={fmt:sum(1 for t in titles if t.get('format')==fmt) for fmt in ('movie','tv_series','OVA','ONA','special')}
    genre_counts={}
    for title in titles:
        for genre in title.get('genres',[]): genre_counts[genre]=genre_counts.get(genre,0)+1
    progress=await db.watch_progress.find({'user_id':uid}).to_list(length=5000)
    episodes=sum(int(p.get('completed_episodes',0)) for p in progress)
    runtime=sum((t.get('runtime_minutes') or 0) for t in titles if isinstance(t.get('runtime_minutes'),int))
    rating_counts={str(n):sum(1 for r in rows if r.get('rating')==n) for n in range(1,11)}
    months={}
    for row in rows:
        done=row.get('completed_at')
        if isinstance(done,datetime):
            key=done.strftime('%Y-%m'); months[key]=months.get(key,0)+1
    unfinished=[]
    for title in titles:
        if title.get('format')=='tv_series' and title.get('episode_count') and any(r['title_id']==title['_id'] and r.get('status')=='WATCHING' for r in rows):
            watched=next((p.get('completed_episodes',0) for p in progress if p['title_id']==title['_id']),0)
            unfinished.append((title.get('episode_count')-watched,title['title']))
    text=f"Your library: {len(rows)} unique titles\n"+'\n'.join(f"{s.value.replace('_',' ').title()}: {counts[s.value]}" for s in Status)
    text+='\n\nFormats: '+'; '.join(f'{k} {v}' for k,v in formats.items() if v)
    text+=f"\nEpisodes completed: {episodes}"
    if runtime: text+=f"\nKnown runtime in library: {runtime} minutes (series totals are not inferred)"
    if genre_counts: text+='\nTop genres: '+', '.join(f'{g} ({n})' for g,n in sorted(genre_counts.items(),key=lambda x:(-x[1],x[0]))[:5])
    rated={k:v for k,v in rating_counts.items() if v}
    if rated: text+='\nRatings: '+', '.join(f'{k}/10 ({v})' for k,v in rated.items())
    if months: text+='\nCompletions by month: '+', '.join(f'{m}: {n}' for m,n in sorted(months.items())[-6:])
    if unfinished: text+='\nLongest unfinished series: '+', '.join(name for _,name in sorted(unfinished,reverse=True)[:3])
    await (update.callback_query.edit_message_text(text) if update.callback_query else update.effective_message.reply_text(text))

async def recommendation_view(update,context,seed_id=None):
    if not await authorized(update,context): return
    recs=await CatalogService(context.application.bot_data['db'].db).recommendations(update.effective_user.id,seed_id)
    if not recs:
        text='Add a few favourites or rate titles 8–10 to get local genre and studio recommendations.'
        markup=None
    else:
        text='Personal recommendations (based on your library):\n\n'+'\n'.join(f"• {r['title']} — {r.get('recommendation_reason','similar genre')}" for r in recs)
        markup=InlineKeyboardMarkup([[InlineKeyboardButton(r['title'][:30],callback_data=f"d:{r['_id']}")] for r in recs])
    if update.callback_query: await update.callback_query.edit_message_text(text,reply_markup=markup)
    else: await update.effective_message.reply_text(text,reply_markup=markup)

async def recommend_cmd(update,context):
    return await recommendation_view(update,context)

async def similar_cmd(update,context):
    if not await authorized(update,context): return
    query=' '.join(context.args).strip()
    if not query: return await update.effective_message.reply_text('Use /similar <title>.')
    docs,_=await CatalogService(context.application.bot_data['db'].db).search(query,size=1)
    if not docs: return await update.effective_message.reply_text('Title not found in the catalog.')
    return await recommendation_view(update,context,docs[0]['_id'])

async def genres_cmd(update,context):
    if not await authorized(update,context): return
    genres=await context.application.bot_data['db'].db.titles.distinct('genres')
    genres=sorted(g for g in genres if isinstance(g,str))
    await update.effective_message.reply_text(('Catalog genres:\n'+'\n'.join(f'• {g}' for g in genres[:80])) if genres else 'Genre metadata is not available yet.')

async def continue_cmd(update,context):
    if not await authorized(update,context): return
    await show_page(update,context,status=Status.WATCHING.value)

async def recent_cmd(update,context):
    if not await authorized(update,context): return
    uid=update.effective_user.id; db=context.application.bot_data['db'].db
    rows=await db.user_library.find({'user_id':uid}).sort('updated_at',-1).limit(PAGE_SIZE).to_list(length=PAGE_SIZE)
    lines=[]
    for row in rows:
        title=await db.titles.find_one({'_id':row['title_id']})
        if title: lines.append(f"• {title['title']} — {row.get('status','unknown')}")
    await update.effective_message.reply_text('\n'.join(lines) if lines else 'No recent library activity.')

async def rewatch_cmd(update,context):
    if not await authorized(update,context): return
    query=' '.join(context.args).strip()
    if not query: return await update.effective_message.reply_text('Use /rewatch <title>.')
    db=context.application.bot_data['db'].db; uid=update.effective_user.id
    docs,_=await CatalogService(db).search(query,size=1)
    if not docs: return await update.effective_message.reply_text('Title not found in the catalog.')
    tid=docs[0]['_id']; await CatalogService(db).add_to_library(uid,tid)
    await db.user_library.update_one({'user_id':uid,'title_id':tid},{'$inc':{'rewatch_count':1},'$set':{'last_watched_at':now_utc(),'updated_at':now_utc()}})
    await db.watch_history.insert_one({'user_id':uid,'title_id':tid,'event':'rewatch_started','created_at':now_utc()})
    await update.effective_message.reply_text(f"Rewatch recorded for {docs[0]['title']}.")

async def history_cmd(update,context):
    if not await authorized(update,context): return
    db=context.application.bot_data['db'].db; uid=update.effective_user.id
    rows=await db.watch_history.find({'user_id':uid}).sort('created_at',-1).limit(PAGE_SIZE).to_list(length=PAGE_SIZE)
    lines=[]
    for row in rows:
        title=await db.titles.find_one({'_id':row['title_id']})
        if title: lines.append(f"• {row.get('created_at','')} — {title['title']} ({row.get('event','activity')})")
    await update.effective_message.reply_text('\n'.join(lines) if lines else 'No watch history yet.')

async def admin(update,context,command):
    if not await authorized(update,context,owner=True): return
    log.info('Owner administrative action: %s', command)
    cfg=context.application.bot_data['settings']; db=context.application.bot_data['db'].db; service=CatalogService(db)
    if command=='seed_catalog':
        dry='--execute' not in context.args
        rep=await service.seed(entries(),dry_run=dry)
        await update.effective_message.reply_text(('DRY RUN — no database changes.\n' if dry else 'Seed complete.\n')+'\n'.join(f'{k}: {v}' for k,v in rep.items())+('\nUse /seed_catalog --execute to write.' if dry else ''))
    elif command=='catalog_stats':
        lines=[f"Titles: {await db.titles.count_documents({})}"]
        for key,label in CATEGORY_LABELS.items(): lines.append(f'{label}: {await db.titles.count_documents({"categories":key})}')
        await update.effective_message.reply_text('\n'.join(lines))
    elif command=='enrich_catalog':
        updated,failed=await MetadataEnricher(db).enrich_incomplete(); await update.effective_message.reply_text(f'Metadata enrichment finished. Updated {updated}; failed {failed}.')
    elif command=='catalog_incomplete':
        rows=await db.titles.find({'metadata_status':'incomplete'},{'title':1}).limit(20).to_list(length=20); await update.effective_message.reply_text('Incomplete catalog entries:\n'+'\n'.join(x['title'] for x in rows) if rows else 'No incomplete entries.')
    elif command=='add_recommendations_to_library':
        total=await db.titles.count_documents({}); existing=await db.user_library.count_documents({'user_id':cfg.owner_id})
        await update.effective_message.reply_text(f'Preview: catalog has {total}; your library has {existing}. Confirm to add only missing titles as Plan to Watch.',reply_markup=keyboard([[('Confirm','bulk:confirm'),('Cancel','catalog')]]))
    elif command=='health':
        try: await context.application.bot_data['db'].ping(); await update.effective_message.reply_text('MongoDB: healthy; bot process: healthy.')
        except Exception: await update.effective_message.reply_text('MongoDB: unavailable.')
    elif command=='allow':
        if not context.args or not context.args[0].isdecimal(): return await update.effective_message.reply_text('Use /allow <numeric Telegram ID>')
        uid=int(context.args[0]); role=context.args[1].upper() if len(context.args)>1 else 'USER'
        if uid==cfg.owner_id: return await update.effective_message.reply_text('The configured owner always retains the OWNER role.')
        if role not in ('USER','ADMIN'): return await update.effective_message.reply_text('Role must be USER or ADMIN.')
        await db.authorized_users.update_one({'user_id':uid},{'$set':{'user_id':uid,'role':role,'active':True,'updated_at':now_utc()}},upsert=True); await update.effective_message.reply_text(f'Authorized {uid} as {role}.')
    elif command=='revoke':
        if not context.args or not context.args[0].isdecimal() or int(context.args[0])==cfg.owner_id: return await update.effective_message.reply_text('Use /revoke <non-owner numeric Telegram ID>.')
        await db.authorized_users.update_one({'user_id':int(context.args[0])},{'$set':{'active':False}}); await update.effective_message.reply_text('Access revoked.')
    elif command=='users':
        rows=await db.authorized_users.find({'active':True}).to_list(length=100); await update.effective_message.reply_text('\n'.join(f"{r['user_id']}: {r['role']}" for r in rows) or 'No additional users.')
    elif command=='role':
        if not context.args or not context.args[0].isdecimal(): return await update.effective_message.reply_text('Use /role <numeric Telegram ID>')
        row=await db.authorized_users.find_one({'user_id':int(context.args[0])}); await update.effective_message.reply_text(f"{row['role']}" if row else 'No approved user record.')
    elif command=='backup':
        await update.effective_message.reply_text('Use the documented mongodump command on a private host. Telegram file exports are intentionally not used for whole-database backups.')
    elif command=='adminstats': await update.effective_message.reply_text(f"Shared catalog: {await db.titles.count_documents({})}; user library entries: {await db.user_library.count_documents({})}")

async def command_search(update,context):
    return await search(update,context)
async def watch(update,context):
    if not await authorized(update,context): return
    if len(context.args)<2: return await update.effective_message.reply_text('Use /progress <title> <watched episodes>.')
    count=context.args[-1]
    if not count.isdecimal(): return await update.effective_message.reply_text('Episode count must be a non-negative integer.')
    q=' '.join(context.args[:-1]); docs,_=await CatalogService(context.application.bot_data['db'].db).search(q,size=1)
    if not docs: return await update.effective_message.reply_text('Title not found in the catalog.')
    title=docs[0]; value=int(count); total=title.get('episode_count')
    if total and value>total: return await update.effective_message.reply_text('Progress cannot exceed the known episode total.')
    from .services import progress_percent
    pct=progress_percent(value,total)
    await context.application.bot_data['db'].db.watch_progress.update_one({'user_id':update.effective_user.id,'title_id':title['_id']},{'$set':{'user_id':update.effective_user.id,'title_id':title['_id'],'completed_episodes':value,'total_episodes':total,'updated_at':now_utc()}},upsert=True)
    await update.effective_message.reply_text(f"{title['title']}: {value} episode(s)"+(f' ({pct}%)' if pct is not None else ' (total unknown)'))

async def ratings(update,context,kind):
    if not await authorized(update,context): return
    if len(context.args)<2: return await update.effective_message.reply_text(f'Use /{kind} <title> <value>.')
    value=context.args[-1]; query=' '.join(context.args[:-1]); db=context.application.bot_data['db'].db
    docs,_=await CatalogService(db).search(query,size=1)
    if not docs: return await update.effective_message.reply_text('Title not found.')
    field='rating' if kind=='rate' else 'notes'
    if kind=='rate':
        if not value.isdecimal() or not 1<=int(value)<=10: return await update.effective_message.reply_text('Rating must be 1–10.')
        value=int(value)
    await CatalogService(db).add_to_library(update.effective_user.id,docs[0]['_id'])
    await db.user_library.update_one({'user_id':update.effective_user.id,'title_id':docs[0]['_id']},{'$set':{field:value,'updated_at':now_utc()}})
    await update.effective_message.reply_text('Saved.')

async def export_cmd(update,context):
    if not await authorized(update,context): return
    from telegram import InputFile
    rows=await context.application.bot_data['db'].db.user_library.find({'user_id':update.effective_user.id}).to_list(length=10000)
    for row in rows: row['_id']=str(row['_id'])
    payload=json.dumps({'schema_version':1,'user_id':update.effective_user.id,'library':rows},default=str,indent=2).encode()
    await update.effective_message.reply_document(InputFile(payload,filename='anime-vault-library.json'),caption='Your private library export.')

async def reminders(update,context):
    if not await authorized(update,context): return
    mode=context.args[0].lower() if context.args else 'status'
    if mode not in ('daily','weekly','off','status'): return await update.effective_message.reply_text('Use /reminders daily, /reminders weekly, /reminders off, or /reminders.')
    db=context.application.bot_data['db'].db; uid=update.effective_user.id
    if mode!='status': await db.user_settings.update_one({'user_id':uid},{'$set':{'reminder_preference':mode,'updated_at':now_utc()}},upsert=True)
    saved=await db.user_settings.find_one({'user_id':uid}) or {}
    await update.effective_message.reply_text(f"Reminder preference: {saved.get('reminder_preference','off')}. Preference is stored; scheduled delivery is not enabled in this build.")

async def import_cmd(update,context):
    if not await authorized(update,context): return
    await update.effective_message.reply_text('Attach your Anime Vault JSON export in this chat. I will preview it and ask for confirmation before importing.')

async def receive_import(update,context):
    if not await authorized(update,context): return
    document=update.effective_message.document
    if not document or not (document.file_name or '').lower().endswith('.json'):
        return await update.effective_message.reply_text('Please attach a .json Anime Vault export.')
    if document.file_size and document.file_size>5_000_000:
        return await update.effective_message.reply_text('Export exceeds the 5 MB size limit.')
    try:
        remote=await document.get_file(); raw=await remote.download_as_bytearray()
        rows=parse_export(bytes(raw),update.effective_user.id)
        report=await preview_import(context.application.bot_data['db'].db,update.effective_user.id,rows)
        context.user_data['pending_import']=rows
    except ValueError as exc:
        return await update.effective_message.reply_text(f'Import rejected: {exc}')
    except Exception:
        log.exception('Library import preview failed')
        return await update.effective_message.reply_text('Could not read that file. Check that it is a valid Anime Vault export.')
    await update.effective_message.reply_text('Import preview (existing records will not be overwritten):\n'+'\n'.join(f'{k}: {v}' for k,v in report.items()),reply_markup=keyboard([[('Confirm import','import:confirm'),('Cancel','import:cancel')]]))

async def cancel(update,context):
    if not await authorized(update,context): return
    context.user_data.clear()
    await update.effective_message.reply_text('Cancelled.')

async def where(update,context):
    if not await authorized(update,context): return
    q=' '.join(context.args)
    if q:
        await update.effective_message.reply_text('Availability not verified: no licensed streaming availability provider is configured. Check the streaming service directly using its official catalog search.')
    else: await update.effective_message.reply_text('Use /where_to_watch <title>. Availability requires a configured authorized provider.')

async def create_list(update,context):
    if not await authorized(update,context): return
    name=' '.join(context.args).strip()
    if not name or len(name)>80: return await update.effective_message.reply_text('Use /create_list <name> (1–80 characters).')
    try: await context.application.bot_data['db'].db.custom_lists.insert_one({'user_id':update.effective_user.id,'name':name,'title_ids':[],'created_at':now_utc()})
    except Exception: return await update.effective_message.reply_text('A list with that name already exists.')
    await update.effective_message.reply_text(f'List created: {name}')

async def lists(update,context):
    if not await authorized(update,context): return
    rows=await context.application.bot_data['db'].db.custom_lists.find({'user_id':update.effective_user.id}).to_list(length=100)
    markup=InlineKeyboardMarkup([[InlineKeyboardButton(r['name'][:30],callback_data=f"lv:{r['_id']}")] for r in rows]) if rows else None
    await update.effective_message.reply_text('\n'.join(r['name'] for r in rows) or 'No custom lists. Use /create_list <name>.',reply_markup=markup)

async def rename_list(update,context):
    if not await authorized(update,context): return
    raw=' '.join(context.args)
    if '|' not in raw: return await update.effective_message.reply_text('Use /rename_list old name | new name')
    old,new=(part.strip() for part in raw.split('|',1))
    if not old or not new or len(new)>80: return await update.effective_message.reply_text('Both names are required; the new name must be at most 80 characters.')
    db=context.application.bot_data['db'].db
    try: result=await db.custom_lists.update_one({'user_id':update.effective_user.id,'name':old},{'$set':{'name':new,'updated_at':now_utc()}})
    except Exception: return await update.effective_message.reply_text('A list with that name already exists.')
    await update.effective_message.reply_text('List renamed.' if result.modified_count else 'List not found or name unchanged.')

async def delete_list(update,context):
    if not await authorized(update,context): return
    name=' '.join(context.args).strip()
    if not name: return await update.effective_message.reply_text('Use /delete_list <name>.')
    row=await context.application.bot_data['db'].db.custom_lists.find_one({'user_id':update.effective_user.id,'name':name})
    if not row: return await update.effective_message.reply_text('List not found.')
    await update.effective_message.reply_text(f"Delete ‘{name}’? Anime and personal library entries will remain.",reply_markup=keyboard([[('Confirm delete',f"ldc:{row['_id']}"),('Cancel','lists')]]))

async def move_list_item(update,context):
    if not await authorized(update,context): return
    raw=' '.join(context.args)
    parts=[part.strip() for part in raw.split('|')]
    if len(parts)!=3 or not parts[2].isdecimal(): return await update.effective_message.reply_text('Use /move_list_item list name | title | position (1-based).')
    db=context.application.bot_data['db'].db; uid=update.effective_user.id
    row=await db.custom_lists.find_one({'user_id':uid,'name':parts[0]})
    if not row: return await update.effective_message.reply_text('List not found.')
    matches,_=await CatalogService(db).search(parts[1],size=1)
    if not matches: return await update.effective_message.reply_text('Title not found in catalog.')
    ids=list(row.get('title_ids',[])); tid=matches[0]['_id']
    if tid in ids: ids.remove(tid)
    position=int(parts[2])
    if position<1 or position>len(ids)+1: return await update.effective_message.reply_text(f'Position must be from 1 to {len(ids)+1}.')
    ids.insert(position-1,tid)
    await db.custom_lists.update_one({'_id':row['_id'],'user_id':uid},{'$set':{'title_ids':ids,'updated_at':now_utc()}})
    await update.effective_message.reply_text('List order updated.')

def build_application(settings, database):
    app=Application.builder().token(settings.bot_token).build(); app.bot_data.update(settings=settings,db=database)
    commands={'start':start,'help':help_command,'menu':menu,'settings':settings_cmd,'search':command_search,'add':add,'library':library,
      'watchlist':watchlist,'watching':watching,'watched':watched,'onhold':onhold,'dropped':dropped,'favourites':favs,'stats':stats,
      'recommend':recommend_cmd,'similar':similar_cmd,'genres':genres_cmd,'continue':continue_cmd,'recent':recent_cmd,
      'rewatch':rewatch_cmd,'history':history_cmd,
      'progress':watch,'rate':lambda u,c:ratings(u,c,'rate'),'review':lambda u,c:ratings(u,c,'review'),'export':export_cmd,'import':import_cmd,
      'reminders':reminders,'where_to_watch':where,'create_list':create_list,'lists':lists,'cancel':cancel,
      'rename_list':rename_list,'delete_list':delete_list,'move_list_item':move_list_item,
      'seed_catalog':lambda u,c:admin(u,c,'seed_catalog'),'catalog_stats':lambda u,c:admin(u,c,'catalog_stats'),
      'enrich_catalog':lambda u,c:admin(u,c,'enrich_catalog'),'catalog_incomplete':lambda u,c:admin(u,c,'catalog_incomplete'),
      'add_recommendations_to_library':lambda u,c:admin(u,c,'add_recommendations_to_library'),'health':lambda u,c:admin(u,c,'health'),
      'allow':lambda u,c:admin(u,c,'allow'),'revoke':lambda u,c:admin(u,c,'revoke'),'users':lambda u,c:admin(u,c,'users'),'role':lambda u,c:admin(u,c,'role'),'backup':lambda u,c:admin(u,c,'backup'),'adminstats':lambda u,c:admin(u,c,'adminstats'),'setregion':setregion}
    for name,handler in commands.items(): app.add_handler(CommandHandler(name,handler))
    app.add_handler(CallbackQueryHandler(callback)); app.add_handler(MessageHandler(filters.Document.ALL,receive_import)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_search))
    async def error_handler(update,context):
        log.error('Unhandled bot error',exc_info=context.error)
        if update and update.effective_message:
            try: await update.effective_message.reply_text('Sorry, the request failed. Please try again later.')
            except Exception: pass
    app.add_error_handler(error_handler)
    return app
