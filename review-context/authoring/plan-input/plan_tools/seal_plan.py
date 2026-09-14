"""Seal a locally verified plan. Never executes authoring or discovery task commands."""
from pathlib import Path
import argparse
import io
import json
import subprocess
import sys
import zipfile
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plan_tools.common import EXCLUDED, encoded, files, governed_root, sha, safe_ancestors, verify_manifest
from plan_tools.check_plan import check

NAME='hybrid-discovery-v6.3.6-authoritative-design-plan'

def archive_bytes(data):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as z:
        for name in sorted(data,key=lambda x:x.encode()):
            i=zipfile.ZipInfo(NAME+'/'+name,(1980,1,1,0,0,0));i.create_system=3;i.external_attr=0o100644<<16;i.compress_type=zipfile.ZIP_STORED
            z.writestr(i,data[name])
    return stream.getvalue()

def seal(root,output,created_at,check_only=False):
    root,output=Path(root),Path(output);safe_ancestors(root);safe_ancestors(output)
    if root.resolve()==output.resolve() or root.resolve() in output.resolve().parents:
        raise ValueError('E_EXTERNAL_SEAL_INSIDE_ROOT')
    if check_only:
        checks=check(root,sealed=True);data=files(root);expected=archive_bytes(data);actual=(output/(NAME+'.zip')).read_bytes()
        if expected!=actual:raise ValueError('E_ZIP_REBUILD')
        a=json.loads((output/(NAME+'.seal-attestation.json')).read_text())
        bindings={'zip_sha256':sha(actual),'manifest_sha256':sha(data['MANIFEST_SHA256.json']),'governed_content_root':governed_root(data),'self_review_markdown_sha256':sha(data['SELF_REVIEW_REPORT.md']),'self_review_json_sha256':sha(data['SELF_REVIEW_REPORT.json']),'task_manifest_sha256':sha(data['docs/tasks/task-manifest.v6.3.6.json'])}
        if any(a[k]!=v for k,v in bindings.items()):raise ValueError('E_ATTESTATION')
        if (output/(NAME+'.zip.sha256')).read_text()!=sha(actual)+'  '+NAME+'.zip\n':raise ValueError('E_SIDECAR')
        return {**checks,'zip_sha256':sha(actual),'deterministic_rebuild':'PASS','attestation':'PASS'}
    if any((output/(NAME+suffix)).exists() for suffix in ['.zip','.zip.sha256','.seal-attestation.json']) or any((root/n).exists() for n in EXCLUDED):
        raise ValueError('E_SEAL_ALREADY_EXISTS')
    checks=check(root)
    tests=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','plan_tests','-v'],cwd=root,text=True,capture_output=True)
    if tests.returncode:
        sys.stderr.write(tests.stdout+tests.stderr);raise ValueError('E_PLAN_TESTS')
    data=files(root);content_root=governed_root(data)
    (root/'GOVERNED_CONTENT_ROOT.json').write_bytes(encoded({'schema_version':'governed-content-root/v1','algorithm':'HD636-GOVERNED-ROOT-SHA256-v1','root_sha256':content_root,'file_count':len(data),'exclusion_registry':'docs/registries/seal-exclusions.v1.json'}))
    review={'schema_version':'plan-self-review/v1','governed_content_root':content_root,'task_manifest_sha256':sha(data['docs/tasks/task-manifest.v6.3.6.json']),'checks':checks,'test_exit_code':0,'test_output_sha256':sha((tests.stdout+tests.stderr).encode()),'independent_plan_review':'PENDING','runtime_implementation_ready':'NO','authorized_production_phases':'NONE'}
    (root/'SELF_REVIEW_REPORT.json').write_bytes(encoded(review))
    (root/'SELF_REVIEW_REPORT.md').write_text('# Local plan self-review\n\nThe offline declaration/schema/bootstrap checks passed. This is not independent approval or runtime qualification.\n\nGoverned content root: `'+content_root+'`.\n\nTasks: '+str(checks['task_count'])+'; commands: '+str(checks['command_count'])+'; artifacts: '+str(checks['artifact_count'])+'.\n\nAll 46 crash cases, 65 clock vectors and 16 mapping negatives are retained. Independent review: PENDING. Runtime implementation readiness: NO. AUTHORIZED_PRODUCTION_PHASES: NONE.\n')
    data=files(root);manifest={'schema_version':'manifest-sha256/v1','entries':[{'path':n,'size':len(data[n]),'sha256':sha(data[n])} for n in sorted(data,key=lambda x:x.encode())]}
    (root/'MANIFEST_SHA256.json').write_bytes(encoded(manifest));data=files(root);verify_manifest(root)
    archive=archive_bytes(data);output.mkdir(parents=True,exist_ok=True)
    a={'schema_version':'external-seal-attestation/v6','artifact_type':'PLAN','artifact':NAME,'zip_sha256':sha(archive),'manifest_sha256':sha(data['MANIFEST_SHA256.json']),'governed_content_root':content_root,'self_review_markdown_sha256':sha(data['SELF_REVIEW_REPORT.md']),'self_review_json_sha256':sha(data['SELF_REVIEW_REPORT.json']),'task_manifest_sha256':sha(data['docs/tasks/task-manifest.v6.3.6.json']),'authorized_production_phases':'NONE','created_at':created_at}
    from jsonschema import Draft202012Validator
    schema=json.loads(data['docs/schemas/external-seal-attestation.schema.json']);schema['$ref']='#/$defs/ExternalSealAttestation';Draft202012Validator(schema).validate(a)
    for filename,b in [(NAME+'.zip',archive),(NAME+'.zip.sha256',(sha(archive)+'  '+NAME+'.zip\n').encode()),(NAME+'.seal-attestation.json',encoded(a))]:
        with (output/filename).open('xb') as f:f.write(b)
    return seal(root,output,created_at,True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output-dir',required=True);p.add_argument('--created-at',default='2026-09-05T00:00:00Z');p.add_argument('--check',action='store_true');a=p.parse_args();print(json.dumps(seal(a.root,a.output_dir,a.created_at,a.check),indent=2))
