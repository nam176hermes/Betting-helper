from pathlib import Path
from collections import Counter
import copy
import hashlib
import json
import struct
import subprocess
import tempfile
import unittest
import zipfile
import sys
import shutil
import ast
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jsonschema import Draft202012Validator
from plan_tools.check_plan import check, validate, cross_contracts
from plan_tools.common import encoded, governed_root, sha, verify_manifest
from plan_tools.seal_plan import archive_bytes
from bootstrap.extract_plan import extract
from bootstrap.verify_extracted_plan import verify_extracted_plan
from bootstrap.create_authoring_workspace import create_authoring_workspace
from bootstrap.initialize_authoring_repository import initialize
P=Path(__file__).resolve().parents[1]

def load():
    j=lambda n:json.loads((P/n).read_text())
    commands=sum((j('docs/registries/'+n)['commands'] for n in ['task-command-registry.v1.json','review-command-registry.v1.json','cybersecurity-command-registry.v1.json','baseline-replay-command-registry.v1.json']),[])
    return [j('docs/tasks/task-manifest.v6.3.6.json'),commands,j('docs/registries/artifact-ownership.v1.json'),j('docs/registries/command-io.v1.json'),j('docs/registries/proof-coverage-matrix.v1.json'),j('docs/configs/review-a.v1.json'),j('docs/registries/review-command-registry.v1.json'),(P/'bootstrap/extract_plan.py').read_text()]

def fixture(root):
    root.mkdir();(root/'docs/registries').mkdir(parents=True)
    (root/'README.md').write_text('Inert bootstrap fixture\n')
    (root/'docs/registries/seed-artifacts.v1.json').write_bytes(encoded({'entries':[{'source':'README.md','destination':'pack/README.md'}]}))
    entries=[{'path':f.relative_to(root).as_posix(),'size':f.stat().st_size,'sha256':sha(f.read_bytes())} for f in root.rglob('*') if f.is_file()]
    (root/'MANIFEST_SHA256.json').write_bytes(encoded({'entries':entries}))

class PlanContractTests(unittest.TestCase):
    def test_cross_contract_regressions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'plan';shutil.copytree(P,root)
            cross_contracts(root)
            cases=[
                ('docs/registries/artifact-ownership.v1.json',lambda x:next(e for e in x['entries'] if e['path']=='runtime/tests/bootstrap/test_repository_baseline.py')['modifying_tasks'].remove('V636-MIG0-T03'),'E_MIGRATION_MODIFIER'),
                ('docs/registries/artifact-ownership.v1.json',lambda x:next(e for e in x['entries'] if e['path']=='runtime/extension/.test-build/test-harness/indexeddb-crash-child.js')['modifying_tasks'].remove('V636-P03-T02'),'E_STALE_HARNESS_OWNER'),
                ('docs/tasks/task-manifest.v6.3.6.json',lambda x:next(t for t in x['tasks'] if t['task_id']=='V636-P03-T02')['exact_command_ids'].reverse(),'E_STALE_HARNESS_ORDER'),
                ('docs/registries/task-command-registry.v1.json',lambda x:next(c for c in x['commands'] if c['command_id']=='TEST_SECURITY_TS').update(argv=['node','--test','extension/.test-build/test/security']),'E_SECURITY_ARGV'),
                ('docs/schemas/review-launch-authorization.schema.json',lambda x:x['$defs']['ReviewLaunchAuthorization']['properties']['workspace_root'].update(pattern=r'^/home/thenam176/betting-helper/review-workspaces/hybrid-discovery-v6\.3\.2/review-[ab]$'),'E_REVIEW_PATH_SCHEMA'),
                ('docs/configs/review-a.v1.json',lambda x:x['input_mounts'].pop(),'E_REVIEW_SEAL_MOUNT'),
                ('docs/registries/review-command-registry.v1.json',lambda x:next(c for c in x['commands'] if c['command_id']=='A_CHECK_EVIDENCE')['argv'].__delitem__(slice(-6,None)),'E_REVIEW_SEAL_ARGV'),
                ('docs/registries/proof-coverage-matrix.v1.json',lambda x:next(r for r in x['entries'] if r['stage']=='SEALED').update(sealed_evidence_path='evidence/V636-P09-T02.json'),'E_SEALED_EVIDENCE_SOURCE'),
                ('docs/registries/task-command-registry.v1.json',lambda x:next(c for c in x['commands'] if c['command_id']=='TEST_RELEASE_TOOLS').update(argv=['uv','run','--frozen','pytest','-q','tests/release','tests/seal']),'E_PREMATURE_RELEASE_COLLECTION'),
                ('docs/registries/inherited-baseline-qualification.v1.json',lambda x:x['historical_reads'][0].update(plan_source='docs/schemas/meta-records.schema.json'),'E_INHERITED_READ_BINDING'),
                ('docs/tasks/task-manifest.v6.3.6.json',lambda x:next(t for t in x['tasks'] if t['task_id']=='V636-MIG0-T05')['outputs'].remove('runtime/review-config/review-authority.v1.json'),'E_MIG0_BINDING_TASK'),
                ('docs/registries/command-io.v1.json',lambda x:next(r for r in x['commands'] if r['command_id']=='V636_MIG0_T07_BINDINGS')['outputs'].remove('runtime/review-config/review-authority.v1.json'),'E_MIG0_BINDING_IO'),
                ('docs/registries/inherited-baseline-qualification.v1.json',lambda x:x['python_files'][0]['tests'].pop(),'E_INHERITED_TEST_COVERAGE'),
                ('docs/registries/artifact-ownership.v1.json',lambda x:next(e for e in x['entries'] if e['path']=='runtime/tests/bootstrap/test_repository_baseline.py')['modifying_tasks'].remove('V636-P05-T09'),'E_INHERITED_ADAPTATION_OWNER'),
                ('docs/registries/version-rebinding.v1.json',lambda x:x['final_legacy_policy'].update(initial_hashes_apply_only_at='V636-MIG0-T06'),'E_MIGRATION_STAGE_HASH'),
                ('docs/tasks/task-manifest.v6.3.6.json',lambda x:next(t for t in x['tasks'] if t['task_id']=='V636-P05-T09')['exact_command_ids'].remove('COMPILE_PRODUCTION'),'E_PRODUCTION_BUILD_COMMAND'),
                ('docs/tasks/task-manifest.v6.3.6.json',lambda x:next(t for t in x['tasks'] if t['task_id']=='V636-P08-T03')['exact_command_ids'].pop(0),'E_BASELINE_ENVIRONMENT_ORDER'),
                ('docs/configs/review-a.v1.json',lambda x:x['node_environment']['dependency_mounts'].clear(),'E_REVIEW_NODE_PROJECTION'),
            ]
            for name,mutate,error in cases:
                with self.subTest(error=error):
                    f=root/name;original=f.read_bytes();data=json.loads(original);mutate(data);f.write_text(json.dumps(data))
                    try:
                        with self.assertRaisesRegex(ValueError,error):cross_contracts(root)
                    finally:f.write_bytes(original)

    def test_exact_node_security_argv_executes_all_files(self):
        registry=json.loads((P/'docs/registries/task-command-registry.v1.json').read_text())
        argv=next(c['argv'] for c in registry['commands'] if c['command_id']=='TEST_SECURITY_TS')
        self.assertEqual(subprocess.check_output(['node','--version'],text=True).strip(),'v22.23.0')
        with tempfile.TemporaryDirectory() as d:
            for i,name in enumerate(argv[2:]):
                f=Path(d)/name;f.parent.mkdir(parents=True,exist_ok=True)
                f.write_text("require('node:test')('registered-"+str(i)+"', () => {});\n")
            result=subprocess.run(argv,cwd=d,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('# tests 6',result.stdout)
            broken=subprocess.run(['node','--test','extension/.test-build/test/security'],cwd=d,capture_output=True,text=True)
            self.assertNotEqual(broken.returncode,0)
            self.assertIn('MODULE_NOT_FOUND',broken.stdout+broken.stderr)

    def test_historical_test_reads_actual_mapped_fixture(self):
        # Execute the original historical authority assertions with only the declared read relocation.
        registry=json.loads((P/'docs/registries/inherited-baseline-qualification.v1.json').read_text())
        symbol='test_plan_manifest_authoring_and_sealing_authority_are_fail_closed'
        source=Path('/home/thenam176/betting-helper/discovery-runtime/tests/bootstrap/test_repository_baseline.py')
        function=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name==symbol)
        bindings=[r for r in registry['historical_reads'] if r['symbol']==symbol]
        with tempfile.TemporaryDirectory() as d:
            vendor=Path(d)
            for row in bindings:
                f=vendor/row['runtime_vendor_relative'];f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes((P/row['plan_source']).read_bytes())
            namespace={'json':json,'PACK_ROOT':vendor,'Draft202012Validator':Draft202012Validator,'deepcopy':copy.deepcopy}
            module=ast.Module(body=[function],type_ignores=[])
            exec(compile(module,str(source),'exec'),namespace)
            with self.assertRaises(FileNotFoundError):namespace[symbol]()
            replacements={r['old_operand']:r['runtime_vendor_relative'] for r in bindings}
            for node in ast.walk(module):
                if isinstance(node,ast.Constant) and isinstance(node.value,str):node.value=replacements.get(node.value,node.value)
            exec(compile(module,str(source),'exec'),namespace)
            namespace[symbol]()

    def test_current_plan(self):
        self.assertEqual(check(P)['result'],'PASS')

    def test_schema_instances(self):
        for sf,df,ref in [('task-card-v6.3.6.schema.json','docs/tasks/task-manifest.v6.3.6.json','TaskManifestV636'),('command-registry.schema.json','docs/registries/task-command-registry.v1.json','CommandRegistry'),('artifact-ownership.schema.json','docs/registries/artifact-ownership.v1.json','ArtifactOwnershipRegistry'),('proof-coverage.schema.json','docs/registries/proof-coverage-matrix.v1.json','ProofCoverageMatrix')]:
            s=json.loads((P/'docs/schemas'/sf).read_text());s['$ref']='#/$defs/'+ref
            Draft202012Validator.check_schema(s);Draft202012Validator(s).validate(json.loads((P/df).read_text()))

    def test_semantic_counterexamples(self):
        cases={
          'production':lambda x:x[0].update(authorized_production_phases='PAPER'),
          'unknown':lambda x:x[0]['tasks'][1].update(dependencies=['UNKNOWN']),
          'future':lambda x:x[0]['tasks'][0].update(dependencies=[x[0]['tasks'][-1]['task_id']]),
          'empty rollback':lambda x:x[0]['tasks'][1].update(rollback=[]),
          'blank rollback':lambda x:x[0]['tasks'][1].update(rollback=[' ']),
          'count':lambda x:x[0].update(declared_task_count=63),
          'lifecycle regression':lambda x:x[0]['tasks'][1].update(lifecycle_from='SEALED',lifecycle_to='DECLARED'),
          'unowned':lambda x:x[0]['tasks'][4]['exact_files'].append('runtime/unowned.py'),
          'future evidence':lambda x:next(row for row in x[4]['entries'] if row['stage']=='REVIEWED').update(stage='CANDIDATE'),
          'recursive review':lambda x:x[5].update(mechanical_command_ids=['REVIEW_A_MECHANICAL']),
        }
        for name,mutate in cases.items():
            with self.subTest(name=name):
                x=load();mutate(x)
                with self.assertRaises(ValueError):validate(*x)
        for arg in ['TODO','TBD','FIXME','PLACEHOLDER','${COMMAND}','$(echo x)','...','<command>','`id`']:
            with self.subTest(argv=arg):
                x=load();x[1][0]['argv']=[arg]
                with self.assertRaisesRegex(ValueError,'E_COMMAND_PLACEHOLDER'):validate(*x)
        x=load();next(e for e in x[2]['entries'] if e['path']=='runtime/tools/inspect_restart_state.py')['creation_owner']='V636-P09-T04'
        with self.assertRaisesRegex(ValueError,'E_CONSUMER_BEFORE_OWNER'):validate(*x)
        for mutate,error in [
            (lambda x:next(e for e in x[2]['entries'] if e['path']=='runtime/tools/inspect_restart_state.py').update(creation_owner=' '),'E_OWNER_UNKNOWN'),
            (lambda x:next(e for e in x[2]['entries'] if e['path']=='runtime/tools/inspect_restart_state.py').update(creation_owner='V636-P99-T01'),'E_OWNER_UNKNOWN'),
            (lambda x:next(e for e in x[2]['entries'] if e['path']=='runtime/tools/inspect_restart_state.py').update(creation_owner=None,source={}),'E_OWNER_SOURCE'),
        ]:
            x=load();mutate(x)
            with self.assertRaisesRegex(ValueError,error):validate(*x)

    def test_inherited_schema_pointer_normalization(self):
        from plan_tools.normalize_inherited_schemas import normalized
        docs,changes=normalized()
        self.assertEqual(len(changes),476)
        for name,expected in docs.items():
            actual=json.loads((P/'docs/inherited/v6.2/schemas'/name).read_text())
            self.assertEqual(actual,expected)

    def test_command_schema_rejects_placeholders(self):
        s=json.loads((P/'docs/schemas/command-registry.schema.json').read_text());s['$ref']='#/$defs/CommandRegistry';v=Draft202012Validator(s)
        d=json.loads((P/'docs/registries/task-command-registry.v1.json').read_text())
        for token in ['TODO','TBD','${COMMAND}','...','<command>']:
            mutated=copy.deepcopy(d);mutated['commands'][0]['argv']=[token];self.assertFalse(v.is_valid(mutated))

    def test_ready_yes_scope_no(self):
        s=json.loads((P/'docs/schemas/review-result.schema.json').read_text());props=s['$defs']['ImplementationReviewResult']['properties']['verdicts']['properties']
        verdicts={k:'NONE' if k=='AUTHORIZED_PRODUCTION_PHASES' else 'NO' if k=='SAFE_TO_FREEZE_SCOPE0' else 'YES' for k in props}
        d={'schema_version':'independent-review-result/v1','review_role':'IMPLEMENTATION_READINESS_REVIEWER','review_outcome':'PASS','findings':[],'pack_zip_sha256':'1'*64,'repo0_receipt_sha256':'2'*64,'review_run_id':'synthetic-positive','verdicts':verdicts,'authorized_production_phases':'NONE','content_hash':'3'*64}
        Draft202012Validator(s).validate(d)
        self.assertTrue(any('REVIEW-READY-YES-SCOPE0-NO' in t['positive_vectors'] for t in load()[0]['tasks']))

    def test_root_algorithm_and_deterministic_zip(self):
        data={'a.txt':b'a','b.txt':b'hello'};chunks=[]
        for path,b in data.items():
            name=path.encode();leaf=hashlib.sha256(b'HYBRID-DISCOVERY/v6.3.6/GOVERNED-FILE/v1\0'+name+b'\0'+hashlib.sha256(b).digest()).digest();chunks.append(struct.pack('>I',len(name))+name+leaf)
        expected=hashlib.sha256(b'HYBRID-DISCOVERY/v6.3.6/GOVERNED-ROOT/v1\0'+b''.join(chunks)).hexdigest()
        self.assertEqual(governed_root(data),expected)
        self.assertEqual(archive_bytes(data),archive_bytes(dict(reversed(list(data.items())))))

    def test_manifest_rejects_extra_missing_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'plan';fixture(root);verify_manifest(root)
            extra=root/'unexpected.py';extra.write_text('inert')
            with self.assertRaises(ValueError):verify_extracted_plan(root,Path(d)/'receipt.json')
            extra.unlink();extra.symlink_to(root/'README.md')
            with self.assertRaises(ValueError):verify_manifest(root)
            extra.unlink();(root/'README.md').unlink()
            with self.assertRaises(ValueError):verify_manifest(root)

    def test_safe_extract_and_reject_existing_destination(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);root=d/'source';fixture(root);data={f.relative_to(root).as_posix():f.read_bytes() for f in root.rglob('*') if f.is_file()}
            z=d/'plan.zip';z.write_bytes(archive_bytes(data));side=d/'plan.zip.sha256';side.write_text(sha(z.read_bytes())+'  plan.zip\n');dest=d/'extract';extract(z,dest,side);verify_manifest(dest)
            with self.assertRaises(ValueError):extract(z,dest,side)
            bad=d/'bad.zip'
            with zipfile.ZipFile(bad,'w') as archive:archive.writestr('../escape',b'bad')
            side.write_text(sha(bad.read_bytes())+'  bad.zip\n')
            with self.assertRaises(ValueError):extract(bad,d/'bad-extract',side)
            self.assertFalse((d/'escape').exists())

    def test_workspace_seed_and_post_receipt_clean_git(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);root=d/'source';fixture(root);author=d/'author';create_authoring_workspace(root,author,author/'.bootstrap/authoring-workspace-receipt.json')
            self.assertEqual((author/'pack/README.md').read_bytes(),(root/'README.md').read_bytes())
            receipt=d/'external/git-receipt.json';r=initialize(author,receipt)
            self.assertEqual(r['status'],'');self.assertEqual(subprocess.check_output(['git','status','--porcelain=v1'],cwd=author,text=True),'')
            with self.assertRaises(ValueError):create_authoring_workspace(root,author,author/'.bootstrap/authoring-workspace-receipt.json')

if __name__=='__main__':unittest.main()
