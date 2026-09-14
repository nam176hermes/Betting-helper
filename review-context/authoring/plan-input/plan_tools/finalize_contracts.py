"""Regenerate ownership, command I/O, seed and topology registries from declared tasks."""
from pathlib import Path
import json
import re
import posixpath
from fnmatch import fnmatch
import sys
sys.dont_write_bytecode = True
P=Path(__file__).resolve().parents[1]
PREFIX='/home/thenam176/betting-helper'; A=PREFIX+'/hybrid-discovery-v6.3.6-authoring'; E=PREFIX+'/authoring-evidence/hybrid-discovery-v6.3.6'; F=PREFIX+'/discovery-runtime-v6.3.6'; FP=PREFIX+'/review-packs/hybrid-discovery-v6.3.6'; PLAN=PREFIX+'/plan-input/hybrid-discovery-v6.3.6-authoritative-design-plan'
REVIEW_CONFIGS=('review-a.v1.json','review-b.v1.json','review-aggregation.v1.json','review-authority.v1.json')
P01_GATE_INPUTS=['.bootstrap/authoring-workspace-receipt.json','plan-input/MANIFEST_SHA256.json','plan-input/docs/tasks/task-manifest.v6.3.6.json','plan-input/docs/registries/artifact-ownership.v1.json','plan-input/docs/schemas/artifact-ownership.schema.json']
def read(n):return json.loads((P/n).read_text())
def dump(n,d):
 f=P/n;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
def logical(s,cwd=A):
 if not s.startswith('/'):s=cwd+'/'+s
 s=posixpath.normpath(s)
 for root,prefix in [(PLAN,'plan-input'),(A+'/plan-input','plan-input'),(F,'runtime'),(FP,'pack'),(A,'')]:
  if s==root or s.startswith(root+'/'):return (prefix+'/'+s[len(root):].lstrip('/')).strip('/')
 return s

def main():
 m=read('docs/tasks/task-manifest.v6.3.6.json');ts=m['tasks'];by={t['task_id']:t for t in ts};order={t['task_id']:i for i,t in enumerate(ts)}
 reg=read('docs/registries/task-command-registry.v1.json');cmd={c['command_id']:c for c in reg['commands']}
 inherited=read('docs/registries/inherited-baseline-qualification.v1.json')
 # Integrate semantic adaptations in canonical tasks, so ownership survives regeneration.
 for row in inherited['python_files']+inherited['typescript_files']+inherited['source_consumers']+inherited['extra_test_sources']:
  writers=row.get('modification_owners',[row.get('modification_owner')])
  for owner in filter(None,writers):
   task=by[owner]
   for key in ['outputs','exact_files']:task[key]=sorted(set(task[key]+[row['path']]))
   task['exact_files']=sorted(set(task['exact_files']+['pack/docs/registries/inherited-baseline-qualification.v1.json']))
   obligation=row.get('interface_obligation','Preserve all named tests and negative cases; adapt inputs according to docs/contracts/09-inherited-baseline-qualification.md.')
   if owner!='V636-MIG0-T03' and obligation not in task['acceptance_criteria']:task['acceptance_criteria'].append(obligation)
  by['V636-P05-T09']['exact_files']=sorted(set(by['V636-P05-T09']['exact_files']+[row['path']]))
 for row in inherited['qualification_commands']:
  cid=row['command_id'];owner=row['owner']
  cmd[cid]={k:v for k,v in row.items() if k!='owner'}
  cmd[cid].update(purpose=cid,kind='verification',available_at='QUALIFIED',network='DENY',provider_access='DENY',authenticated_operator_access='DENY')
  if cid not in by[owner]['exact_command_ids']:by[owner]['exact_command_ids'].append(cid)
 cmd['BOOT0_EXTRACT_PLAN']['argv']=['python3.12','-B','-c',(P/'bootstrap/extract_plan.py').read_text(),'--zip',PREFIX+'/inputs/hybrid-discovery-v6.3.6-authoritative-design-plan.zip','--sidecar',PREFIX+'/inputs/hybrid-discovery-v6.3.6-authoritative-design-plan.zip.sha256','--destination',PLAN]
 for c in cmd.values():
  if c['argv'][0]=='python3.12' and '-B' not in c['argv']:c['argv'].insert(1,'-B')
 for cid in ['MIG0_UV_SYNC','MIG0_PNPM_INSTALL']:
  if cid not in by['V636-MIG0-T05']['exact_command_ids']:by['V636-MIG0-T05']['exact_command_ids'].append(cid)
 # One exact task owns each command execution; reused migration installs are new command IDs.
 for cid in ['MIG0_UV_SYNC','MIG0_PNPM_INSTALL']:
  if cid in by['V636-MIG0-T07']['exact_command_ids']:
   new=cid+'_REFRESH';cmd[new]=dict(cmd[cid],command_id=new,purpose=new);by['V636-MIG0-T07']['exact_command_ids']=[new if x==cid else x for x in by['V636-MIG0-T07']['exact_command_ids']]
 binding_outputs=['runtime/task-command-registry.json',*['runtime/review-config/'+name for name in REVIEW_CONFIGS]]
 for task_id in ['V636-MIG0-T05','V636-MIG0-T07','V636-MIG0-T08']:
  for field in ['outputs','exact_files']:
   by[task_id][field]=sorted(set(by[task_id][field]+binding_outputs))
 gate=by['V636-P01-T06']
 gate['inputs']=sorted(set(gate['inputs']+P01_GATE_INPUTS))
 gate['exact_schema_refs']=sorted(set(gate['exact_schema_refs']+['pack/docs/schemas/artifact-ownership.schema.json#/$defs/ArtifactOwnershipRegistry']))
 # Runtime binding outputs are generated only by MIG0 refreshes.
 for t in ts:
  if t['phase']=='P05':t['outputs']=[f for f in t['outputs'] if not f.startswith('runtime/review-config/')]
 # Supplied pack inputs are seeded before P00; later tasks read them without rewriting normative data.
 seed_sources=[f.relative_to(P).as_posix() for f in P.rglob('*') if f.is_file() and (f.relative_to(P).as_posix().startswith('docs/') or f.name in ['README.md','AGENTS.md','plan-manifest.json','DESIGN_V6_3_6.md','IMPLEMENTATION_PLAN_V6_3_6.md','REPAIR_MATRIX_V6_3_6.md'])]
 # Include generated registry paths even on the first run.
 generated=['seed-artifacts.v1.json','artifact-ownership.v1.json','command-io.v1.json','verification-topology.v1.json','normative-source-map.v1.json','baseline-replay-command-registry.v1.json','delivery-map.v1.json']
 seed_sources=sorted(set(seed_sources)|{'docs/registries/'+n for n in generated})
 seeds=[{'source':s,'destination':'pack/'+s} for s in seed_sources]
 dump('docs/registries/seed-artifacts.v1.json',{'schema_version':'seed-artifacts/v1','owner':'V636-BOOT0-T02','entries':seeds})
 seeded={r['destination']:r['source'] for r in seeds}
 for t in ts:t['outputs']=[f for f in t['outputs'] if f not in seeded]
 baseline=read('docs/registries/baseline-source-files.v1.json');base={e['path']:e for e in baseline['files']}
 outputs={}
 for t in ts:
  for f in t['outputs']:outputs.setdefault(logical(f),[]).append(t['task_id'])
 artifacts={}
 def add(path,owner,classification='TASK_OUTPUT',source=None,materialize=True,modifiers=None,qualification=None):
  artifacts[path]={'path':path,'classification':classification,'creation_owner':owner,'modifying_tasks':modifiers or [],'materialization_required':materialize,'source':source,'qualification_owner':qualification,'consumers':[]}
 for f,e in base.items():
  if f.startswith('vendor/') or f in ['schema-lock.json','task-command-registry.json']:continue
  path='runtime/'+f;mods=outputs.get(path,[])
  add(path,'V636-MIG0-T02','BASELINE_COPY',{'path':baseline['root']+'/'+f,'sha256':e['sha256']},modifiers=mods,qualification=mods[-1] if mods else 'V636-MIG0-T06')
 for dest,source in seeded.items():add(dest,'V636-BOOT0-T02','PLAN_SEED',{'path':'plan-input/'+source})
 for f in sorted(P.rglob('*')):
  if f.is_file() and '__pycache__' not in f.parts:
   rel=f.relative_to(P).as_posix();add('plan-input/'+rel,None,'BASELINE_INPUT',{'path':rel})
 for name in ['GOVERNED_CONTENT_ROOT.json','SELF_REVIEW_REPORT.md','SELF_REVIEW_REPORT.json','MANIFEST_SHA256.json']:
  add('plan-input/'+name,None,'BASELINE_INPUT',{'path':name})
 for f,mods in outputs.items():
  if f in artifacts:
   if artifacts[f]['classification']!='PLAN_SEED':artifacts[f]['modifying_tasks']=sorted(set(artifacts[f]['modifying_tasks']+mods),key=order.get)
   continue
  sourcefile=f.startswith('runtime/') and (f.endswith(('.py','.ts','.json','.toml','.yaml')) and not f.endswith('SCHEMA_SHA256.json'))
  if sourcefile:
   creator=mods[0] if order[mods[0]]<order['V636-P01-T02'] else 'V636-P01-T02'
   add(f,creator,modifiers=[x for x in mods if x!=creator],qualification=mods[-1])
  else:
   external=f.startswith('/') or '/receipts/' in f or f.startswith('pack/') and f.split('/')[-1] in ['GOVERNED_CONTENT_ROOT.json','SELF_REVIEW_REPORT.md','SELF_REVIEW_REPORT.json','MANIFEST_SHA256.json']
   add(f,mods[0],'EVIDENCE_OUTPUT' if external else 'TASK_OUTPUT',materialize=not external,modifiers=mods[1:])
 # Schema/source tools and imported configs that appear as readers are still explicit baseline seeds.
 for name in REVIEW_CONFIGS:
  add('runtime/review-config/'+name,'V636-MIG0-T05','GENERATED_OUTPUT',{'path':'pack/docs/configs/'+name},modifiers=['V636-MIG0-T07','V636-MIG0-T08'],qualification='V636-MIG0-T08')
 for path in ['runtime/schema-lock.json','runtime/task-command-registry.json','runtime/vendor/hybrid-discovery-v6.3.6/SCHEMA_SHA256.json']:
  add(path,'V636-MIG0-T04' if 'task-command' not in path else 'V636-MIG0-T05','GENERATED_OUTPUT',{'path':'pack/docs/registries/normative-source-map.v1.json'},modifiers=['V636-MIG0-T07','V636-MIG0-T08'],qualification='V636-MIG0-T08')
 for path in ['runtime/uv.lock','runtime/pnpm-lock.yaml']:
  if path in artifacts:artifacts[path]['modifying_tasks']=list(dict.fromkeys(artifacts[path]['modifying_tasks']+['V636-MIG0-T07']))
 # Rebinding is a real write, not implicit permission inherited from copying.
 for patch in read('docs/registries/version-rebinding.v1.json')['patches']:
  e=artifacts[patch['path']]
  e['modifying_tasks']=sorted(set(e['modifying_tasks']+['V636-MIG0-T03']),key=order.get)
 nm=read('docs/registries/normative-source-map.v1.json');nm['plan_entries']=[{'plan_source':s,'vendor_relative':s} for s in seed_sources if s.startswith('docs/') and not s.startswith(('docs/inherited/','docs/reviews/','docs/receipts/','docs/plans/','docs/sources/'))]
 dump('docs/registries/normative-source-map.v1.json',nm)
 for row in nm['inherited_entries']+nm['plan_entries']:
  add('runtime/vendor/hybrid-discovery-v6.3.6/'+row['vendor_relative'],'V636-MIG0-T04','GENERATED_OUTPUT',{'path':'pack/'+row['plan_source']},modifiers=['V636-MIG0-T07','V636-MIG0-T08'],qualification='V636-MIG0-T08')
 for t in ts:
  for f in t['evidence_artifacts']:add(f,t['task_id'],'EVIDENCE_OUTPUT',materialize=False)
 for f,owner in [(E+'/CANDIDATE_QUALIFICATION.json','V636-P07-T03'),(FP+'.zip','V636-P09-T04'),(FP+'.zip.sha256','V636-P09-T04'),(FP+'.seal-attestation.json','V636-P09-T04')]:add(f,owner,'EVIDENCE_OUTPUT',materialize=False)
 for f in [PREFIX+'/inputs/hybrid-discovery-v6.3.6-authoritative-design-plan.zip',PREFIX+'/inputs/hybrid-discovery-v6.3.6-authoritative-design-plan.zip.sha256']:
  add(f,None,'EXTERNAL_INPUT',{'path':f,'binding':'EXTERNAL_DELIVERY_SIDECAR'},False)
 for name in ['ed25519-private-key.pem','ed25519-public-key.json','state.sqlite']:
  path='/home/thenam176/.config/hybrid-discovery/review-authority/'+name
  add(path,None,'EXTERNAL_INPUT',{'path':path,'creation_owner':'HOST_REVIEW_AUTHORITY','creation_command':'HOST_REVIEW_AUTHORITY_BOOTSTRAP','binding':'REQUIRED_HUMAN_HOST_INPUT_BEFORE_P10'},False)
 for f,e in list(artifacts.items()):
  if f.startswith('runtime/extension/') and f.endswith('.ts'):
   rel=f.removeprefix('runtime/extension/').removesuffix('.ts')+'.js'
   source_rel=f.removeprefix('runtime/extension/')
   harness=any((fnmatch(source_rel,pattern) or fnmatch(source_rel,pattern.replace("/**/","/"))) for pattern in read('docs/configs/tsconfig.harness.json')['include'])
   creator='V636-MIG0-T07' if harness else 'V636-P04-T03'
   modifiers=(['V636-P03-T02'] if harness else [])+(['V636-P04-T03'] if harness else [])+['V636-P05-T09']
   add('runtime/extension/.test-build/'+rel,creator,'GENERATED_OUTPUT',{'path':f},materialize=False,modifiers=modifiers,qualification='V636-P05-T09')
   if f.startswith('runtime/extension/src/') and not f.endswith('.d.ts'):
    destination='runtime/extension/dist/'+f.removeprefix('runtime/extension/src/').removesuffix('.ts')+'.js'
    add(destination,'V636-P05-T09','GENERATED_OUTPUT',{'path':f},materialize=False,qualification='V636-P05-T09')
    artifacts[destination]['consumers']=['V636-P05-T09','V636-P07-T01','V636-P08-T01','V636-P08-T03','V636-P10-T02']
 # Offline environments are generated scratch, not exported source or signed pack inputs.
 for path in [F+'/.venv',F+'/node_modules',F+'/extension/node_modules']:
  add(path,'V636-P08-T03','GENERATED_OUTPUT',{'path':'runtime/uv.lock' if '.venv' in path else 'runtime/pnpm-lock.yaml'},materialize=False)
 for role in ['a','b']:
  config=read('docs/configs/review-'+role+'.v1.json');owner='V636-P10-T01' if role=='a' else 'V636-P10-T02'
  node=config['node_environment']
  for row in node['project_inputs']:
   add(node['project_root']+'/'+row['destination'],owner,'GENERATED_OUTPUT',{'path':logical(row['source'])},materialize=False)
  for row in node['dependency_mounts']:
   add(row['source_root'],owner,'GENERATED_OUTPUT',{'path':'runtime/pnpm-lock.yaml'},materialize=False)
  add(config['environment']['UV_PROJECT_ENVIRONMENT'],owner,'GENERATED_OUTPUT',{'path':'runtime/uv.lock'},materialize=False)
 # Source creation is complete in P01. Qualified behavior remains assigned to its declared implementation task.
 early=by['V636-P01-T02'];new_sources=[f for f,e in artifacts.items() if e['creation_owner']=='V636-P01-T02']
 early['exact_files']=sorted(set(early['exact_files']+new_sources));early['outputs']=sorted(set(early['outputs']+new_sources))
 candidate_ids=[c['command_id'] for c in cmd.values() if c['kind']=='verification' and (c['command_id'].startswith(('TEST_','COMPILE_','QUALIFY_')) or c['command_id']=='VERIFY_REVIEW_AUTHORITY_BOOTSTRAP')]
 candidate_ids.sort(key=lambda cid:not cid.startswith('COMPILE_'))
 baseline_commands=[]
 for cid in candidate_ids:
  original=cmd[cid]
  baseline_commands.append(dict(original,command_id='BASELINE__'+cid,cwd=original['cwd'].replace(A+'/runtime',F),argv=[arg.replace(A+'/runtime',F) for arg in original['argv']],kind='baseline-verification',purpose='Post-commit runtime replay of '+cid))
 dump('docs/registries/baseline-replay-command-registry.v1.json',{'schema_version':'baseline-replay-command-registry/v1','commands':baseline_commands,'runtime_root':F,'source_registry':'pack/docs/registries/task-command-registry.v1.json','rule':'Same qualified runtime test argv; exact cwd rebound to the delivered repository. No authoring command or registry runner is replayed.'})
 delivery=[]
 for f,e in list(artifacts.items()):
  if f.startswith(('authoring-tools/','authoring-tests/')):
   destination='pack/authoring-source/'+f
   add(destination,'V636-P09-T01','GENERATED_OUTPUT',{'path':f},materialize=False)
   delivery.append({'source':f,'destination':destination,'owner':'V636-P09-T01'})
 dump('docs/registries/delivery-map.v1.json',{'schema_version':'delivery-map/v1','authoring_source_exports':delivery,'runtime_source_root':A+'/runtime','final_runtime_root':F,'rule':'Sealed-review reference resolution maps historic authoring source paths through this exact source export; runtime references resolve in final runtime. No authoring workspace mount is needed.'})
 all_commands=list(cmd.values())+read('docs/registries/review-command-registry.v1.json')['commands']+read('docs/registries/cybersecurity-command-registry.v1.json')['commands']+baseline_commands
 io=[];unknown=[]
 output_flags={'--output','--output-dir','--destination','--zip','--sidecar','--attestation'}
 for c in all_commands:
  consumers=[t['task_id'] for t in ts if c['command_id'] in t['exact_command_ids']]
  if c['kind']=='baseline-verification':consumers=['V636-P08-T03']
  if c['kind']=='review-leaf':consumers=['V636-P10-T01' if c['command_id'].startswith('A_') else 'V636-P10-T02']
  if c['command_id'] in ['A_INSTALL_NODE','B_INSTALL_NODE','A_INSTALL_PYTHON','B_INSTALL_PYTHON']:consumers=['V636-P10-T01' if c['command_id'].startswith('A_') else 'V636-P10-T02']
  inputs=[];out=[];directories=[]
  argv=c['argv'];skipcode=argv.index('-c')+1 if '-c' in argv else -1
  for i,s in enumerate(argv):
   if i==skipcode or s.startswith('-') or not re.search(r'\.(?:py|ts|js|json|toml|yaml|md|zip|sha256)$',s):continue
   effective_cwd=c['cwd']+'/extension' if '--dir' in argv and s.startswith('tsconfig.') else c['cwd']
   f=logical(s,effective_cwd);prev=argv[i-1] if i else ''
   isout=prev in output_flags or prev=='--receipt' and c['kind'] not in ['review-leaf'] and '--check-only' not in argv
   if c['kind']=='review-leaf':isout=False
   if c['command_id'].startswith('BOOT0') and prev in ['--zip','--sidecar']:isout=False
   (out if isout else inputs).append(f)
   if f not in artifacts:unknown.append((c['command_id'],f))
  io.append({'command_id':c['command_id'],'consumers':consumers,'inputs':sorted(set(inputs)),'outputs':sorted(set(out)),'input_directories':directories})
 binding_inputs=['authoring-tools/build_task_command_registry.py','pack/docs/tasks/task-manifest.v6.3.6.json','pack/docs/registries/task-command-registry.v1.json',*['pack/docs/configs/'+name for name in REVIEW_CONFIGS]]
 for row in io:
  if row['command_id'] in ['VERIFY_V636_MIG0_T05','V636_MIG0_T07_BINDINGS','V636_MIG0_T08_BINDINGS']:
   row['inputs']=binding_inputs
   row['outputs']=binding_outputs
   row['input_directories']=['pack/docs/configs']
  if row['command_id']=='TEST_V636_P01_T06':
   row['inputs']=sorted(set(row['inputs']+P01_GATE_INPUTS))
 for t in ts:
  refs=t['exact_files']+[s.split('::')[0].split('#')[0] for s in t['exact_symbols']]+t['tests_first']+[s.split('#')[0] for s in t['exact_schema_refs']]
  for f in refs:
   f=logical(f.split('::')[0].split('#')[0])
   if f.startswith('bootstrap/'):f='plan-input/'+f
   if f in artifacts:artifacts[f]['consumers'].append(t['task_id'])
   else:unknown.append((t['task_id'],f))
 for row in io:
  for f in row['inputs']:
   if f in artifacts:artifacts[f]['consumers']+=row['consumers']
 for e in artifacts.values():e['consumers']=sorted(set(e['consumers']),key=lambda x:order[x])
 dump('docs/registries/artifact-ownership.v1.json',{'schema_version':'artifact-ownership/v2','entries':sorted(artifacts.values(),key=lambda x:x['path'])})
 dump('docs/registries/command-io.v1.json',{'schema_version':'command-io/v1','commands':io})
 candidate=candidate_ids
 dump('docs/registries/verification-topology.v1.json',{'schema_version':'verification-topology/v1','candidate_command_ids':candidate,'excluded_kinds':['operation','migration','bootstrap','plan-check','review-operation','review-leaf','crash-child'],'required_groups':['bootstrap','authoring','materialization','contracts','durability','clock','review','security','release','seal','test-harness'],'group_sources':{'bootstrap':['plan-input/bootstrap/test_bootstrap_tools.py'],'authoring':['authoring-tests'],'materialization':['runtime/tests/materialization'],'contracts':['runtime/tests/contracts'],'durability':['runtime/tests/durability'],'clock':['runtime/tests/clock','runtime/extension/test/clock'],'review':['runtime/tests/review'],'security':['runtime/tests/security','runtime/extension/test/security'],'release':['runtime/tests/release'],'seal':['runtime/tests/seal'],'test-harness':['runtime/extension/test-harness']},'harness_compile_command':'COMPILE_CRASH_HARNESS','all_test_compile_command':'COMPILE_ALL_TESTS','source_freeze_task':'V636-P06-T03'})
 dump('docs/registries/task-command-registry.v1.json',{'schema_version':'command-registry/v1','commands':list(cmd.values())})
 m['declared_task_count']=len(ts);dump('docs/tasks/task-manifest.v6.3.6.json',m)
 print(json.dumps({'tasks':len(ts),'artifacts':len(artifacts),'commands':len(all_commands),'unresolved':unknown},indent=2))
 if unknown:raise SystemExit(1)

if __name__=='__main__':main()
