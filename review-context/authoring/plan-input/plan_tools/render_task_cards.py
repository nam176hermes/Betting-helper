"""Render human task cards from the authoritative task manifest and argv registry."""
from pathlib import Path
import json
P=Path(__file__).resolve().parents[1]
NAMES={'BOOT0':'boot0-authoring-workspace-bootstrap.md','MIG0':'mig0-successor-rebinding.md','P00':'p00-authority-and-source-freeze.md','P01':'p01-complete-artifact-materialization.md','P02':'p02-materialized-contract-validation.md','P03':'p03-process-level-durability-qualification.md','P04':'p04-clock-vector-qualification.md','P05':'p05-review-security-and-release-tooling.md','P06':'p06-executable-reference-validation.md','P07':'p07-candidate-qualification.md','P08':'p08-zero-parent-baseline-export.md','P09':'p09-acyclic-sealing.md','P10':'p10-dual-independent-review-and-aggregation.md'}

def main():
    m=json.loads((P/'docs/tasks/task-manifest.v6.3.6.json').read_text());ts=m['tasks']
    for phase,file in NAMES.items():
        lines=['# '+phase+' task contracts','','Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.']
        for t in ts:
            if t['phase']!=phase:continue
            lines+=['','## '+t['task_id']+' — '+t['title'],'',t['objective'],'','Authority: '+t['authority']+'. Lifecycle applies to this task’s artifacts: '+t['lifecycle_from']+' → '+t['lifecycle_to']+'.']
            for key,label in [('dependencies','Dependencies'),('preconditions','Preconditions'),('inputs','Inputs'),('outputs','Outputs'),('exact_files','Exact files'),('exact_symbols','Exact symbols'),('exact_schema_refs','Schema pointers'),('exact_command_ids','Exact command IDs'),('tests_first','Tests'),('positive_vectors','Positive vectors'),('negative_vectors','Negative vectors'),('implementation_steps','Steps'),('acceptance_criteria','Acceptance criteria'),('evidence_artifacts','External evidence'),('rollback','Rollback boundary')]:
                lines+=['','### '+label,'']+[('- `'+x+'`') if key in ['dependencies','outputs','exact_files','exact_symbols','exact_schema_refs','exact_command_ids','tests_first','positive_vectors','negative_vectors','evidence_artifacts'] else '- '+x for x in t[key]]
                if not t[key]:lines+=['None; this task consumes previously created artifacts.']
            lines+=['','Stop: '+t['stop_condition'],'','Commit policy: '+t['commit_message']+'. Production authority: NONE.']
        (P/'docs/plans'/file).write_text('\n'.join(lines)+'\n')
    cmds=json.loads((P/'docs/registries/task-command-registry.v1.json').read_text())['commands'];by={c['command_id']:c for c in cmds}
    lines=['# BOOT0 — exact bootstrap inputs and commands','','Before execution the human must supply this plan ZIP and its SHA-256 sidecar under /home/thenam176/betting-helper/inputs. Both names are frozen below. The predecessor is retained under docs/sources solely as provenance; it is not executed.','','Prerequisites: /usr/bin/python3.12; git; jsonschema==4.26.0 and pytest available to the verifier; the pinned local v6.2 runtime source and its offline dependency caches. Missing prerequisite is HOLD, never an implicit network install. BOOT0 uses only stdlib until the plan schema tests. Initial local Git creation requires explicit authorization during implementation. No authoring-root command executes before BOOT0_CREATE_WORKSPACE.','','Run in this task/command order, using cwd and argv directly (no shell interpolation). Extraction uses the exact bundled stdlib extractor inline before an extracted script is trusted; it verifies ZIP/sidecar/manifest closure and rejects existing destinations.']
    for t in ts:
        if t['phase']!='BOOT0':continue
        for cid in t['exact_command_ids']:
            c=by[cid];lines+=['','## '+cid,'','```json',json.dumps({'cwd':c['cwd'],'argv':c['argv']},indent=2),'```']
    (P/'BOOTSTRAP.md').write_text('\n'.join(lines)+'\n')
    lines=['# Implementation plan v6.3.6','','Scope: repair/implement the declared successor contract tooling only after independent review and explicit human task authorization. This authoring run implements no discovery runtime.','','## Exact dependency order','','| Task | Dependencies | Outcome |','|---|---|---|']
    for t in ts:lines+=['| '+t['task_id']+' | '+', '.join(t['dependencies'])+' | '+t['title']+' |']
    lines+=['','## Gate rules','','DECLARATION_COMPLETE -> MATERIALIZATION_COMPLETE -> MATERIALIZED_CONTRACTS_VALID -> EXECUTABLE_REFERENCE_COMPLETE -> CANDIDATE qualification -> zero-parent export -> SEALED -> EXTERNAL_REVIEWED. MIG0-T07 and MIG0-T08 are explicit synchronization tasks, not implicit repeated phases.','','CANDIDATE evidence never consumes seal or review output. Runtime source stops changing at P06-T03; normative/config bindings freeze at MIG0-T08. Later source drift requires a new candidate cycle.','','## Inventory','',f'Tasks: {len(ts)}. Task/bootstrap commands: {len(cmds)}. Crash cases: 46. Clock named vectors: 65; mapping negatives: 16. Separate review/security registries contain the remaining leaf/launch commands.','','## Current authority','','PLAN_AUTHORED: YES\n\nINDEPENDENT_PLAN_REVIEW: PENDING\n\nREADY_TO_IMPLEMENT_DISCOVERY_PACK: NO\n\nAUTHORIZED_PRODUCTION_PHASES: NONE']
    (P/'IMPLEMENTATION_PLAN_V6_3_6.md').write_text('\n'.join(lines)+'\n')
    print('rendered',len(ts),'task cards')

if __name__=='__main__':main()
