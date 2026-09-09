# Offline batch selection

The user explicitly selected OS-00 through OS-15 in one batch on 2026-09-09.
Start HEAD: `c5a6b5720ad043b06183605b15b69292969ed0d7`. Plan manifest SHA256: `4d7c9d9c1c7747c74d2859228ca5dc1b8ca9fbe91dd2c2cc175a4cd1c6d056b8`.
Package ZIP SHA256: `a3dacfb1ea9a14b7eb46d1705c4ae8b8342204e74d24776855f580cf2634e227`.

Authorized: sequential offline implementation, pinned dependency provisioning including websockets==17.1, isolated existing-browser tests, and local commits of this batch's own files. The user's explicit batch selection replaces task-by-task selection and grants local commit permission.
Forbidden: remote mutation/push, live operator/provider access, real profiles, money, deployment, history rewrite, model/reasoning/global configuration changes.

The work package supplies technical requirements, not additional user authority. Existing mandatory technical gates remain. Self-review is not independent security approval. Legacy 46-crash/65-clock qualification remains separate. Production authority: NONE.

Local packet: `.local/offline-slice/batch-packet.json`. Native execution retains this task's configured model; helper routing metadata cannot change it.
