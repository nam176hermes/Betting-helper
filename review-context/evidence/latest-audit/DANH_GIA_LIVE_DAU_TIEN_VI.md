# Đánh giá Part B và đường ngắn nhất đến trận live đầu tiên

Ngày đánh giá: 13/09/2026 America/Toronto, 14/09/2026 UTC.
Đây là audit của implementation coordinator, không phải Review A/B độc lập hoặc quyền chạy live.

## Kết luận

Phần ứng dụng đã có backend, extension, Side Panel/workspace, lưu trữ/replay và kho key Windows. Không cần xây lại UI hoặc backend. Nhưng hai HOLD gần nhất chưa mô tả hết điều kiện cản trận live đầu tiên. Audit này phát hiện thêm lỗi thứ tự xác minh/intent, sự lặp tải bằng chứng, checkpoint lỗi thời và thiếu bản cài hiện tại.

Không có cơ sở để cho tỷ lệ hoàn thiện 90–99%: số lượng test PASS không đo được khả năng đọc DOM Mise-o-jeu thật. Trạng thái chính xác là: mã ứng dụng có kiểm thử tốt ở phạm vi đã thực thi; candidate có bằng chứng mock/platform/qualification; đường operator thực tế và admission live chưa được chứng minh.

## Phạm vi và căn cứ

- Runtime đang dùng: `/home/thenam176/betting-helper/part-b-candidate`, commit `8570c78b47b0f8afb59a4d1e305af269ad6a4936`.
- Authoring/controller inputs: `/home/thenam176/betting-helper/authoring-part-b-review-inputs`, commit `959439f492b6bd385bfdce57443733a00044aebc`.
- Đã đọc AGENTS của workspace và hai repo, các hợp đồng v3 đang materialize, code của các entrypoint, bộ kiểm thử liên quan và kết quả r24.
- Root workspace có nhiều repo/phiên bản cũ; báo cáo không coi chúng là ứng dụng hiện hành và không tuyên bố audit lại mọi snapshot lịch sử.
- ZIP kế hoạch gốc và sidecar không còn tại đường Desktop người dùng nêu. Tìm tên chính xác trong workspace/Desktop không thấy bản thay thế. Vì vậy đây không phải xác nhận đã đối chiếu từng điều khoản trong ZIP gốc. Phân loại việc có thể hoãn dựa trên yêu cầu trực tiếp của người dùng và hợp đồng/code hiện tại; không âm thầm thay đổi kế hoạch đã seal.
- Codebase-Memory được dùng để định hướng cấu trúc; graph loại trừ tools/docs và một số tests nên các kết luận entrypoint dựa trên đọc file thực tế.

## Bản đồ ứng dụng và luồng chính

| Thành phần | Vai trò | Trạng thái kiểm tra |
|---|---|---|
| `tools/launch_part_b.py` | Menu Windows/WSL, chọn trận, status, probe, discovery, live, replay | Có; còn tải bằng chứng lặp và thông báo lỗi quá chung |
| `windows_credential_store.py`, `windows_credential_helper.py` | Lưu key Windows Credential Manager, giải phóng lease, truyền kín đến backend | Code/tests có; không đọc hay xác nhận key thật trong audit |
| `ProviderBundlePoller`, `ApiFootballClient`, quota ledger | Một scheduler/backend; request bundle và hạn mức bền vững | Tests local PASS; provider cũ PASS không cấp admission cho nguồn/trận mới |
| `dom_reader.ts`, `capture.ts`, `operator_profile.py` | Đọc vùng chọn/field map có giới hạn, kiểm tra H/D/A và binding | Synthetic PASS; chưa có sample/profile thực được chấp nhận |
| `background.ts`, `panel.ts`, `workspace.ts` | Shared watchlist, hiển thị, pairing, STOP | Đã có; không cần tạo UI mới |
| `live_preflight_batched.py`, `live_intent.py` | Xác minh bằng chứng, receipt, scope, thời hạn, consent | Có; phát hiện vấn đề intent hết hạn trong lúc xác minh chậm |
| `LiveCaptureSpool`, `LiveStore`, `live_replay.py` | IndexedDB → loopback → SQLite → replay | Local tests PASS; thiếu proof credentials trong registry B hiện tại |
| authoring, P08/P09, host review | Qualification, seal, launch, độc lập và provenance | r24 có bằng chứng PASS cơ học; verdict A/B vẫn HOLD |

Luồng nguồn: Windows launcher → backend WSL2 → consent/credential lease → ProviderBundlePoller → LiveStore. Tab được chọn → fixed reader → LiveCaptureSpool → loopback có role/MAC → cùng LiveStore → shared projection → Side Panel/workspace. Đóng phiên → replay/qualifier.

Luồng review hiện tại: candidate qualification/seal → A/B candidate; riêng đường lấy mẫu/live tiêu thụ B theo các scope `OPERATOR_DISCOVERY_TOOL`, `CAPTURE_PROFILE`, `LIVE_SECURITY`. Một result candidate không thể đổi nhãn thành scope live.

## Blocker và lỗi còn tồn đọng

| ID | Mức ảnh hưởng | Phát hiện, bằng chứng | Việc đóng nhỏ nhất |
|---|---|---|---|
| F01 | Cản chuẩn bị nguồn thật khi xác minh chậm | `execute-discovery` đọc intent trước `verify_external_review`, rồi mới hỏi/consume. Intent tối đa 900s. Diagnostic dùng đồng hồ giả lập xác minh 901s tái hiện việc hỏi xác nhận sau khi intent hết hạn rồi exit 2. | Xác minh nặng trước khi tạo preview consent ngắn hạn; recheck byte/scope/trust/revocation trước consent và I/O. Không tự xác nhận hoặc kéo dài intent cũ. Áp dụng cùng nguyên tắc cho live launcher. |
| F02 | Lãng phí lớn, làm F01 dễ xảy ra | Menu live gọi `readiness` → `prepare_live_intent` → launcher `_load_action`; cả ba gọi `load_evidence`. Một cấu hình đủ evidence có cả capture/security review. `verify_external_review` gọi `authorized_review_context` → `measure_review_context` → sealed verification. | Truyền đối tượng bằng chứng đã xác minh trong cùng operation và dùng các recheck hiện có. Không tái sử dụng cờ PASS thuần, không dùng cache theo mtime, không reuse qua source/boot/epoch/expiry thay đổi. |
| F03 | HOLD độc lập B | Registry credential test dùng `UniversalDenialEngine`/E0 cũ, không chứng minh current live sinks. | Mở rộng đúng kiểm thử đăng ký sẵn cho cookie/token/raw_response/authorization: control cho phép, deny ở nhiều độ sâu, mutation làm vô hiệu proof; quan sát hash/log/SQLite/IndexedDB thực theo yêu cầu. Không cần sửa guard nếu kiểm thử đầy đủ vẫn PASS. |
| F04 | HOLD độc lập A | A tự ghi nhận đọc historical memory ngoài role inputs. Human attestation đã được ghi nhận sau execute; không chữa được việc lệch input. | Sửa đường khởi tạo reviewer để chỉ nạp input được phép và kiểm tra điều này trước execute tốn thời gian; review A thay thế. Nếu app luôn nạp memory, không yêu cầu mở task giống hệt rồi hy vọng khác. Bản HOLD cũ giữ nguyên. |
| F05 | Gate thời gian riêng của aggregation | Launch v3 28800s, nhưng aggregation vẫn tối đa 3600s sau lần hoàn tất cơ học muộn hơn. R24 deadline này là `2026-09-14T00:59:27.141935Z`, đã qua tại thời điểm audit. | Finalize/aggregate sớm khi thực sự đủ điều kiện; nếu cần nới, sửa policy qua generator và qualification. Không gia hạn ngầm receipt đã cấp. Đây chưa phải blocker đầu tiên của r24 vì hai verdict vốn HOLD. |
| F06 | Lỗi điều phối | execution-state còn `current_sealed_pack` r20, `current_review_handoff` r22, `package` cũ, `pending_user_input.answer_received=false` và chỉ dẫn sửa ba lỗi cũ; cùng file có current_delivery r24 và dữ liệu human mới. Một số tài liệu live cũng ghi trạng thái/flow cũ. | Đồng bộ trường current từ một candidate/evidence manifest; giữ lịch sử rõ ràng. Public diagnostic trả mã lỗi allowlist đủ cụ thể, không dump exception chứa dữ liệu. Không hỏi lại tên thenam. |
| F07 | Chưa triển khai bản hiện tại trên đường người dùng | Gói r24 có và 25 file kiểm tra toàn vẹn PASS. `Documents/BettingHelper`/Desktop có bảy bản cài/shortcut cũ; không có `8570c78b47b0`/shortcut 8570c78b ở vị trí installer quy định. | Sau khi đóng băng candidate cuối, cài gói đúng hash một lần; load extension của gói đó. Chưa kiểm tra browser profile thực nên không khẳng định extension nào đang được nạp. |
| F08 | Chưa có admission config hiện tại | Checkout hiện chỉ có config examples, chưa có current reviewed config trong đường launcher thường dùng. Preflight example báo tám điều kiện thiếu; platform/Part A đã có bằng chứng nhưng chưa được gắn vào config này. | Chuẩn bị private config/evidence paths, xác minh lại bytes; không sửa config example để giả nhận readiness. Phân biệt artifact đã tồn tại với artifact đã được loader chấp nhận. |
| F09 | Dữ liệu nhà cung cấp/trận mới | Probe fixture 1635632 từng được người dùng chạy PASS/4 attempts trên nguồn cũ; ngày chọn 10/09 đã qua. Loader đòi cùng source/operational scope và probe trong 24h. | Chọn fixture sắp diễn ra, probe đúng nguồn và quota sau consent riêng. Chỉ dùng key lưu sẵn nếu đã enroll; không yêu cầu paste key. |
| F10 | Khả thi operator chưa biết | Chưa có sample thật, native IDs, HOME/AWAY, complete H/D/A và settlement được xác minh; profile index rỗng. Có selected-region bootstrap nhưng không chứng minh DOM thật đáp ứng grammar/required fields. | Lấy sample read-only sau scoped tool review và consent riêng; lập profile từ dữ liệu thực. Thiếu trường thì giữ unsupported/HOLD; không đoán IDs hay settlement. Đây là bất định sản phẩm lớn nhất còn lại. |
| F11 | Chưa có review của dữ liệu/profile/live | Hai result hiện tại thuộc `CANDIDATE_READINESS`, trong khi loader cần các receipt scope thực. Profile/capture/security paths đều chưa được chấp nhận. | Cấp scope B thực từ cùng seal khi source không đổi; review profile rồi final enabled config/live artifacts. Dùng cơ chế v3 hiện có, không xây một review framework mới. |
| F12 | Chưa có lần chạy thật được chấp nhận | Chưa có in-progress provider + capture thực, ba đối chiếu H/D/A FT độc lập theo thời gian, đóng run và replay. | Sau admission, thử một fixture/FT khoảng 15–20 phút đang thi đấu trong bound đã xác nhận; ba CHECK cách ≥30s, STOP, replay. Ghi NOT_OBSERVED cho sự kiện không xảy ra. |

F01 là lỗi thứ tự/khả dụng, không phải bypass bảo mật: từ chối intent hết hạn là đúng. Độ trễ 901s trong diagnostic được tiêm bằng đồng hồ giả; audit không chạy một live receipt thật mất 901s. Các lần launch/prepare r24 thực tế mất khoảng 18 phút mỗi lần là tín hiệu cần xử lý đường nặng này, không phải phép đo chính xác latency của live admission.

Diagnostic mới của F03: gọi `validate_live_record` và `LiveStore.append` thực với 1 allowed control và 12 trường hợp field/depth bị cấm. Tất cả trường hợp bị chặn bằng `E_LIVE_RECORD`, không gọi hash sink/log/SQL, file SQLite không đổi. Chưa có guard-disabled mutation, chưa có IndexedDB/browser trong diagnostic, không nằm trong registry host. Do đó không đóng review B và không phát hiện lộ secret thật.

Rủi ro vận hành sau trận đầu: config factory giữ nguyên `run_output_dir`, còn service từ chối thư mục đã tồn tại. Mỗi run cần output riêng, được đưa vào scope config trước review; không xóa run cũ để chạy lại. Các tài liệu cũ nói phải nhập key mỗi restart cũng không còn mô tả đúng nhánh Credential Manager.

## Vì sao test đều xanh nhưng vẫn HOLD

1. Test PASS trả lời các assertions đã viết; không chứng minh assertion đó bao phủ đúng current live surface. F03 là ví dụ cụ thể.
2. Review đang kiểm tra cả independence/custody/freshness. Các điều kiện này độc lập với test code. F04 và F05 không được chữa bằng chạy lại test.
3. Nhiều sửa chữa phát sinh ở tooling/governance, kéo theo candidate commit mới và bằng chứng phải gắn lại. Checkpoint giữ nhiều thế hệ khiến vòng tiếp theo dễ lấy nhầm nguồn.
4. Candidate review được người dùng hiểu là cửa cuối trước live, nhưng code còn ba loại scope B thực. Cần hiển thị chuỗi này trước khi hẹn trận.
5. Thiếu sample operator từ sớm khiến mô hình dữ liệu/selector có thể chỉ bị kiểm chứng sau một chuỗi qualification dài.

Thời gian đã đo của campaign r24 (không chạy lại trong audit):

| Công đoạn | Thời gian |
|---|---:|
| Full controller | 94,9 phút |
| Part B mock | 14,8 phút |
| Platform + đóng gói | 18,8 giây |
| P08/P09 các bước thành công | 85,3 phút |
| Cấp launch + chuẩn bị A/B | 72,4 phút |
| Tổng các đoạn trên, chưa tính review và chờ người dùng | Khoảng 267,6 phút / 4 giờ 28 phút |

Đóng gói extension chỉ khoảng 6,2 giây. Phần lớn thời gian không nằm ở việc xây UI. Số đo trên là thời gian process/campaign, không phải chi phí token hay dự báo tiết kiệm đã chứng minh.

## Những phần có thể bỏ khỏi đường tới trận đầu

| Việc | Có thể làm ngay theo phạm vi hiện tại? | Điều kiện |
|---|---|---|
| PB-22: chạy 3/5 trận | Hoãn | Giữ max_matches=1; không tuyên bố PASS_THREE/FIVE |
| PB-24/SCOPE0, dataset, quyền nghiên cứu, models/Part C | Hoãn | Không là prerequisite trong current live loader; các verdict đó vẫn pending |
| H1/H2 odds settlement, mọi loại giải/thị trường | Hoãn phần mở rộng | Trận đầu chỉ FT có H/D/A đầy đủ, vẫn giữ provider polling theo period |
| Events fallback | Giữ OFF | Không tạo thêm feasibility/budget work không cần cho scope hiện tại |
| Xây UI/extension khác | Không cần | Tái dùng sản phẩm đang có, chỉ sửa lỗi trực tiếp cản workflow |
| Chạy đủ 120 phút | Không cần | 120 phút là trần; thử khoảng 15–20 phút với consent tương ứng và tiêu chí qualifier vẫn đầy đủ |
| Nhập lại API key mỗi trận | Không cần nếu đã enroll và lease/generation hợp lệ | Credential Manager đã có; vẫn phải consent từng nguồn/run |
| Build/seal lại chỉ vì có sample/config riêng mới | Không mặc định cần | v3 `--scope`/`--scope-input` bind private JSON từ cùng qualified source/seal; vẫn cần scope receipt mới và byte rechecks |
| Sửa tracked profile-index để chạy thật | Không phải dependency của loader | Index hiện chỉ được test sử dụng; runtime đọc private profile/review từ config. Handoff thay đổi phải ghi rõ; không sửa index sau freeze làm đổi commit để rồi tự invalid hóa review |
| Chạy toàn bộ test tương lai `E_CONTRACT_NOT_IMPLEMENTED` | Không kích hoạt cho scope mới nếu chưa được chọn | Giữ đủ các regression hiện được controller yêu cầu |
| Chứng minh mọi tình huống goal/card/suspend/power-loss trong chính trận đầu | Không cần giả vờ quan sát | Giữ các negative/crash tests bắt buộc; ghi rõ trường hợp thực chưa quan sát, không tuyên bố qualification rộng hơn |

## Chỉ có thể thay sau amendment rõ ràng

- Không tiếp tục dùng A/B candidate tổng quát làm gate lặp cho từng sample hoặc trận. Current loader tiêu thụ scoped B và không gọi candidate A/B aggregator. Đây là cơ sở kỹ thuật để thu hẹp đường tới live; nó không tự xóa nghĩa vụ A/B đã chọn trong hợp đồng/controller. Cần ghi rõ loại approval nào phục vụ candidate, loại nào phục vụ operation.
- Có thể thay human-open thủ công bằng controller khởi tạo phiên độc lập thật nếu môi trường hỗ trợ và contract/schema được sửa để mô tả đúng provenance. Không thể chỉ đánh `attested=true`, dùng agent triển khai tự ký review hoặc đổi tên một phiên cũ.
- Có thể nới aggregate delay trong policy sau khi giữ nguyên chữ ký, revocation, boot, exact input và expiry checks. Nới launch lên 8h đơn thuần không nới aggregate delay 1h. Receipt cũ không được hồi tố.
- Có thể phân biệt approval nguồn/capability dài hơn với approval config/profile/run ngắn hơn để giảm review theo từng trận. Đây là thay đổi trust model rộng, không phải lựa chọn tối thiểu cho trận đầu.
- Có thể gộp orchestration nhiều scope vào một đợt review, nhưng format hiện tại bind đúng một scope/result. Không lấy một receipt candidate hoặc profile dùng thay LIVE_SECURITY.

Khuyến nghị cho tốc độ: tận dụng v3 và proof objects đang có; sửa lỗi nhỏ và thủ tục startup/finalize một lần. Chưa nên thiết kế lại toàn bộ hệ review hoặc cache xuyên campaign trước trận đầu.

## Không bỏ các bảo vệ thực sự cần thiết

Giữ provider backend riêng; endpoint/fixture allowlist; daily/session/minute reservation; key chỉ qua terminal/kho OS; deny secret trong record/log; exact H/D/A/native binding; operator tab/profile được chọn; loopback 127.0.0.1; role/MAC/replay/revocation; durable store/replay; STOP/expiry; review độc lập của mặt live được kích hoạt; và consent đúng scope. Không coi synthetic PASS là quan sát nguồn thật. Không đặt cược/Cashout/Part C.

## Batch sửa đề xuất, rồi đóng băng nguồn

1. Đưa F03 vào kiểm thử đăng ký hiện có: Python security boundary, TS sink test, browser spool regression khi bắt buộc. Cùng 4 trường cấm, allow/deny/mutation; actual observer tách khỏi oracle. Chạy focused trước; chỉ sửa production guard nếu có counterexample.
2. Sửa F01/F02 ở entrypoint chung: heavy verification một lần trước short intent; tái sử dụng EvidenceIndex/review proof trong operation; recheck source/config/artifact bytes, boot/epoch/revocation, scope và thời gian trước consent/I/O. Test delayed verifier, changed input, expired/refused consent, no key read/no request/no listener khi bị từ chối.
3. Sửa startup A, ghi nhận human input đúng thời điểm, hiển thị HOLD reason cụ thể; làm sạch trường current của checkpoint và hướng dẫn triển khai. Không đổi model/reasoning hoặc global memory của người dùng. Nếu môi trường không đáp ứng input isolation, phát hiện trước execute.
4. Chốt scope trận đầu: Windows Chrome → WSL2, một fixture, FT, khoảng 15–20 phút, fallback OFF, không đổi quota. Chuẩn bị đủ source-proof coverage matrix và kiểm thử nguyên workflow từ launcher đến lỗi/consent/replay trước seal. Có thể ghi review-bound config thật sau freeze trong `.local/part-b`.
5. Một local commit cho batch sau khi focused/static/affected regressions PASS; chạy qualification/P08/P09/seal cho bytes cuối. Giữ mọi receipt cũ. Không cập nhật tracked status/profile/index sau seal nếu không có sửa nguồn cần thiết.
6. Thực hiện độc lập đúng scope và công cụ đã preflight; finalize/intake khi kết quả tới và đủ điều kiện. Chỉ launch review khi từng yêu cầu hiện biết đã có nguồn/bằng chứng. Nếu xuất hiện counterexample mới, sửa tập trung; không thể đảm bảo một review trung thực sẽ không tìm lỗi mới.
7. Cài đúng gói; chọn trận tương lai. Probe theo consent riêng có thể chạy song song chuẩn bị tool-review sau khi nguồn đã đóng băng, không cần chờ profile. Lấy sample trước để giải quyết bất định DOM. Tạo profile/binding thực và scoped profile review, rồi final live config/security review bằng cơ chế v3 cùng seal nếu source không đổi.
8. Kiểm tra artifact paths, candidate/package/extension và thời gian hiệu lực còn đủ cho session. Tạo intent ngay trước consent. Người dùng START READ ONLY → ba CHECK FT → STOP → qualifier/replay. Chỉ khi kết quả thực PASS mới cấp LIVE_READ_ONLY_PASS_ONE.

Không hẹn một trận sát giờ khi F01/F03/F04 và DOM feasibility chưa đóng. Cửa sổ trận được chọn sau khi phần chuẩn bị thực đã sẵn sàng.

## Kiểm tra thực thi trong audit này

- Hai nhóm pytest không trùng nhau: 183 + 238 = 421 PASS, 0 FAIL, 0 SKIP (27 module). Có thực thi TypeScript contract test bằng compiler vào thư mục riêng; không chạy lại Windows browser acceptance trong audit.
- Ruff Part B/tests: exit 0. mypy phạm vi Part B: exit 0, 36 source files. TypeScript live typecheck và ESLint: exit 0. Registry self-check: exit 0.
- Diagnostic current sinks: local PASS, 1 allow + 12 deny; limitations nêu trên.
- Diagnostic slow discovery: tái hiện lỗi, script kiểm chứng exit 0; launcher dưới clock giả exit 2 đúng như quan sát.
- Preflight config example: exit 2 dự kiến, không được dùng để kết luận artifact platform/Part A không tồn tại hoặc key thật bị thiếu. CLI này truyền key_present=None, nghĩa là NOT_CHECKED.
- Đối chiếu source hash, các report r24, raw result A/B và inventory gói delivery 25 file. Mock r24 ghi 457 executed Python tests; platform PASS dùng SYNTHETIC, sleep/wake và power-loss NOT_OBSERVED. Đây là bằng chứng trước đó đối chiếu lại, không phải full campaign mới.
- Lần gọi pytest đầu có lỗi harness của audit: dùng `-p no:cacheprovider` xung đột `--strict-config` và `cache_dir` của repo (exit 4, no tests). Đã sửa argv để dùng cache riêng, không sửa config repo; log thất bại giữ lại. Diagnostic clock đầu có lỗi biến lớp trong script audit, đã sửa và giữ log trước; không phải lỗi ứng dụng.
- Không chạy lại full qualification/seal/A/B, không quét CVE mới, không chứng minh tất cả historical toolchain/type debt đã đóng, không quan sát native Side Panel trên profile thật, không đọc key/credential slot và không gọi provider/operator.

Toàn bộ argv/exit/duration/log hashes nằm trong `*.command.json`; dữ liệu đối chiếu nằm trong `CURRENT_EVIDENCE_CHECK.json`, `CHECKPOINT_DRIFT.json`, `sink-diagnostic.json`, `slow-discovery.json`, và manifest audit.

## Verdict

| Nhãn | Trạng thái |
|---|---|
| PART_B_MOCK_PASS | PASS r24 được đối chiếu đúng source; audit có thêm 421 local pytest PASS |
| PROVIDER_PROBE_PASS | Historical PASS; NOT_REVALIDATED_FOR_CURRENT_CANDIDATE |
| OPERATOR_PROFILE_ACCEPTED | NO |
| PLATFORM_BRIDGE_PASS | PASS r24 Windows Chrome/WSL2 với synthetic data, chưa gắn vào live config |
| LIVE_READ_ONLY_PASS_ONE | NOT_EXECUTED |
| LIVE_READ_ONLY_PASS_THREE | NOT_EXECUTED; có thể hoãn |
| LIVE_READ_ONLY_PASS_FIVE | NOT_EXECUTED; có thể hoãn |
| SCOPE0_READY_FOR_REVIEW | NOT_ESTABLISHED; không chặn riêng thử live chỉ đọc |
| INDEPENDENT_LIVE_SECURITY_REVIEW | NOT_ACCEPTED / WAITING_REVIEW |
| MODEL_ENABLED | false |
| MONEY_READY | NO |

Không sửa source/registry/vendor/receipt trong audit này; không commit/push/deploy. 13 generated dirty files cũ giữ nguyên. Artifact audit nằm ngoài tracked source. API attempts, operator captures, live sessions, primary credential reads trong audit đều bằng 0.
