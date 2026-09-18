"""Durable, evidence-backed presence work queue. External actions belong to the native browser driver.

SQLite transactions coordinate independent MCP clients. Unknown publish outcomes
reserve their duplicate key permanently until reconciled; retries never send blind.
"""
import datetime as dt
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = Path.home() / '.blacklabel/presence'


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(value).hexdigest()


def clean_text(value):
    if re.search(r'(?i)\b(?:password|access_token|refresh_token|api_key|authorization)\s*[:=]\s*\S+', value):
        raise ValueError('Do not store credentials in campaign records')
    if re.search(r'https?://\S+[?&](?:code|token|access_token|signature|sig)=', value, re.I):
        raise ValueError('Do not store signed links or authentication callback codes')
    return value


def public_url(value):
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('Expected a public http(s) URL without credentials')
    clean_text(value)
    return value


def norm(value):
    return re.sub(r'\W+', ' ', value.casefold()).strip()


class Presence:
    def __init__(self, state=None, registry=None):
        self.state = Path(state or os.environ.get('BL_PRESENCE_STATE', DEFAULT_STATE))
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.state, 0o700)
        self.platforms = json.loads(Path(registry or os.environ.get('BL_PRESENCE_REGISTRY') or ROOT / 'platforms.json').read_text())['platforms']
        self.by_id = {p['id']: p for p in self.platforms}
        self.db = sqlite3.connect(self.state / 'presence.sqlite3', timeout=10)
        self.db.row_factory = sqlite3.Row
        os.chmod(self.state / 'presence.sqlite3', 0o600)
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL, request TEXT NOT NULL,
          mode TEXT NOT NULL, corrections TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),site TEXT NOT NULL,
          ordinal INTEGER NOT NULL,instruction TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
          lease TEXT,lease_until REAL,detail TEXT,receipt TEXT,updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS accounts(site TEXT NOT NULL,identity TEXT NOT NULL,profile_url TEXT NOT NULL,
          browser TEXT NOT NULL,status TEXT NOT NULL,evidence TEXT NOT NULL,verified REAL NOT NULL,
          PRIMARY KEY(site,identity));
        CREATE TABLE IF NOT EXISTS content(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),site TEXT NOT NULL,
          identity TEXT NOT NULL,body TEXT NOT NULL,angle TEXT NOT NULL,sources TEXT NOT NULL,media TEXT NOT NULL,
          hash TEXT NOT NULL,review TEXT,status TEXT NOT NULL DEFAULT 'draft',created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS publications(id TEXT PRIMARY KEY,content_id TEXT UNIQUE NOT NULL REFERENCES content(id),
          duplicate_key TEXT UNIQUE NOT NULL,status TEXT NOT NULL,url TEXT,receipt TEXT,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,event TEXT NOT NULL,
          payload TEXT NOT NULL,created REAL NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def event(self, run, event, payload):
        self.db.execute('INSERT INTO events(run_id,event,payload,created) VALUES(?,?,?,?)', (run, event, json.dumps(payload), time.time()))

    def row(self, table, ident):
        assert table in ('runs', 'tasks', 'content', 'publications')
        row = self.db.execute('SELECT * FROM ' + table + ' WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('Unknown ' + table + ' ID')
        return dict(row)

    def catalog(self, site=None):
        if site:
            if site not in self.by_id:
                raise ValueError('Unknown platform; use presence_catalog')
            return self.by_id[site]
        return {'sites': [{k: p[k] for k in ('id','name','category','disposition','home_url')} for p in self.platforms],
                'counts': {s: sum(p['disposition'] == s for p in self.platforms) for s in ('active','held','excluded','conditional')},
                'historical_account_candidates_are_not_verified_sessions': True}

    def run(self, task_id, request, mode='execute', sites=None):
        clean_text(request)
        if not request.strip() or mode not in ('execute','draft','audit'):
            raise ValueError('A user request and valid mode are required')
        old = self.db.execute('SELECT id FROM runs WHERE task_id=?', (task_id,)).fetchone()
        if old:
            return self.status(old['id'])
        selected = sites or [p['id'] for p in self.platforms if p['disposition'] == 'active']
        selected = list(dict.fromkeys(selected))
        for site in selected:
            p = self.catalog(site)
            if p['disposition'] != 'active':
                raise ValueError(site + ' is ' + p['disposition'] + ' in the supplied scope')
        run = str(uuid.uuid4())
        with self.db:
            self.db.execute('INSERT INTO runs(id,task_id,request,mode,created) VALUES(?,?,?,?,?)', (run,task_id,request,mode,time.time()))
            for site in selected:
                p = self.by_id[site]
                if mode == 'audit':
                    requirements = ['Inspect current owner identity, sign-in state, existing profile, and unmet requirements; do not mutate external state.']
                elif mode == 'draft':
                    requirements = ['Prepare distinct evidence-based copy and matching real media for this site; do not publish or change profile.']
                else:
                    requirements = ['Verify existing owner identity and session; use native browser sign-in/recovery without creating a duplicate.']
                    requirements += [re.sub(r'^(?:- |\d+\. )', '', l) for l in p['requirements'].splitlines() if re.match(r'^(?:- |\d+\. )',l)]
                    requirements += ['Reconcile every requirement, profile URL, native post/listing URL, and readback receipt for this site.']
                for ordinal, instruction in enumerate(requirements):
                    self.db.execute('INSERT INTO tasks(id,run_id,site,ordinal,instruction,updated) VALUES(?,?,?,?,?,?)',
                                    (str(uuid.uuid4()),run,site,ordinal,instruction,time.time()))
            self.event(run, 'started', {'request':request,'mode':mode,'sites':selected})
        return self.status(run)

    def amend(self, run_id, correction):
        clean_text(correction)
        with self.db:
            run = self.row('runs',run_id)
            corrections = json.loads(run['corrections']) + [correction]
            self.db.execute('UPDATE runs SET corrections=? WHERE id=?',(json.dumps(corrections),run_id))
            self.event(run_id,'correction',{'text':correction})
        return self.status(run_id)

    def status(self, run_id=None):
        if run_id is None:
            return {'runs': [dict(r) for r in self.db.execute('SELECT id,task_id,mode,created FROM runs ORDER BY created DESC LIMIT 30')]}
        run = self.row('runs',run_id)
        tasks = [dict(r) for r in self.db.execute('SELECT * FROM tasks WHERE run_id=? ORDER BY site,ordinal',(run_id,))]
        counts = {s:sum(t['status']==s for t in tasks) for s in ('pending','leased','verified','needs_user','waiting_provider','uncertain')}
        pubs = [dict(r) for r in self.db.execute('SELECT p.id,c.site,c.identity,p.status,p.url FROM publications p JOIN content c ON p.content_id=c.id WHERE c.run_id=?',(run_id,))]
        return {'run':{**run,'corrections':json.loads(run['corrections'])},'counts':counts,'total_requirements':len(tasks),
                'complete':bool(tasks) and all(t['status']=='verified' for t in tasks),
                'remaining':[t for t in tasks if t['status']!='verified'], 'publications':pubs,
                'execution':'Native browser tools perform external actions; these records track observations, not independent provider attestations.'}

    def next(self, run_id):
        run = self.row('runs',run_id)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            # Expired actions are uncertain. Never assume a dead client did not publish.
            self.db.execute("UPDATE tasks SET status='uncertain',detail='Lease expired; inspect destination before retrying',lease=NULL WHERE status='leased' AND lease_until<?",(time.time(),))
            rows = self.db.execute("SELECT * FROM tasks WHERE run_id=? AND status='pending' ORDER BY ordinal,site",(run_id,)).fetchall()
            rows = sorted(rows, key=lambda row:(self.by_id[row['site']].get('priority',99),row['ordinal']))
            chosen = None
            for row in rows:
                site = row['site']
                busy = self.db.execute("SELECT 1 FROM tasks WHERE site=? AND status IN ('leased','uncertain') LIMIT 1",(site,)).fetchone()
                waiting = self.db.execute("SELECT 1 FROM tasks WHERE run_id=? AND site=? AND status IN ('needs_user','waiting_provider','uncertain') LIMIT 1",(run_id,site)).fetchone()
                if not busy and not waiting:
                    chosen = dict(row); break
            if chosen:
                lease = str(uuid.uuid4())
                self.db.execute("UPDATE tasks SET status='leased',lease=?,lease_until=?,updated=? WHERE id=?",(lease,time.time()+900,time.time(),chosen['id']))
                self.event(run_id,'leased',{'task_id':chosen['id'],'site':chosen['site']})
                chosen.update(status='leased',lease=lease)
            self.db.commit()
        except BaseException:
            self.db.rollback(); raise
        if not chosen:
            return {'next':None,'status':self.status(run_id),'instruction':'Reconcile uncertain outcomes and check waiting dependencies. Do not claim complete unless all requirements have verified evidence.'}
        return {'next':chosen,'platform':self.catalog(chosen['site']),'original_request':run['request'],'corrections':json.loads(run['corrections']),
                'driver':'black-label-browser MCP; use existing real Safari/Chrome sessions and native saved sign-in',
                'instruction':'Perform this requirement, record the actual result with presence_record, then call presence_next until complete. Inspect quality and attached media before posting.'}

    def record(self, task_id, lease, outcome, detail, evidence_url=None, readback=None):
        clean_text(detail); clean_text(readback or '')
        if outcome not in ('verified','needs_user','waiting_provider','uncertain','retry'):
            raise ValueError('Unsupported outcome')
        task = self.row('tasks',task_id)
        if task['status'] != 'leased' or task['lease'] != lease or task['lease_until'] < time.time():
            raise ValueError('Stale task lease; reconcile before recording')
        if outcome == 'verified' and (not evidence_url or not readback):
            raise ValueError('Verified work requires an evidence URL and observed readback')
        if evidence_url:
            public_url(evidence_url)
        receipt = {'source':'agent_browser_observation','url':evidence_url,'readback':readback,'at':time.time()}
        with self.db:
            self.db.execute('UPDATE tasks SET status=?,detail=?,receipt=?,lease=NULL,lease_until=NULL,updated=? WHERE id=?',
                            ('pending' if outcome=='retry' else outcome,detail,json.dumps(receipt),time.time(),task_id))
            self.event(task['run_id'],'task_result',{'task_id':task_id,'outcome':outcome,'detail':detail,'receipt':receipt})
        return {'recorded':True,'outcome':outcome,'next':'presence_next'}

    def resume_site(self, run_id, site, evidence):
        clean_text(evidence); self.row('runs',run_id); self.catalog(site)
        if not evidence.strip():
            raise ValueError('Provide the observed recovery or reconciliation evidence')
        with self.db:
            self.db.execute("UPDATE tasks SET status='pending',detail=?,updated=? WHERE run_id=? AND site=? AND status IN ('needs_user','waiting_provider','uncertain')",(evidence,time.time(),run_id,site))
            self.event(run_id,'resumed_site',{'site':site,'evidence':evidence})
        return self.status(run_id)

    def account(self, site, identity, profile_url, browser, status, evidence):
        self.catalog(site); public_url(profile_url); clean_text(evidence); clean_text(identity)
        if not identity.strip() or not evidence.strip():
            raise ValueError('Actual observed account identity and evidence are required')
        if status not in ('signed_in','needs_login','needs_verification') or browser not in ('safari','chrome'):
            raise ValueError('Invalid account observation')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO accounts VALUES(?,?,?,?,?,?,?)',(site,identity,profile_url,browser,status,evidence,time.time()))
        return {'recorded':True,'identity':identity,'source':'agent_browser_observation'}

    def connections(self):
        return {'accounts':[dict(r) for r in self.db.execute('SELECT * FROM accounts ORDER BY site,identity')],
                'note':'Saved observations are dated, not proof of a current authenticated session. Refresh before any publish.'}

    def quality(self, body, angle, sources, media, site, identity, exclude=None):
        problems = []
        if len(body.strip()) < 30 or len(angle.strip()) < 15:
            problems.append('Write a specific useful point and explain the distinct angle')
        if not sources or any(not x.get('claim') or not x.get('url') for x in sources):
            problems.append('Ground factual claims in explicit source URLs')
        for source in sources:
            if source.get('url'):
                public_url(source['url'])
        banned = r'(?i)revolutioniz|game.chang|unlock the power|in today.s fast.paced|seamless(ly)?|cutting.edge|delve into|leverage the power'
        if re.search(banned,body):
            problems.append('Rewrite generic AI marketing filler into concrete product facts')
        if len(re.findall(r'(?<!\w)#\w+',body)) > 5:
            problems.append('Remove hashtag stuffing')
        if re.search(r'(?i)\b(lorem ipsum|insert (?:text|link)|TODO|placeholder)\b',body):
            problems.append('Remove placeholders')
        if not media and site in ('facebook','instagram','threads','youtube','tiktok','pinterest','snapchat','linkedin','x'):
            problems.append('Attach matching real product/campaign media for this promotional post')
        for other in self.db.execute('SELECT id,body FROM content WHERE site=? AND identity=?',(site,identity)):
            if other['id'] != exclude and difflib.SequenceMatcher(None,norm(body),norm(other['body'])).ratio() >= .88:
                problems.append('Near-duplicate of existing content '+other['id']); break
        return problems

    def stage(self, run_id, site, identity, body, angle, sources, media_paths):
        run = self.row('runs',run_id); self.catalog(site)
        if not self.db.execute('SELECT 1 FROM tasks WHERE run_id=? AND site=?',(run_id,site)).fetchone():
            raise ValueError('Site is outside this run')
        if run['mode']=='audit':
            raise ValueError('Audit-only run cannot stage publication content')
        clean_text(body); clean_text(angle); clean_text(identity)
        for source in sources:
            clean_text(source.get('claim', ''))
        media = []
        for raw in media_paths:
            path = Path(raw).expanduser().resolve()
            if not path.is_file() or path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.mp4','.mov','.gif'):
                raise ValueError('Media must be an existing image/video file')
            if path.stat().st_size > 1024**3:
                raise ValueError('Media exceeds 1GB; export a platform-appropriate asset')
            hasher = hashlib.sha256()
            with path.open('rb') as f:
                for chunk in iter(lambda:f.read(1024*1024),b''): hasher.update(chunk)
            media.append({'path':str(path),'sha256':hasher.hexdigest(),'bytes':path.stat().st_size})
        problems = self.quality(body,angle,sources,media,site,identity)
        if problems:
            return {'staged':False,'rewrite_required':problems,'action':'Revise content and media without asking for repeated permission'}
        content_hash = digest({'site':site,'identity':identity,'body':body,'media':[m['sha256'] for m in media]})
        ident = str(uuid.uuid4())
        with self.db:
            self.db.execute('INSERT INTO content(id,run_id,site,identity,body,angle,sources,media,hash,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (ident,run_id,site,identity,body,angle,json.dumps(sources),json.dumps(media),content_hash,time.time()))
            self.event(run_id,'content_staged',{'content_id':ident,'hash':content_hash})
        return {'staged':True,'content_id':ident,'hash':content_hash,'next':'Inspect rendered media and current source claims, then presence_review. This lint is not a visual or factual review.'}

    def review(self, content_id, content_hash, factual_evidence, visual_evidence, distinct_reason):
        row = self.row('content',content_id)
        if row['hash'] != content_hash or row['status'] != 'draft':
            raise ValueError('Review must bind to the unchanged draft hash')
        for value in (factual_evidence,visual_evidence,distinct_reason):
            clean_text(value)
            if len(value.strip())<20:
                raise ValueError('Record concrete factual, visual and distinctness review evidence')
        review = {'hash':content_hash,'facts':factual_evidence,'visual':visual_evidence,'distinct':distinct_reason,'at':time.time(),'source':'agent_inspection'}
        with self.db:
            self.db.execute("UPDATE content SET review=?,status='reviewed' WHERE id=?",(json.dumps(review),content_id))
            self.event(row['run_id'],'content_reviewed',{'content_id':content_id,'hash':content_hash})
        return {'reviewed':True,'next':'presence_prepare_publish'}

    def prepare(self, content_id):
        row = self.row('content',content_id); run = self.row('runs',row['run_id'])
        if run['mode'] != 'execute':
            raise ValueError('Draft/audit run has no publication authority')
        if row['status'] != 'reviewed':
            raise ValueError('Inspect facts and actual media before preparing publication')
        account = self.db.execute('SELECT * FROM accounts WHERE site=? AND identity=?',(row['site'],row['identity'])).fetchone()
        if not account or account['status']!='signed_in' or time.time()-account['verified']>1800:
            raise ValueError('Refresh the exact destination identity in the native browser, then presence_account')
        media = json.loads(row['media'])
        for m in media:
            path = Path(m['path'])
            if not path.is_file() or digest(path.read_bytes()) != m['sha256']:
                raise ValueError('Media changed after review; restage and inspect the new asset')
        key = digest({'site':row['site'],'identity':row['identity'],'body':norm(row['body']),'media':[m['sha256'] for m in media]})
        with self.db:
            existing = self.db.execute('SELECT * FROM publications WHERE duplicate_key=?',(key,)).fetchone()
            if existing:
                return {'publish':False,'existing':dict(existing),'action':'Reconcile existing outcome; do not submit again'}
            ident = str(uuid.uuid4())
            self.db.execute('INSERT INTO publications(id,content_id,duplicate_key,status,created) VALUES(?,?,?,?,?)',(ident,content_id,key,'prepared',time.time()))
            self.event(row['run_id'],'publish_prepared',{'publication_id':ident,'content_id':content_id})
        return {'publish':True,'publication_id':ident,'destination':dict(account),'body':row['body'],'media':media,
                'driver':'Use native browser to attach this exact media, inspect composer, submit once and read back the live result. Then presence_publication_result. This tool has not posted anything.'}

    def publication_result(self, publication_id, outcome, observed_identity, readback, media_verified=False, url=None):
        pub=self.row('publications',publication_id); content=self.row('content',pub['content_id'])
        clean_text(readback); clean_text(observed_identity)
        if url:
            public_url(url)
        if outcome not in ('verified','scheduled','uncertain','not_submitted'):
            raise ValueError('Unsupported publication outcome')
        if pub['status']=='verified':
            return {'unchanged':True,'receipt':json.loads(pub['receipt'])}
        if outcome=='verified':
            if not url or observed_identity!=content['identity'] or not media_verified and json.loads(content['media']):
                raise ValueError('Verify exact identity, actual media, and public permalink')
            public_url(url)
            if norm(content['body']) not in norm(readback):
                raise ValueError('Readback does not contain the final post text')
            expected=urlsplit(self.db.execute('SELECT profile_url FROM accounts WHERE site=? AND identity=?',(content['site'],content['identity'])).fetchone()[0]).hostname
            host=urlsplit(url).hostname
            if expected and host and expected.removeprefix('www.') != host.removeprefix('www.'):
                raise ValueError('Receipt URL does not match the destination host')
        receipt={'outcome':outcome,'identity':observed_identity,'readback':readback,'media_verified':media_verified,'url':url,'at':time.time(),'source':'agent_browser_observation'}
        with self.db:
            self.db.execute('UPDATE publications SET status=?,url=?,receipt=? WHERE id=?',(outcome,url,json.dumps(receipt),publication_id))
            self.event(content['run_id'],'publication_result',{'publication_id':publication_id,**receipt})
        return {'recorded':True,'receipt':receipt,'retry_policy':'Unknown outcomes keep their duplicate reservation. Reconcile before any new submission.'}

    def export(self, run_id):
        value=self.status(run_id)
        path=self.state/('run-'+run_id+'.json')
        tmp=path.with_suffix('.tmp')
        fd=os.open(tmp,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2)
        os.replace(tmp,path)
        return {'path':str(path),'sha256':digest(path.read_bytes()),'complete':value['complete']}
