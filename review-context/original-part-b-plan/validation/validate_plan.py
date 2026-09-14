"""Offline validation of this plan package, not the Betting-helper runtime."""
from __future__ import annotations
import ast
import copy
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urldefrag

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
checks: list[dict[str, object]] = []

def ok(name: str, detail: object) -> None:
    checks.append({'check': name, 'status': 'PASS', 'detail': detail})

def expect_schema_rejection(validator: Draft202012Validator, value: object) -> None:
    try:
        validator.validate(value)
    except ValidationError:
        return
    raise AssertionError('negative schema mutation accepted')

def expect_sql_rejection(db: sqlite3.Connection, sql: str, args: tuple = ()) -> None:
    try:
        db.execute(sql, args)
    except sqlite3.DatabaseError:
        return
    raise AssertionError(f'negative SQL operation accepted: {sql}')

def main() -> int:
    objects = {}
    for p in ROOT.rglob('*.json'):
        if p.name in {'validation-result.json', 'MANIFEST_SHA256.json'}:
            continue
        objects[p.relative_to(ROOT).as_posix()] = json.loads(p.read_text())
    ok('JSON_PARSE', len(objects))
    schemas = {k:v for k,v in objects.items() if k.endswith('.schema.json')}
    registry = Registry()
    for key,schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema['$id'], Resource.from_contents(schema))
    ok('SCHEMA_META_VALIDATION',len(schemas))
    ids = {schema['$id']:schema for schema in schemas.values()}
    ref_count = 0
    def visit(value, current):
        nonlocal ref_count
        if isinstance(value, dict):
            if '$ref' in value:
                ref_count += 1
                base, frag = urldefrag(value['$ref'])
                obj = current if not base else ids[base]
                if frag:
                    if not frag.startswith('/'):
                        raise AssertionError('unregistered anchor')
                    for part in frag[1:].split('/'):
                        obj = obj[unquote(part).replace('~1','/').replace('~0','~')]
            for child in value.values(): visit(child,current)
        elif isinstance(value,list):
            for child in value: visit(child,current)
    for schema in schemas.values(): visit(schema,schema)
    ok('LOCAL_SCHEMA_REFERENCE_RESOLUTION',ref_count)
    v=Draft202012Validator(objects['assets/contracts/live_readonly/v1/config.schema.json'],registry=registry,format_checker=FormatChecker())
    example=objects['assets/config/live-batched.example.json'];v.validate(example)
    neg=[]
    def mutate(path,value):
        x=copy.deepcopy(example);cursor=x
        for key in path[:-1]:cursor=cursor[key]
        cursor[path[-1]]=value;neg.append(x)
    mutate(['money_enabled'],True)
    mutate(['model_enabled'],True)
    mutate(['provider','base_url'],'https://not-provider.invalid')
    mutate(['provider','api_key'],'TEST_ONLY_FAKE_VALUE')
    mutate(['provider','fixture_ids'],list(range(1,22)))
    mutate(['runtime','host'],'0.0.0.0')
    mutate(['enabled'],True)
    mutate(['provider','live_poll_seconds'],1)
    mutate(['provider','fixture_ids'],[True])
    for x in neg:expect_schema_rejection(v,x)
    ok('CONFIG_EXAMPLE_AND_NEGATIVE_CASES',{'positive':1,'negative':len(neg)})
    rec_schema=objects['assets/contracts/live_readonly/v1/records.schema.json']
    rv=Draft202012Validator(rec_schema,registry=registry,format_checker=FormatChecker())
    uid='11111111-1111-4111-8111-111111111111'
    event={'protocol':'BH_LIVE_READONLY_V1','run_id':uid,'source_kind':'CONTROL','stream_id':uid,
           'generation':'0','sequence':'1','observation_id':uid,'observed_at_utc':'2026-09-09T20:00:00Z',
           'received_mono_us':'1','previous_hash':'0'*64,'content_hash':'a'*64,
           'payload_type':'HealthChange','payload':{'binding_id':None,'reason':'SOURCE_STARTED','state':'WAITING_FOR_DATA','epoch':'0','evidence_hashes':[]}}
    rv.validate(event)
    event_neg=[]
    for mutation in [lambda x:x['payload'].update(cookie='TEST_ONLY'), lambda x:x.update(source_kind='OPERATOR'),lambda x:x.update(sequence='0'),lambda x:x.update(observation_id='not-uuid')]:
        x=copy.deepcopy(event);mutation(x);event_neg.append(x)
    for x in event_neg:expect_schema_rejection(rv,x)
    ok('CLOSED_EVENT_UNION_CASES',{'positive':1,'negative':len(event_neg)})
    iv=Draft202012Validator(objects['assets/contracts/live_readonly/v1/run-intent.schema.json'],format_checker=FormatChecker())
    intent={'schema_version':'part-b-run-intent/v1','intent_id':uid,'stage':'PROVIDER_PROBE',
            'config_sha256':'a'*64,'source_tree_sha256':'b'*64,'fixture_ids':[10],'operator_urls':[],
            'max_duration_seconds':300,'max_http_attempts':20,'issued_at':'2026-09-09T20:00:00Z',
            'expires_at':'2026-09-09T20:15:00Z','user_confirmation_required':True,'money_authority':False}
    iv.validate(intent)
    for k,value in [('max_http_attempts',21),('max_duration_seconds',301),('money_authority',True),('api_key','TEST_ONLY')]:
        x=copy.deepcopy(intent);x[k]=value;expect_schema_rejection(iv,x)
    ok('INTENT_SHAPE_AND_PROBE_LIMIT_CASES',{'positive':1,'negative':4,'temporal_semantics':'assigned to PB-14; runtime not executed'})
    task_index=objects['registries/tasks.json'];tasks=task_index['tasks'];task_ids=[t['id'] for t in tasks]
    assert len(task_ids)==len(set(task_ids))==task_index['task_count']==25
    source_ids={s['id'] for s in objects['registries/sources.json']}
    for n,t in enumerate(tasks):
        assert set(t['dependencies'])<=set(task_ids[:n]),t['id']
        assert set(t['sources'])<=source_ids,t['id']
        assert t['files'] and t['interfaces'] and t['steps'] and t['acceptance']
        text=(ROOT/t['plan_path']).read_text()
        assert text.startswith('# '+t['id'])
        for h in ['Files owned/modified','Interfaces to produce','Read before implementation','Test-first execution','Exact verification commands','Acceptance','Error handling and continuation','Rollback']:
            assert '## '+h in text,(t['id'],h)
        for a in t['acceptance']:assert a in text,t['id']
        for i in t['interfaces']:assert i in text,t['id']
    cases=objects['registries/acceptance-cases.json']['cases']
    assert len(cases)==48==len({c['case_id'] for c in cases})
    assert {c['owner_task'] for c in cases}<=set(task_ids)
    ok('TASK_AND_ACCEPTANCE_DAG',{'tasks':len(tasks),'cases':len(cases),'sources':len(source_ids)})
    # All referenced future command scripts must have a task owner.
    owned={p for t in tasks for p in t['files']}
    required=set()
    for p in [ROOT/'06_EVIDENCE_AND_RUNS.md',ROOT/'03_KEY_GUIDE_VI.md',*(ROOT/'tasks').glob('*.md')]:
        for path in re.findall(r'\b(tools/[A-Za-z0-9_/-]+\.py)\b',p.read_text()):required.add(path)
    assert required<=owned,sorted(required-owned)
    ok('COMMAND_SCRIPT_OWNERSHIP',len(required))
    sql_files=sorted((ROOT/'assets/contracts/live_readonly/v1').glob('*.sql'))
    for path in sql_files:
        with sqlite3.connect(':memory:') as db:db.executescript(path.read_text())
    ok('LITERAL_SQL_DDL_COMPILES',len(sql_files))
    with sqlite3.connect(':memory:') as db:
        db.executescript((ROOT/'assets/contracts/live_readonly/v1/live-store.sql').read_text())
        db.execute('INSERT INTO run_meta VALUES(?,?,?,?,?,?,?)',('run','a'*64,'b'*64,'2026-09-09','LIVE_READ_ONLY',1,0))
        args=(1,'run','stream',0,1,'observation-1','CONTROL','HealthChange',b'{}','0'*64,'1'*64,'2026-09-09',1)
        db.execute('INSERT INTO live_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',args)
        db.execute('INSERT INTO stream_cursors VALUES(?,?,?,?,?,?,?)',(1,1,'run','stream',0,1,'1'*64))
        bad=list(args);bad[0]=2;bad[4]=3;bad[5]='observation-3';bad[9]='1'*64
        expect_sql_rejection(db,'INSERT INTO live_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',tuple(bad))
        bad[4]=2;bad[5]='observation-2';bad[9]='a'*64
        expect_sql_rejection(db,'INSERT INTO live_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',tuple(bad))
        expect_sql_rejection(db,'INSERT INTO stream_cursors VALUES(?,?,?,?,?,?,?)',(2,999,'run','stream',0,2,'2'*64))
        expect_sql_rejection(db,"UPDATE live_events SET content_hash=? WHERE receive_index=1",('a'*64,))
        expect_sql_rejection(db,'DELETE FROM live_events WHERE receive_index=1')
        db.execute('INSERT INTO run_closures VALUES(?,?,?,?)',('run','2026-09-09','USER_STOP',1))
        bad[9]='1'*64
        expect_sql_rejection(db,'INSERT INTO live_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',tuple(bad))
    with sqlite3.connect(':memory:') as db:
        db.executescript((ROOT/'assets/contracts/live_readonly/v1/quota-store.sql').read_text())
        args=('attempt','api-football-primary','scope','STATUS','2026-09-09','2026-09-09T20:00:00Z','boot',1)
        db.execute('INSERT INTO quota_reservations VALUES(?,?,?,?,?,?,?,?)',args)
        expect_sql_rejection(db,'INSERT INTO quota_reservations VALUES(?,?,?,?,?,?,?,?)',args)
        expect_sql_rejection(db,'DELETE FROM quota_reservations')
    with sqlite3.connect(':memory:') as db:
        db.executescript((ROOT/'assets/contracts/live_readonly/v1/intent-store.sql').read_text())
        args=('intent','a'*64,'run','PROVIDER_PROBE','b'*64,'c'*64,'2026-09-09T20:00:00Z','LOCAL_TTY_USER_CONFIRMATION',0)
        db.execute('INSERT INTO intent_consumptions VALUES(?,?,?,?,?,?,?,?,?)',args)
        expect_sql_rejection(db,'INSERT INTO intent_consumptions VALUES(?,?,?,?,?,?,?,?,?)',args)
        expect_sql_rejection(db,'DELETE FROM intent_consumptions')
    ok('SQL_CONSTRAINT_NEGATIVES',10)
    link_count=0
    for p in ROOT.rglob('*.md'):
        text=p.read_text()
        assert len(re.findall(r'^```',text,flags=re.M))%2==0,p
        for url in re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)',text):
            if re.match(r'^[a-z]+://',url) or url.startswith('#'):continue
            target=unquote(url.split('#')[0])
            assert (p.parent/target).is_file(),(str(p),target)
            link_count+=1
    ok('INTERNAL_MARKDOWN_LINKS_AND_FENCES',link_count)
    for path in (ROOT/'reference').glob('*.py'):ast.parse(path.read_text())
    run=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/'reference'),'-p','test_*.py','-v'],capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr
    assert 'Ran 13 tests' in run.stderr
    ok('REFERENCE_REQUEST_BUDGET_TESTS',13)
    result={'schema_version':'part-b-plan-validation/v1','status':'PASS','scope':'PACKAGE_STATIC_SCHEMAS_SQL_REFERENCE_MATH_ONLY',
            'runtime_implementation_executed':False,'real_api_calls':0,'real_credentials_requested':False,
            'checks':checks,'reference_test_output':run.stderr.strip()}
    (ROOT/'validation-result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
