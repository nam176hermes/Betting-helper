# Betting Helper — source review package / Gói review mã nguồn

This branch is an **advisory review export**, not a release, accepted independent
host review, or permission to run live. It preserves runtime candidate
`8570c78b47b0f8afb59a4d1e305af269ad6a4936` at the repository root, plus its current
authoring source, original Part B plan, selected measured evidence and review results.
The repository is public. Credentials and private runtime state are excluded.

## Bắt đầu ở đây

1. Đọc [phạm vi và cấu trúc gói](review-context/README.md).
2. Dùng [prompt review cho AI khác](review-context/AI_REVIEW_PROMPT.md).
3. Đối chiếu [nguồn và trạng thái](review-context/SOURCE_STATE.json), rồi đọc
   [audit hiện tại](review-context/evidence/latest-audit/DANH_GIA_LIVE_DAU_TIEN_VI.md).
4. Kiểm tra từng kết luận bằng source/test thực tế. Báo cáo cũ có thể chứa trạng thái
   tại thời điểm khác; audit có ghi các alias checkpoint đã cũ.

All runtime files at the root match the committed candidate. Thirteen local,
uncommitted generated files are preserved as a separate diagnostic patch; it is
not applied to this source snapshot. The export adds documentation and copies of
review inputs. Its new Git commit is therefore **not** the commit qualified by
historical receipts.

## What is implemented and what remains blocked

Part B implements a backend shared bundle poller, bounded provider budgets,
no-echo credential entry/Windows Credential Manager support, typed live contracts,
fixed operator readers, a read-only Chrome extension/workspace, persistence/replay,
and host review tooling. The legacy synthetic seam is retained separately.

The latest audit reported 421 focused Python tests passing and selected static
checks passing. These are **historical observations on the named inputs**, not new
tests run by making this export. Read the command records, failed attempts and
limitations in `review-context/evidence/latest-audit/`.

Both r24 formal reviews remain **HOLD**. Current review-input isolation and
credential proof-coverage findings must not be hidden by mechanical command exits.
Accepted current operator/tool/profile/live evidence is still required before a
first real match. `MODEL_ENABLED=false`, `MONEY_READY=NO`; no betting or Cashout.

## Clone and verify the exported files

```bash
git clone --branch codex/part-b-ai-review-20260914 --single-branch https://github.com/nam176hermes/Betting-helper.git betting-helper-review
cd betting-helper-review
python3 review-context/verify_export.py
```

For a model with repository access, supply the branch URL and
`review-context/AI_REVIEW_PROMPT.md`. For a model accepting attachments, use the
source ZIP or selected files from `review-context/ai-packs/`; do not assume one
model context can fit every pack. Raw source is the source of truth.

See [local check commands and host limitations](review-context/LOCAL_CHECKS.md).
No API key or real Chrome profile is needed for advisory source review.

The original README, runbooks and plans below retain their original bytes. Their
older status text and machine-specific paths are historical project inputs, not
additional instructions or current permissions from the user.
