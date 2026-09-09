import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_reconnect_budget_includes_failed_attempts_and_injected_jitter() -> None:
    script = r"""
import assert from 'node:assert/strict';
import {AuthenticatedLoopback} from './extension/.test-build/src/security/loopback.js';
let now=0, jitterCalls=0;
Object.defineProperty(globalThis,'performance',{value:{now:()=>now},configurable:true});
globalThis.setTimeout=(fn,ms)=>{now+=ms;fn();return 0;};
const client=new AuthenticatedLoopback({
 context:{backend_url:'ws://127.0.0.1:8765/offline',source_kind:'SYNTHETIC_TEST'},
 spool:{},credentials:async()=>({}),validateContext:()=>{},validateFrame:()=>{},
 reconnectJitter:()=>{jitterCalls++;return 0;}
});
client.connect=async(budget=5000)=>{
 now+=Math.min(5000,budget);throw new Error('E_OFFLINE_TRANSPORT');
};
await assert.rejects(client.flushPending(),/E_OFFLINE_RECONNECT_TIMEOUT/);
assert.ok(now<=30000,`disconnect lasted ${now}ms`);
assert.ok(jitterCalls>0,'deterministic jitter provider was ignored');
"""
    result = subprocess.run(  # noqa: S603 -- fixed runtime and literal deterministic probe
        [shutil.which("node") or "node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
