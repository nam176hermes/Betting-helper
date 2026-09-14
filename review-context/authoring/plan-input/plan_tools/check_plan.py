"""Read-only semantic validation of the plan contract, never runtime execution."""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import tomllib
import json
import re
import sys
import ast
sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plan_tools.common import files, governed_root, verify_manifest
from plan_tools.finalize_contracts import logical
from jsonschema import Draft202012Validator

BAD = re.compile(r'(?i)(?:\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b|\.\.\.|<[^>]+>|\$\{|\$\(|`)')

def require(value,code):
    if not value:raise ValueError(code)

def ancestors(tasks):
    seen={}
    for t in tasks:
        tid=t['task_id'];deps=t['dependencies']
        require(tid not in seen,'E_TASK_DUPLICATE')
        require(all(d in seen for d in deps),'E_DEPENDENCY_UNKNOWN_OR_FUTURE')
        seen[tid]=set(deps).union(*(seen[d] for d in deps))
    return seen

def validate(manifest,commands,ownership,io,proof,review_a,review_commands,extractor):
    require(manifest['authorized_production_phases']=='NONE' and manifest['authority']=='PLAN_ONLY','E_PRODUCTION_AUTHORITY')
    tasks=manifest['tasks'];require(manifest['declared_task_count']==len(tasks),'E_TASK_COUNT')
    deps=ancestors(tasks);by={t['task_id']:t for t in tasks}
    own={e['path']:e for e in ownership['entries']};require(len(own)==len(ownership['entries']),'E_OWNER_DUPLICATE')
    allcmd=commands;cmd={c['command_id']:c for c in allcmd};require(len(cmd)==len(allcmd),'E_COMMAND_DUPLICATE')
    for c in allcmd:
        a=c['argv'];require(isinstance(a,list) and a and all(isinstance(x,str) and x.strip() for x in a),'E_ARGV')
        require(c['network']=='DENY' and c['provider_access']=='DENY' and c['authenticated_operator_access']=='DENY','E_COMMAND_AUTHORITY')
        require(not a[0].endswith('.md'),'E_PROMPT_COMMAND')
        require(not ('-c' in a and a[0] in ['python','python3','python3.12','bash','sh','zsh']) or c['command_id']=='BOOT0_EXTRACT_PLAN','E_INLINE_COMMAND')
        for i,token in enumerate(a):
            if token.endswith('.md'):require(i>0 and a[i-1] in ['--prompt','--prompt-file','--input'],'E_PROMPT_COMMAND')
        for i,x in enumerate(a):
            if c['command_id']=='BOOT0_EXTRACT_PLAN' and i>0 and a[i-1]=='-c':
                require(x==extractor,'E_BOOTSTRAP_EXTRACTOR_BINDING')
            else:require(not BAD.search(x),'E_COMMAND_PLACEHOLDER')
    def source_valid(entry):
        source=entry['source'];classification=entry['classification']
        if classification in ['BASELINE_INPUT','PLAN_SEED','GENERATED_OUTPUT']:
            return isinstance(source,dict) and set(source)=={'path'} and isinstance(source['path'],str) and source['path'].strip()
        if classification=='BASELINE_COPY':
            return isinstance(source,dict) and set(source)=={'path','sha256'} and isinstance(source['path'],str) and source['path'].strip() and isinstance(source['sha256'],str) and re.fullmatch(r'[0-9a-f]{64}',source['sha256'])
        if classification in ['TASK_OUTPUT','EVIDENCE_OUTPUT']:
            return source is None
        if classification=='EXTERNAL_INPUT':
            return isinstance(source,dict) and set(source) in [{'path','binding'},{'path','binding','creation_owner','creation_command'}] and all(isinstance(value,str) and value.strip() for value in source.values())
        return False
    def consumer(f,tid):
        require(f in own,'E_UNOWNED:'+f)
        e=own[f];require(source_valid(e),'E_OWNER_SOURCE:'+f);owner=e['creation_owner']
        require(owner is None and bool(e['source']) or isinstance(owner,str) and owner.strip() and owner in by,'E_OWNER_UNKNOWN:'+f)
        require(owner is None or owner==tid or owner in deps[tid],'E_CONSUMER_BEFORE_OWNER:'+f+':'+tid)
    def normalize(f):
        f=logical(f.split('::')[0].split('#')[0])
        return 'plan-input/'+f if f.startswith('bootstrap/') else f
    for t in tasks:
        tid=t['task_id'];require(t['authority'] in ['PLAN_AUTHORING','DISCOVERY_IMPLEMENTATION','REVIEW_TOOLING','EXTERNAL_REVIEW'],'E_TASK_AUTHORITY')
        require(t['rollback'] and all(x.strip() for x in t['rollback']),'E_EMPTY_ROLLBACK')
        states=['DECLARED','MATERIALIZED','EXECUTABLE','QUALIFIED','SEALED','EXTERNAL_REVIEWED']
        require(t['lifecycle_from'] in states and t['lifecycle_to'] in states and states.index(t['lifecycle_from'])<=states.index(t['lifecycle_to']),'E_LIFECYCLE_REGRESSION')
        require(t['exact_command_ids'] and all(c in cmd for c in t['exact_command_ids']),'E_COMMAND_UNKNOWN')
        for f in t['exact_files']+t['tests_first']+t['exact_symbols']+t['exact_schema_refs']:consumer(normalize(f),tid)
        for f in t['outputs']+t['evidence_artifacts']:
            f=normalize(f);consumer(f,tid);require(own[f]['creation_owner']==tid or tid in own[f]['modifying_tasks'],'E_OUTPUT_OWNER:'+tid+':'+f)
    for e in own.values():
        require(source_valid(e),'E_OWNER_SOURCE:'+e['path'])
        owner=e['creation_owner']
        require(isinstance(owner,str) and owner.strip() and owner in by or owner is None and e['source'],'E_OWNER_UNKNOWN:'+e['path'])
        for field in ['modifying_tasks','consumers']:
            require(all(isinstance(tid,str) and tid.strip() and tid in by for tid in e[field]),'E_OWNER_TASK_REFERENCE:'+e['path'])
        qualification=e['qualification_owner']
        require(qualification is None or isinstance(qualification,str) and qualification.strip() and qualification in by,'E_OWNER_QUALIFICATION:'+e['path'])
        for tid in e['consumers']:consumer(e['path'],tid)
    for row in io['commands']:
        require(row['command_id'] in cmd,'E_IO_COMMAND')
        for f in row['inputs']:
            for tid in row['consumers']:consumer(f,tid)
        for f in row['outputs']:require(f in own,'E_UNOWNED_OUTPUT:'+f)
    stages={'CANDIDATE':'V636-P07-T02','SEALED':'V636-P09-T04','REVIEWED':'V636-P10-T04'}
    for row in proof['entries']:
        require(row['stage'] in stages,'E_PROOF_STAGE')
        gate=stages[row['stage']];owner=row['evidence_owner']
        require(owner in deps[gate] or owner==gate,'E_FUTURE_EVIDENCE:'+row['requirement_id'])
        require(row['command_id'] in cmd,'E_PROOF_COMMAND')
    for cid in review_a['mechanical_command_ids']:
        require(cid in cmd and cmd[cid]['kind']=='review-leaf','E_REVIEW_RECURSION')
        require('run_review_a_checks.py' not in ' '.join(cmd[cid]['argv']),'E_REVIEW_RECURSION')
    # Last creation/qualification of a release tool precedes executable-reference completion.
    for f,e in own.items():
        if f.startswith('runtime/tools/') and any(x in f for x in ['export_','seal_','zero_parent','assemble_review','compute_governed']):
            q=e['qualification_owner'];require(q and q in deps['V636-P06-T03'],'E_LATE_RELEASE_QUALIFICATION:'+f)
    return {'task_count':len(tasks),'command_count':len(allcmd),'artifact_count':len(own)}

def pointers(root):
    count=0
    documents={str(p):json.loads(p.read_text()) for p in root.rglob('*.schema.json')}
    ids={d['$id']:d for d in documents.values() if '$id' in d}
    def resolve(data,ref):
        nonlocal count
        location,separator,fragment=ref.partition('#')
        require(not fragment or fragment.startswith('/'),'E_SCHEMA_NONPOINTER:'+ref)
        d=ids[location] if location else data
        for k in fragment[1:].split('/') if fragment else []:
            k=k.replace('~1','/').replace('~0','~');d=d[int(k)] if isinstance(d,list) else d[k]
        count+=1
    for data in documents.values():
        def walk(x):
            if isinstance(x,dict):
                if '$ref' in x:resolve(data,x['$ref'])
                for v in x.values():walk(v)
            elif isinstance(x,list):
                for v in x:walk(v)
        walk(data)
    j=lambda n:json.loads((root/n).read_text())
    refs=[r for t in j('docs/tasks/task-manifest.v6.3.6.json')['tasks'] for r in t['exact_schema_refs']]
    refs += [r['plan_source_path']+r['json_pointer'] for r in j('docs/registries/schema-reference-registry.v1.json')['references']]
    for ref in refs:
        f,fragment=ref.split('#',1);resolve(j(f.removeprefix('pack/')),'#'+fragment)
    return count

def cross_contracts(root):
    """Validate producer, build and isolated-review seams, not just identifiers."""
    j=lambda n:json.loads((root/n).read_text())
    tasks=j('docs/tasks/task-manifest.v6.3.6.json')['tasks'];by={t['task_id']:t for t in tasks};deps=ancestors(tasks)
    own={e['path']:e for e in j('docs/registries/artifact-ownership.v1.json')['entries']}
    commands=sum((j('docs/registries/'+n)['commands'] for n in ['task-command-registry.v1.json','review-command-registry.v1.json','cybersecurity-command-registry.v1.json']),[])
    cmd={c['command_id']:c for c in commands}
    migration=j('docs/registries/version-rebinding.v1.json')
    for patch in migration['patches']:
        require('V636-MIG0-T03' in own[patch['path']]['modifying_tasks'],'E_MIGRATION_MODIFIER:'+patch['path'])
        source=Path(patch['source_path']).read_bytes()
        require(hashlib.sha256(source).hexdigest()==patch['before_sha256'],'E_PATCH_SOURCE')
        transformed=source.decode()
        for replacement in patch['replacements']:
            require(replacement['old'] in transformed,'E_PATCH_OPERAND')
            transformed=transformed.replace(replacement['old'],replacement['new'])
        require(hashlib.sha256(transformed.encode()).hexdigest()==patch['after_sha256'],'E_PATCH_RESULT')
    # A generated child must be rebuilt after its latest source writer and before its consumer.
    child='runtime/extension/.test-build/test-harness/indexeddb-crash-child.js'
    source=own[own[child]['source']['path']]
    writer='V636-P03-T02';consumer='V636-P03-T03';compiler='COMPILE_CRASH_HARNESS_AFTER_IMPLEMENTATION'
    require(writer in source['modifying_tasks'] and writer in own[child]['modifying_tasks'],'E_STALE_HARNESS_OWNER')
    require(writer in deps[consumer] and compiler in by[writer]['exact_command_ids'],'E_STALE_HARNESS_COMPILE')
    require(by[writer]['exact_command_ids'].index(compiler)<by[writer]['exact_command_ids'].index('TEST_V636_P03_T02'),'E_STALE_HARNESS_ORDER')
    require(cmd[compiler]['argv']==cmd['COMPILE_CRASH_HARNESS']['argv'],'E_HARNESS_CONFIG')
    security=j('docs/registries/cybersecurity-command-registry.v1.json')['commands']
    expected=sorted(c['argv'][1] for c in security if c['argv'][0]=='node')
    require(len(expected)==6 and cmd['TEST_SECURITY_TS']['argv']==['node','--test',*expected],'E_SECURITY_ARGV')
    schema=j('docs/schemas/review-launch-authorization.schema.json')['$defs']['ReviewLaunchAuthorization']['properties']
    fp='/home/thenam176/betting-helper/review-packs/hybrid-discovery-v6.3.6'
    seal_files={fp+'.zip',fp+'.zip.sha256',fp+'.seal-attestation.json'}
    configs=[j('docs/configs/review-'+role+'.v1.json') for role in ['a','b']]
    for role,cfg in zip(['a','b'],configs):
        for field,key in [('workspace_root','workspace_root'),('allowed_output_root','output_root')]:
            require(Draft202012Validator(schema[field]).is_valid(cfg[key]),'E_REVIEW_PATH_SCHEMA')
            require(cfg[key].endswith('/review-'+role),'E_REVIEW_ROLE_PATH')
        mounts=cfg['input_mounts'];paths=[m['source_root'] for m in mounts]
        require(len(paths)==len(set(paths))==5 and seal_files.issubset(paths),'E_REVIEW_SEAL_MOUNT')
        require(all(m['mode']=='READ_ONLY' and m['source_root']==m['workspace_mount'] for m in mounts),'E_REVIEW_MOUNT_MODE')
        require(schema['input_mounts']['minItems']==schema['input_mounts']['maxItems']==len(mounts),'E_REVIEW_MOUNT_SCHEMA')
        require(set(cfg['seal_inputs'].values())==seal_files,'E_REVIEW_SEAL_BINDING')
    io={r['command_id']:r for r in j('docs/registries/command-io.v1.json')['commands']}
    binding_outputs=['runtime/task-command-registry.json',*['runtime/review-config/'+name for name in ('review-a.v1.json','review-b.v1.json','review-aggregation.v1.json','review-authority.v1.json')]]
    binding_inputs=['authoring-tools/build_task_command_registry.py','pack/docs/tasks/task-manifest.v6.3.6.json','pack/docs/registries/task-command-registry.v1.json',*['pack/docs/configs/'+name for name in ('review-a.v1.json','review-b.v1.json','review-aggregation.v1.json','review-authority.v1.json')]]
    for task_id,command_id in [('V636-MIG0-T05','VERIFY_V636_MIG0_T05'),('V636-MIG0-T07','V636_MIG0_T07_BINDINGS'),('V636-MIG0-T08','V636_MIG0_T08_BINDINGS')]:
        require(set(binding_outputs)<=set(by[task_id]['outputs']) and set(binding_outputs)<=set(by[task_id]['exact_files']),'E_MIG0_BINDING_TASK:'+task_id)
        row=io[command_id]
        require(row['inputs']==binding_inputs and row['outputs']==binding_outputs and row['input_directories']==['pack/docs/configs'],'E_MIG0_BINDING_IO:'+command_id)
    materialization_inputs={'.bootstrap/authoring-workspace-receipt.json','plan-input/MANIFEST_SHA256.json','plan-input/docs/tasks/task-manifest.v6.3.6.json','plan-input/docs/registries/artifact-ownership.v1.json','plan-input/docs/schemas/artifact-ownership.schema.json'}
    gate=by['V636-P01-T06']
    require(materialization_inputs<=set(io['TEST_V636_P01_T06']['inputs']),'E_MATERIALIZATION_GATE_INPUTS')
    require('pack/docs/schemas/artifact-ownership.schema.json#/$defs/ArtifactOwnershipRegistry' in gate['exact_schema_refs'],'E_MATERIALIZATION_GATE_SCHEMA')
    args=cmd['A_CHECK_EVIDENCE']['argv']
    for flag,file in [('--attestation',fp+'.seal-attestation.json'),('--zip',fp+'.zip'),('--sidecar',fp+'.zip.sha256')]:
        require(flag in args and args[args.index(flag)+1]==file,'E_REVIEW_SEAL_ARGV')
        require(file in io['A_CHECK_EVIDENCE']['inputs'],'E_REVIEW_SEAL_IO')
    for row in j('docs/registries/proof-coverage-matrix.v1.json')['entries']:
        if row['stage']=='SEALED':
            require(row['evidence_artifact']==fp+'.seal-attestation.json' and row['sealed_evidence_path'] is None and row['evidence_owner']=='V636-P09-T04','E_SEALED_EVIDENCE_SOURCE')
    receipt=j('docs/schemas/review-execution-receipt.schema.json')['$defs']
    roots=next(d['properties']['input_content_roots'] for d in receipt.values() if 'input_content_roots' in d.get('properties',{}))
    require(roots['minItems']==roots['maxItems']==5,'E_REVIEW_RECEIPT_INPUTS')
    release=by['V636-P05-T09']
    expected_release=[p.removeprefix('runtime/') for p in release['tests_first']]
    require(cmd['TEST_RELEASE_TOOLS']['argv'][5:]==expected_release,'E_PREMATURE_RELEASE_COLLECTION')
    baseline=j('docs/registries/inherited-baseline-qualification.v1.json')
    source_root=Path(j('docs/registries/baseline-source-files.v1.json')['root'])
    for row in baseline['python_files']+baseline['typescript_files']+baseline['source_consumers']+baseline['extra_test_sources']:
        source=source_root/row['path'].removeprefix('runtime/')
        require(hashlib.sha256(source.read_bytes()).hexdigest()==row['source_sha256'],'E_INHERITED_CONSUMER_SOURCE')
        writers=row.get('modification_owners',[row.get('modification_owner')])
        for writer in filter(None,writers):
            require(writer in own[row['path']]['modifying_tasks'] and row['path'] in by[writer]['outputs'],'E_INHERITED_ADAPTATION_OWNER')
        if 'tests' in row:
            names=sorted(n.name for n in ast.parse(source.read_text()).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_'))
            require(names==sorted(t['symbol'] for t in row['tests']),'E_INHERITED_TEST_COVERAGE')
    for fixture in baseline['fixtures']:
        data=(root/fixture['plan_destination']).read_bytes()
        require(len(data)==fixture['size'] and hashlib.sha256(data).hexdigest()==fixture['sha256'],'E_INHERITED_FIXTURE')
    mapping=j('docs/registries/normative-source-map.v1.json')
    pairs={(e['plan_source'],e['vendor_relative']) for e in mapping['inherited_entries']+mapping['plan_entries']}
    for row in baseline['historical_reads']:
        require((root/row['plan_source']).is_file() and (row['plan_source'],row['runtime_vendor_relative']) in pairs,'E_INHERITED_READ_BINDING')
        require(row['owner_task'] in own[row['consumer']]['modifying_tasks'],'E_INHERITED_READ_OWNER')
    topology=j('docs/registries/verification-topology.v1.json')
    replay={c['command_id']:c for c in j('docs/registries/baseline-replay-command-registry.v1.json')['commands']}
    for row in baseline['qualification_commands']:
        cid=row['command_id'];require(cid in release['exact_command_ids'] and cid in topology['candidate_command_ids'],'E_INHERITED_QUALIFICATION')
        require(cmd[cid]['argv']==row['argv'],'E_INHERITED_COMMAND')
        expected=[a.replace('/hybrid-discovery-v6.3.6-authoring/runtime','/discovery-runtime-v6.3.6') for a in row['argv']]
        require(replay['BASELINE__'+cid]['argv']==expected,'E_BASELINE_ARGV_ROOT')
    require('VERIFY_FINAL_MIGRATION' in by['V636-MIG0-T08']['exact_command_ids'],'E_FINAL_MIGRATION_SCAN')
    require(migration['final_legacy_policy']['initial_hashes_apply_only_at']=='V636-MIG0-T03','E_MIGRATION_STAGE_HASH')
    require('COMPILE_PRODUCTION' in release['exact_command_ids'] and cmd['COMPILE_PRODUCTION']['argv'][-1]=='tsconfig.build.json','E_PRODUCTION_BUILD_COMMAND')
    require(release['exact_command_ids'].index('COMPILE_PRODUCTION')<release['exact_command_ids'].index('TEST_SECURITY_TS'),'E_PRODUCTION_BUILD_ORDER')
    sources={f for f in own if f.startswith('runtime/extension/src/') and f.endswith('.ts') and not f.endswith('.d.ts')}
    expected_dist={'runtime/extension/dist/'+f.removeprefix('runtime/extension/src/').removesuffix('.ts')+'.js' for f in sources}
    require(expected_dist and expected_dist=={f for f in own if f.startswith('runtime/extension/dist/')},'E_PRODUCTION_BUILD_INVENTORY')
    for f in expected_dist:require(own[f]['creation_owner']=='V636-P05-T09','E_PRODUCTION_BUILD_OWNER')
    before=by['V636-P08-T03']['exact_command_ids']
    require(before[:2]==['BASELINE_INSTALL_PYTHON','BASELINE_INSTALL_NODE'],'E_BASELINE_ENVIRONMENT_ORDER')
    for cid in before[:2]:
        require(cmd[cid]['cwd']=='/home/thenam176/betting-helper/discovery-runtime-v6.3.6' and '--offline' in cmd[cid]['argv'],'E_BASELINE_ENVIRONMENT_ROOT')
    for role,cfg in zip(['a','b'],configs):
        require(cfg['preparation_command_ids']==[role.upper()+'_INSTALL_PYTHON',role.upper()+'_INSTALL_NODE'],'E_REVIEW_ENVIRONMENT_SETUP')
        node=cfg['node_environment'];require(len(node['project_inputs'])==4 and len(node['dependency_mounts'])==2,'E_REVIEW_NODE_PROJECTION')
        require(cmd[node['install_command_id']]['cwd']==node['project_root'] and '--ignore-scripts' in cmd[node['install_command_id']]['argv'],'E_REVIEW_NODE_INSTALL')
        require(all(r['mode']=='READ_ONLY' and r['source_root'].startswith(cfg['scratch_root']+'/') for r in node['dependency_mounts']),'E_REVIEW_NODE_MOUNT')
    require('--candidate-receipt' in cmd['VERIFY_V636_P08_T01']['argv'] and 'authoring HEAD' not in by['V636-P08-T01']['objective'],'E_EXPORT_QUALIFIED_INPUT')
    return {'migration_patch_owners':len(migration['patches']),'review_mounts_per_role':5,'exact_security_js_files':6,'inherited_python_tests':sum(len(row['tests']) for row in baseline['python_files'])}

def check(root, sealed=False):
    root=Path(root);j=lambda n:json.loads((root/n).read_text())
    commands=sum((j('docs/registries/'+n)['commands'] for n in ['task-command-registry.v1.json','review-command-registry.v1.json','cybersecurity-command-registry.v1.json','baseline-replay-command-registry.v1.json']),[])
    result=validate(j('docs/tasks/task-manifest.v6.3.6.json'),commands,j('docs/registries/artifact-ownership.v1.json'),j('docs/registries/command-io.v1.json'),j('docs/registries/proof-coverage-matrix.v1.json'),j('docs/configs/review-a.v1.json'),j('docs/registries/review-command-registry.v1.json'),(root/'bootstrap/extract_plan.py').read_text())
    result['resolved_schema_pointers']=pointers(root)
    crash=j('docs/vectors/inherited/durability-crash-v6.2.json')['cases'];rows=j('docs/registries/crash-harness-registry.v1.json')['entries'];cmd={c['command_id']:c for c in commands}
    require(len(crash)==46 and Counter(c['id'] for c in crash)==Counter(r['vector_id'] for r in rows),'E_CRASH_COVERAGE')
    for r in rows:
        c=crash[r['source_case_index']]
        require(all(c[k]==r[v] for k,v in [('id','vector_id'),('expected','expected_post_restart_state'),('kill','kill_action'),('boundary','source_boundary')]),'E_CRASH_STATE')
        require(r['child_command_id'] in cmd and r['verification_command_id'] in cmd and r['crash_checkpoint'],'E_CRASH_COMMAND')
    result['crash_cases']=len(rows)
    clock=j('docs/vectors/inherited/clock-coherence-v6.2.json');ids=[]
    def walk(x):
        if isinstance(x,dict):
            for k,v in x.items():
                if k in ['id','vector_id']:ids.append(v)
                walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(clock);coverage=j('docs/registries/clock-vector-coverage.v1.json')['entries']
    require(len(ids)==65 and Counter(ids)==Counter(r['vector_id'] for r in coverage),'E_CLOCK_COVERAGE')
    precedence=j('docs/registries/clock-failure-precedence.v1.json')
    require(len(clock['mapping_negative_vectors'])==len(precedence['negative_vectors'])==16,'E_CLOCK_NEGATIVES')
    result.update(clock_vectors=65,mapping_negatives=16)
    for name in ['a','b']:
        c=j('docs/configs/review-'+name+'.v1.json');require(c['workspace_root'].endswith('/review-'+name),'E_REVIEW_WORKSPACE')
    topology=j('docs/registries/verification-topology.v1.json')
    require(all(cmd[x]['kind']=='verification' for x in topology['candidate_command_ids']),'E_CANDIDATE_RECURSION')
    if sealed:
        result.update(verify_manifest(root));data=files(root);require(governed_root(data)==j('GOVERNED_CONTENT_ROOT.json')['root_sha256'],'E_GOVERNED_ROOT')
    # Verify supplied configuration, inherited bindings, and actual prerequisite source bytes.
    cfg=tomllib.loads((root/'docs/configs/runtime-pyproject.toml').read_text())
    require(cfg['tool']['pytest']['ini_options']['testpaths']==['tests','../authoring-tests'],'E_PYTEST_DISCOVERY')
    require('test-harness/**/*.ts' in j('docs/configs/tsconfig.test.json')['include'],'E_TS_HARNESS')
    require('test-harness' in j('docs/configs/tsconfig.build.json')['exclude'],'E_PRODUCTION_HARNESS')
    for row in j('docs/registries/normative-source-map.v1.json')['inherited_entries']:
        expected=row.get('plan_sha256',row['source_sha256'])
        require(hashlib.sha256((root/row['plan_source']).read_bytes()).hexdigest()==expected,'E_INHERITED_BYTES')
    source=j('docs/registries/baseline-source-files.v1.json')
    for row in source['files']:
        b=(Path(source['root'])/row['path']).read_bytes()
        require(len(b)==row['size'] and hashlib.sha256(b).hexdigest()==row['sha256'],'E_BASELINE_SOURCE_DRIFT:'+row['path'])
    for row in j('docs/registries/source-inputs.v1.json')['required_plan_source_files']:
        require(hashlib.sha256((root/row['path']).read_bytes()).hexdigest()==row['sha256'],'E_PREDECESSOR_DRIFT')
    result['pinned_baseline_files']=len(source['files'])
    result.update(cross_contracts(root))
    result['authorized_production_phases']='NONE';result['result']='PASS'
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--sealed',action='store_true');a=p.parse_args()
    print(json.dumps(check(a.root,a.sealed),indent=2))
