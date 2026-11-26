# 河湾社区广播剧补录服务

河湾制作组用这个本机服务制作《桥边来信》第二场。录音师送入原音，剪辑师提交时间轴，导演从一个正式校样派发补录，演员交回整数录音帧。导演签发后，下一班用定稿号领取当时的声音和出处。

需要 Python 3.11，依赖均来自标准库。控制台物化项目时提供 `check_project.py`。从项目根目录运行完整回归和工作日演示。

```text
python3 -B check_project.py
python3 -B -m unittest tests.test_workday.WorkdayTests.test_workday
```

也可用 `python3 -B -m unittest discover -s tests -t .` 直接运行原套件。演示导入 `examples/bridge.json`，在临时库完成真实 HTTP 工作流。对白 `[10,20,30,40]` 与伴奏 `[1,2,3,4]` 得到校样 `[11,22,33,44]`。导演采用 `[1,3)` 的 `[70,80]` 后，下一班凭定稿号听到 `[11,72,83,44]`。

## 启动

```text
python3 -B -m takes.workbench --database studio.sqlite --port 8765
```

服务监听 `127.0.0.1`。每次启动补齐数据库结构。已有素材、剪辑、实收和定稿继续保留。样例由调用方显式登记。

## HTTP 接口

所有 POST 接收 UTF-8 JSON 对象。下表中列出的字段均为必填，剪辑指令另有说明。ID 为正整数。POST 成功返回 201，GET 及校样请求返回 200。所有错误返回 `error` 与 `message`。非法输入返回 400，缺少记录返回 404，过期父版及补录状态或覆盖冲突返回 409，存储失败返回 500。

| 请求 | 输入 | 成功结果 |
| --- | --- | --- |
| `POST /assets` | `source`, `sample_rate`, `frames` | `asset_id`, `source`, `sample_rate`, `length` |
| `POST /edits` | `scene`, `parent_revision_id`, `instructions` | 正式版及其轨道、片段和父版 |
| `POST /preview` | `revision_id`, `start`, `end` | 版号、场景、采样率、监听区间、`frames`, `sources` |
| `POST /takes` | `revision_id`, `start`, `end` | `take_id`, `revision_id`, `start`, `end`, `length`, `sample_rate`, `state` |
| `POST /takes/return` | `take_id`, `frames` | `take_id`, `length`, `state` |
| `POST /takes/apply` | `take_id` | `master_id` 和冻结清单 |
| `GET /masters/{id}` | 路径中的成品号 | 冻结清单、`master_id`, `frames` |

`GET /assets/{id}` 读取素材及原帧，`GET /revisions/{id}` 读取正式版，`GET /scenes/{name}` 读取当前版头，`GET /takes/{id}` 读取单据、实收和采用号，`GET /masters` 返回已提交的 `master_ids`。场景名可在路径中用百分号编码。

### 剪辑与校样

初次发行的 `parent_revision_id` 为 `null`，此后使用当前正式版号。非空 `instructions` 依次作用于候选布局。`dialogue` 是可补录的对白轨。其他命名轨用于伴奏或环境声。同一轨内的片段不能重叠，各轨可在同一帧叠加。对包含空隙的移除区间，只剪去区间内该轨的声音，其他片段保持在原坐标。场景末端取全部片段的最大终点。空场的长度为零，首个插入素材确定场景采样率，清空后仍保留采样率。

| 指令 `op` | 其他字段 | 效果 |
| --- | --- | --- |
| `insert` | `track`, `asset_id`, `source_start`, `source_end`, `at` | 在绝对位置插入一个新出现 |
| `copy` | `occurrence_id`, `at`, 可选 `piece_start` | 在同轨复制所选片段并分配新出现号 |
| `move` | `occurrence_id`, `at`, 可选 `piece_start` | 在同轨移动所选片段，保留原出现和素材区间 |
| `remove` | `track`, `start`, `end` | 移除该轨区间内的已有声音 |
| `level` | `track`, `percent`, `muted` | 配置该版轨道增益及静音 |

出现号在场景内唯一分配。剪成多段后，各残段共享原出现号，可用 `piece_start` 选择其中一段。若有多个残段，移动或复制时须指定其当前起点。坐标、采样率、增益和样本均使用 JSON 整数，布尔值仅用于 `muted`。所有帧区间左闭右开。素材切片必须非空且落在素材范围内。监听窗和派发窗必须非空且落在场景范围内。

默认音量为 100%。每个输出位置先累加各轨样本与音量百分比的乘积，除以 100 时向零取整，最后限制到 `[-32768,32767]`。静音及 0% 音量轨无贡献，未放置声音的位置输出零。正音量轨上的素材零样本仍有出处。`sources` 按轨道名、轨内位置排列，包含素材号、来源号、出现号、素材内区间和绝对场景区间。

### 派发、采用和交班

派发窗须命中对白。补录单冻结原版号及其录制窗。窗内空隙也算录制长度。演员在 `pending` 状态交回整窗，合格时成为 `received`。长度或样本校验失败时可继续交回。已有实收的单拒绝再次交回。

贴入依据提交时的正式剪辑版。原窗仍在场的对白帧从实收的原窗偏移取样。伴奏和其他对白照常混音。整窗无残留时返回冲突，实收保留。贴入和剪辑通过同一 SQLite 数据库提交，成功的先后决定所用正式版。签发时一起冻结声音和清单，并将单转为 `adopted`。已采用单可再次请求贴入来领取原清单。失败的贴入保留原实收供重试。

清单的 `coverage` 列出实际覆盖的场景区间，`sources` 记录保留的素材贡献，`take` 记录补录单、派发版、原窗及每段覆盖的素材区间、场景位置与原窗偏移。定稿可按号复听。后续改剪时，交班人员可分别领取旧定稿和指定新版的校样。
