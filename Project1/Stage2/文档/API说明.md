# API说明

接口前缀为 `/api`，请求体使用 JSON。登录后将 token 放入 `Authorization: Bearer <token>`。完整参数和在线调试见运行后的 `/docs`。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /health | 检查 MongoDB 连接 |
| POST | /auth/register | 注册，传 username、password |
| POST | /auth/login | 登录，返回 access_token 与当前用户 |
| GET | /auth/me | 获取当前用户 |
| GET | /capabilities | 获取支持的题型、条件运算符和容量限制 |
| GET | /surveys | 分页查询自己的问卷，参数 page、size |
| POST | /surveys | 创建草稿 |
| GET | /surveys/{sid} | 查询自己的完整问卷 |
| PUT | /surveys/{sid} | 保存草稿，包括题目及规则 |
| PATCH | /surveys/{sid} | 更新标题、说明、截止时间 |
| POST | /surveys/{sid}/publish | 发布，检查问卷完整性 |
| POST | /surveys/{sid}/close | 关闭已发布问卷 |
| POST | /surveys/{sid}/preview | 创建者预览，不保存正式答卷 |
| GET | /surveys/{sid}/statistics | 整体统计，可用 question_id 筛选单题 |
| GET | /surveys/{sid}/questions/{qid}/contents | 分页查看填空内容，参数 page、size |
| GET | /surveys/{sid}/responses | 分页查看答卷；匿名时不返回填写者 ID |
| GET | /fill/{code} | 登录后获取可填写的问卷 |
| POST | /fill/{code}/evaluate | 校验已回答题目并计算下一个问题 |
| POST | /fill/{code}/submit | 提交答卷；需要 submission_key 与 answers |

## 常用请求格式

| 请求 | 字段 |
| --- | --- |
| 创建和保存草稿 | title、description、allow_anonymous、allow_repeat、deadline_at、questions |
| 修改基本信息 | title、description、deadline_at；三个字段作为完整基本信息提交 |
| 预览和逐题校验 | answers：由 question_id、value 组成的数组；未答题不传，已确认跳过的选答题可传 null |
| 正式提交 | submission_key：UUID 字符串；answers：答案数组 |
| 截止时间 | ISO 8601 字符串，必须包含时区，如 `2026-11-01T00:00:00+08:00`；不设置传 null |
| 单选答案 | 选项 ID 字符串 |
| 多选答案 | 选项 ID 数组，不能重复 |
| 文本和手机号 | 字符串 |
| 数字答案 | JSON 数字，不接受数字字符串或布尔值 |

题目、校验和规则结构见同目录的《数据库设计.md》。题目、选项和规则 ID 在前端使用 UUID 生成；后端检查格式、唯一性、引用和跳转方向。

## 返回约定

| 状态码 | 含义 |
| --- | --- |
| 200 | 操作成功 |
| 201 | 用户或草稿创建成功 |
| 401 | 未登录、登录失效或密码错误 |
| 404 | 资源不存在或不属于当前用户 |
| 409 | 重复填写、重复用户名、状态冲突或提交键冲突 |
| 422 | 配置或答案校验失败 |
| 503 | 数据库不可用或操作失败 |

业务错误使用 `detail` 返回提示，题目答案错误另外返回 `field` 指向题目 ID。分页接口最大 size 为 100。管理接口即使知道其他人的资源 ID，也不能绕过所有权检查。

## 第二阶段新增接口

本文件保留第一阶段接口，并补充当前实际实现的第二阶段接口。默认服务为 [本机第二阶段 API 文档](http://127.0.0.1:8001/docs)，应用版本为 2.2.0。实现与验证见[第二阶段实现与验证](../测试/测试用例.md#第二阶段实现与验证)。

### 已实现的题目与版本接口

以下路径同样使用 `/api` 前缀和 Bearer 登录身份。拥有者可管理原系列；当前共享接收者可读取和复用，修改时派生到自己名下。正式版本不提供覆盖或删除接口。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /question-series | 列表，支持 status、keyword、page、size；scope 接受 owned 或 shared |
| POST | /question-series | 传 name、content、request_key，保存系列及首版本 |
| GET | /question-series/{series_id} | 系列详情、最新成功版本、数量及操作状态 |
| PATCH | /question-series/{series_id} | 修改 name 或 status，支持归档与恢复可用 |
| GET | /question-series/{series_id}/versions | 分页历史，含直接来源和恢复来源编号 |
| GET | /question-versions/{version_id} | 只读查看正式版本 |
| POST | /question-series/{series_id}/versions | 传 parent_version_id、content、request_key，新建版本 |
| POST | /question-series/{series_id}/restorations | 传 base_version_id、restore_version_id、request_key，以旧内容创建新版本 |
| POST | /question-versions/{version_id}/forks | 当前可使用的自有或共享版本派生为自己的新系列，传 name、content、request_key |
| GET | /question-series/{series_id}/usages | 版本使用情况，可筛选 version_id；只返回允许查看的问卷信息 |

content 仅包含 type、title、required、options、validation；不包含问卷内部 id 与 jump_rules。request_key 为 UUID，相同操作重试沿用；首次成功 201，已有请求重放 200，不同请求共用同键返回 409。

问卷 POST、PUT 继续支持原七字段题目，第二阶段编辑器增加 series_id、version_id；服务器生成并验证内容快照。GET 管理详情增加 question_bindings 和 migration_status。新编辑器 PUT 和 PATCH 提交 expected_updated_at 检查并发；未迁移 schema_version=1 问卷保留原操作，待迁移后加入版本复用。

GET /fill/{code} 不暴露版本管理元数据，答题、提交及原统计保持原请求和含义。GET /health 增加 database_name、stage，以区分两阶段实例。实际错误格式继续使用 detail、field；规划文档中更细的业务 code 尚未全部实现。

### 共享、题库及跨问卷统计接口

以下路径均有 `/api` 前缀。共享与统计授权的 username 必须对应已注册用户；服务器确定授权者，不能授权给自己。撤销路径的 grantee_id 为被授权用户 ID。

| 方法 | 路径 | 用途及参数 |
| --- | --- | --- |
| GET | /question-series/{series_id}/shares | 所有者分页查看共享状态，page、size |
| PUT | /question-series/{series_id}/shares | 授权或重新授权，JSON：username |
| DELETE | /question-series/{series_id}/shares/{grantee_id} | 撤销题目使用权 |
| GET | /question-banks | 自己的题库，page、size |
| POST | /question-banks | 创建题库，JSON：name、description |
| GET | /question-banks/{bank_id} | 名称、说明、revision、成员快照与当前可操作状态 |
| PUT | /question-banks/{bank_id} | 保存，JSON：name、description、version_ids、revision |
| DELETE | /question-banks/{bank_id} | 删除容器，JSON：revision；不删除题目、问卷或答卷 |
| GET | /surveys/{sid}/questions/{qid}/statistic-grants | 所有者分页查看该问卷题目的统计授权 |
| PUT | /surveys/{sid}/questions/{qid}/statistic-grants | JSON：username、allow_contents；已发布过的问卷才可授权 |
| DELETE | /surveys/{sid}/questions/{qid}/statistic-grants/{grantee_id} | 撤销该单题的统计授权 |
| GET | /question-statistics/versions | 可进入统计的版本列表，keyword、series_id、page、size |
| GET | /question-statistics/versions/{version_id} | 汇总，scope 为 all、own、authorized；数字题可重复传 boundaries |
| GET | /question-statistics/versions/{version_id}/sources | 有权查看的精确来源，scope、page、size |
| GET | /question-statistics/versions/{version_id}/contents | 文本或数字填写内容，scope、page、size；每项仅有 value |

题库 revision 从 1 开始，每次保存递增；保存和删除都检查旧 revision，冲突返回 409。version_ids 最多 500 个且不能重复。已有失效来源成员可以保留或移除，不能新增、重新加入或升级到无权使用的版本。

统计按具体 version_id 分别计算。scope=all 表示当前有权查看的所有来源，own 为自己的问卷，authorized 为获单题授权的他人问卷。拥有题目或获得共享不代表可以读取他人的答卷；只获统计授权也不会取得原系列历史和整份问卷。来源按 survey_id 与 question_id 精确配对，并验证 version_id。

汇总包含 answered、total_responses、source_survey_count、source_question_count 和 content_access。选择题返回 options 计数；数字题增加 average、minimum、maximum、distribution。有效回答数与可见内容数分别计算。boundaries 要求 2～20 个严格递增的有限数字，如 `?boundaries=10&boundaries=30`，生成两端尾区间及中间区间。

撤销共享后，既有问卷仍保留引用并可继续发布、填写和统计，但不能新增使用、派生或读取原历史。撤销统计授权后，后续统计请求立即按新的授权范围计算。已获填空内容权限的跨用户结果不返回填写者、答卷编号或逐条提交时间。

## 第二阶段接口契约与兼容说明

以下保留第二阶段设计依据及兼容约定。实际已上线的接口见上一节；细分业务 code 等设计示例尚未全部实现，不作为当前返回保证。

本文将已确定的业务规则和数据库设计落实为接口契约，供后续前后端开发及接口测试使用。配套页面流程见[第二阶段页面与操作流程](系统说明.md#第二阶段页面与操作流程)。

本文保留完整设计契约。题目、版本、共享、题库及跨问卷统计核心接口已实现，实际路径、参数与兼容情况见[API 说明](API说明.md)和[第二阶段实现与验证](../测试/测试用例.md#第二阶段实现与验证)。实际错误仍以 detail、field 为主；下文细分业务 code 是设计约定，尚未全部实现，不能将设计示例视为当前返回保证。

### 1. 通用契约

- 接口前缀 `/api`，请求和返回使用 JSON。除原健康检查、注册、登录外，均要求 Bearer token；资源的 owner_id、created_by 和 granted_by 从登录身份确定，不接受客户端指定。
- 系列、版本、问卷、题库、用户 ID 在 JSON 中使用 ObjectId 的 24 位十六进制字符串；问卷内部题目、选项、规则 ID 继续沿用原字符串规则。业务版本号使用 version_no，不用 schema_version 代替。
- 新增对象对外使用 `_id`，保持现有资源返回风格；来源字段使用 series_id、version_id 等明确名称。日期使用含时区的 ISO 8601，后端 UTC 保存，页面北京时间展示。
- 新增列表统一返回 `{items, total, page, size}`；page 从 1 开始，size 默认 20、最大 100。原接口不因本阶段强制改变分页返回格式。
- 首次创建资源返回 201，更新、查询及幂等重放返回 200；删除题库、撤销授权也返回 200 JSON，避免当前 api.js 无条件调用 response.json() 时出错。
- 输入模型拒绝未知字段；type、title、required、options、validation 的取值及容量沿用第一阶段，新增管理名称为 1～200 字，说明最多 5000 字。id、跳转及问卷内容仍使用原限制。
- 前端使用返回的 actions 描述可用操作，但后端每次操作仍重新检查身份、状态和授权；按钮隐藏不代替后端检查。
- 新增 GET 只读，不能隐式迁移、创建版本、绑定题目或修改题库。数据库迁移由脚本执行，不向普通用户开放迁移 HTTP 接口。

#### 1.1 错误与冲突

保留原 detail、field、errors，新增业务 code 和可选的定位项；原前端仍可直接展示 detail。

| HTTP 状态 | code 示例 | 处理 |
| --- | --- | --- |
| 401 | AUTH_REQUIRED | 登录失效，重新登录 |
| 404 | RESOURCE_NOT_FOUND | 不存在或当前用户不能读取，不回显其他用户的资源信息 |
| 409 | SURVEY_LOCKED、SERIES_ARCHIVED、SHARE_REVOKED | 已经有上下文访问权，但当前操作因状态或授权变化不可执行 |
| 409 | VERSION_ALREADY_USED、STALE_DOCUMENT、REQUEST_KEY_CONFLICT | 重复引用、并发修改或重试键对应内容不一致 |
| 422 | INVALID_CONTENT、INVALID_JUMP_RULE、INVALID_BOUNDARIES | 输入或配置有误，定位到字段、题目和规则 |
| 503 | DATABASE_UNAVAILABLE | 保留输入，恢复后重试 |

没有读取权的外部资源统一返回 404；对自己问卷中的已撤销共享引用，可以说明该引用当前不可新增使用，但不借此开放源系列历史。

```json
{
  "detail": "第 2 题的一条跳转规则引用了新版本中不存在的选项",
  "code": "INVALID_JUMP_RULE",
  "field": "q_age",
  "errors": [{"question_id": "q_age", "rule_id": "r1", "field": "value", "message": "选项已不存在"}]
}
```

#### 1.2 重试与并发

创建题目系列及首版本、创建新版本、恢复和派生均要求 request_key 为 UUID；客户端在同一次保存的网络重试中沿用，内容或操作改变后换新键。服务端规范化请求，连同操作、资源及来源计算 request_hash，使用现有设计中的 created_by + request_key 唯一约束。

相同键与相同请求返回原产物，不增加版本号；同键不同请求返回 409。重放前仍检查当前访问权限，不允许用历史请求键绕过已撤销权限。创建系列时只认首版本成功后的完整产物；失败留下的空系列不出现在列表，重复请求不得返回两个成功系列。

题库更新提交 revision；问卷新编辑器提交 expected_updated_at，须为最近一次读取返回的原始时间字符串，不在前端重新格式化。后端以读取值校验，再使用条件更新。冲突时不自动用旧页面覆盖远端，不自动重试内容写入；请用户重新读取并核对。

系列元数据和授权更新使用小粒度接口，不把整个系列或授权列表整批覆盖。授权操作按最后一次成功请求生效，返回最新状态供界面刷新。

### 2. 题目内容与版本对象

可复用 content 只有五个字段，不包含问卷内部 id、题序或 jump_rules：

```json
{
  "type": "number",
  "title": "你的年龄",
  "required": true,
  "options": [],
  "validation": {"min_value": 0, "max_value": 120, "integer_only": true}
}
```

版本详情返回 `_id, series_id, version_no, content, parent_version_id, restored_from_version_id, operation, created_by, created_at`。管理端可显示有权限的拥有者基本信息，禁止返回 request_hash、密钥或任何密码字段。request_key 为内部去重依据，不在普通题目列表中返回。

系列详情返回 `_id, name, status, owner, latest_version, forked_from, actions`。latest_version 为实际已成功保存的最大版本号对应版本。forked_from 只在有源访问权时展开详情，无源访问权时仅保留来源标识。系列列表每条带题型、最新题干摘要、最新版本号和是否可选用，不返回全量历史。

### 3. 题目管理接口

| 方法与路径 | 请求 | 返回及权限 |
| --- | --- | --- |
| GET /question-series | scope=owned 或 shared；status=active、archived 或 all；keyword；page、size | 自有或当前有效共享系列列表；shared 仅列 active，不列已撤销授权 |
| POST /question-series | name、content、request_key | 创建当前用户拥有的系列及 v1，返回 `{series, version}` |
| GET /question-series/{series_id} | 无 | 所有者或有效共享接收者查看；归档系列仅所有者读管理详情 |
| PATCH /question-series/{series_id} | name、status 中至少一项 | 仅所有者；改名或归档、恢复 active，不改变正式版本 |
| GET /question-series/{series_id}/versions | page、size | 所有者或有效共享接收者查看历史，版本号降序，保留 parent 和恢复来源 |
| GET /question-versions/{version_id} | 无 | 同上，读取指定正式版本；统计授权不直接开放此管理接口 |
| POST /question-series/{series_id}/versions | parent_version_id、content、request_key | active 系列所有者基于本系列已有版本新建正式版本 |
| POST /question-series/{series_id}/restorations | base_version_id、restore_version_id、request_key | active 系列所有者恢复；两版本均属于本系列；parent=base，内容复制 restore |
| POST /question-versions/{version_id}/forks | name、content、request_key | 当前可用版本的所有者或共享接收者派生，返回新 `{series, version}`；无改动派生时 content 仍提交完整原内容 |
| GET /question-series/{series_id}/usages | 可选 version_id；page、size | 按下文范围返回使用情况，不开放其他用户整卷管理 |

新增版本的 parent 必填，首版本由创建系列接口产生；允许基于旧版本分支，不强制 parent 必须为最新版本。恢复操作不接受自定义 content。归档与撤销共享后已有问卷、题库的快照，通过各自详情接口读取，不依赖源版本管理接口继续开放。

使用情况返回 `visible_items, visible_total, restricted_survey_count, counts_by_version`。visible_items 按问卷及版本显示题名、状态、版本号和当前用户可执行的跳转；同一系列在同卷多版本出现时分别展示，但 restricted_survey_count 按问卷去重。counts_by_version 仅系列所有者返回全局数量，其他人只返回自己的范围。

- 系列所有者：自己的使用明细，加明确向自己授权该题统计的他人问卷基本信息；其他使用仅返回数量。
- 有效共享接收者：只显示自己的使用，不返回全局受限数量，该字段为 null。
- 仅保留原引用的用户：允许查该系列在自己问卷中的使用记录，不开放系列历史、其他用户使用或新建引用；统计仅授权用户通过统计来源接口查看自己获授权的条目。
- visible_items 中 owner_context=owned 可链接问卷管理，owner_context=statistics_only 只可链接单题统计，不能链接他人整卷编辑页。

### 4. 共享使用权接口

| 方法与路径 | 请求 | 结果 |
| --- | --- | --- |
| GET /question-series/{series_id}/shares | page、size | 所有者查看已发出授权，包括 active、revoked 和接收者用户名 |
| PUT /question-series/{series_id}/shares | username | 所有者向精确匹配的已注册用户授权或重新授权，返回当前授权记录 |
| DELETE /question-series/{series_id}/shares/{grantee_id} | 无 | 所有者幂等撤销，返回 `{status:"revoked"}` |

用户名沿用 trim 和 casefold 规则，禁止给自己重复授权。目标未注册返回 422，页面提示检查用户名；不增加公开用户目录、模糊搜索或邮箱邀请功能。授权覆盖当前和后续正式版本，页面提交前显示此范围。

### 5. 题库接口

| 方法与路径 | 请求 | 结果 |
| --- | --- | --- |
| GET /question-banks | page、size | 自有题库列表，返回名称、说明、成员数、revision |
| POST /question-banks | name、description | 创建空题库，返回完整题库；创建中禁用重复点击，失败后先刷新核对再手动重建 |
| GET /question-banks/{bank_id} | 无 | 自有题库详情，返回全部成员，最多 500；成员包含快照、版本号、当前可选用及更新状态 |
| PUT /question-banks/{bank_id} | name、description、version_ids、revision | 按数组顺序保存完整成员列表，新增或换版本重新查使用权限；已有不可用条目允许原样保留或移出 |
| DELETE /question-banks/{bank_id} | JSON `{revision}` | 核对归属和 revision 后删除容器，返回 `{deleted:true}` |

PUT 返回最新 revision；同一版本重复加入返回 409，不静默去重。同系列不同版本可以并存。服务端从版本生成新成员快照，不接受客户端任意 content；保留成员使用已存快照，不能用不可用条目克隆出新的成员。更新到新版本就是在 version_ids 中显式替换旧值，其他题库和问卷不随之变化。

题库 GET 可包含当前已撤销共享或归档成员的原快照，但不展开不可访问的最新版本详情。成员返回 actions.can_select、can_update 和 unavailable_reason；此信息不代替问卷保存时再检查权限。

### 6. 扩展原问卷接口

保留 POST /surveys、GET /surveys/{sid}、PUT /surveys/{sid}、PATCH 元数据、发布、关闭、预览及填写接口，不增加每点一次选题就立即改写数据库的接口。编辑器先在当前页面组装整份草稿，点击保存后才更新问卷。

#### 6.1 第二阶段编辑器的请求

创建或保存草稿的原字段继续存在。已保存的可复用题目使用原七字段加 series_id、version_id：

```json
{
  "title": "学生情况调查",
  "description": "",
  "allow_anonymous": false,
  "allow_repeat": false,
  "deadline_at": null,
  "expected_updated_at": "2026-10-22T05:00:00+00:00",
  "questions": [{
    "id": "q_age",
    "series_id": "000000000000000000000101",
    "version_id": "000000000000000000000102",
    "type": "number",
    "title": "你的年龄",
    "required": true,
    "options": [],
    "validation": {"min_value": 0, "max_value": 120, "integer_only": true},
    "jump_rules": []
  }]
}
```

以上为 PUT 示例；首次 POST 不传 expected_updated_at。PUT 对新编辑器要求带此值，原七字段旧请求仍可兼容，不因此宣称旧客户端具备跨页面并发保护。新建问卷成功后保存返回的 _id 再发布；POST 创建问卷沿用第一阶段行为，发生响应丢失时提示先核对问卷列表，不自动无限重试导致重复创建。

引用元数据、快照和 jump_rules 分开校验：series_id 与版本所属一致，五字段 content 经规范化后与正式版本一致；新增引用检查当前权限；保留旧引用按原问卷核对。整份问卷通过后一次更新，不部分写入题序或规则。

新编辑器通过第 3 节接口先把新增或修改题目保存为正式版本，再发送整卷请求；未改内容的题目不产生版本。新版本保存成功而问卷保存失败时保留版本，返回编辑页说明哪些题已保存、问卷尚未保存，重试沿用已有版本和原请求键。

#### 6.2 兼容返回与原入口

GET /surveys/{sid} 返回原问卷内容，另在顶层提供 question_bindings，按内部 question_id 列出 series_id、version_id、version_no、来源状态和 actions；不把动作标记混入严格校验的题目内容。schema_version=1 的问卷返回 migration_status=required，保留原功能，暂不开放版本绑定操作。

填卷 GET /fill/{code} 只返回原答题字段，逐题校验和提交继续使用原 answers 与 submission_key。预览和规则引擎使用原七字段投影，不接收管理用的 ObjectId 元数据。

原七字段草稿请求由服务端按内部 id 对照原问卷：未改内容保留引用，新增题创建系列，内容变化按所有权创建新版本或有权限的派生系列。省略 version_id 不解除来源。

对已有问卷 PUT 的内部版本操作，以当前用户、问卷 ID、题目 ID、原绑定版本、操作类型和规范化新内容派生稳定的 UUID 请求键。正式版本已写入但问卷尚未更新时，重试可以找回相同产物；问卷已更新且内容未变时直接保留引用。首次 POST 仍沿用原问卷创建行为，不能宣称没有外部请求键的旧创建接口已具备完整去重能力。兼容实现需验证中断恢复，不给每次重试随意生成新 UUID。

PATCH 元数据继续接受原 title、description、deadline_at；扩展可选 expected_updated_at，新页面传入以提示陈旧编辑冲突。发布不替换题目版本、不同步题库、不生成新版本；首次发布锁定结构，之后的关闭状态同样锁定。

### 7. 单题统计授权接口

| 方法与路径 | 请求 | 结果 |
| --- | --- | --- |
| GET /surveys/{sid}/questions/{qid}/statistic-grants | page、size | 问卷创建者查看本题发出的授权 |
| PUT /surveys/{sid}/questions/{qid}/statistic-grants | username、allow_contents | 创建者授权或调整；服务端从题目读取 version_id，不接受客户端指定替代版本 |
| DELETE /surveys/{sid}/questions/{qid}/statistic-grants/{grantee_id} | 无 | 创建者幂等撤销，返回当前 revoked 状态 |

只允许对首次发布过的问卷题目授权，已关闭问卷仍可授权；未迁移题需先完成迁移。allow_contents 默认 false；单选、多选固定为 false，文本或数字才可开启。接收者不需要同时拥有题目共享权，且不能据此访问整卷统计或答卷列表。自己作为问卷创建者已有统计权，不创建给自己的授权。

### 8. 跨问卷单题统计接口

| 方法与路径 | 请求 | 返回 |
| --- | --- | --- |
| GET /question-statistics/versions | 可选 series_id、keyword；page、size | 当前可查看的版本入口，来源为自有或有效共享题目，以及自己问卷引用和收到的有效统计授权；按 version_id 去重，受限源仅返回获准的题目快照 |
| GET /question-statistics/versions/{version_id} | scope=all、own 或 authorized；数字题可重复传 boundaries | 当前范围的基础统计，不含逐条内容 |
| GET /question-statistics/versions/{version_id}/sources | scope；page、size | 本次统计允许纳入的问卷题目，标题、状态、version_id、是否可看内容，不含其他题目或分享链接 |
| GET /question-statistics/versions/{version_id}/contents | scope；page、size | 文本或数字的内容列表，仅 `{value}`，并返回内容可见范围 |

scope 默认 all，own 为自己的问卷题，authorized 为他人授予统计权限的题；按 (survey_id, question_id) 去重。授权题来自当前有效记录，不接受客户端直接传 owner_id 扩大范围；若之后加入来源筛选，也只能缩小后端计算的范围。

基础返回包含 `version, scope, source_question_count, source_survey_count, total_responses, answered, content_access`，以及题型对应的 options、average、minimum、maximum、distribution。total_responses 为纳入问卷的成功答卷数，answered 为实际回答本题的份数；未答及跳过不算 answered。每个版本在同一问卷只能出现一次，防止单题重复计数。

content_access 至少包含 `source_question_count, answered, partial`，说明其中多少回答允许逐条查看；contents 返回 `{items,total,page,size,scope,content_source_question_count}`，total 仅为内容可见答案数，不冒充全体 answered。文本的基础统计也只显示回答份数，逐条文本需内容权限。

数字题默认等宽 10 组，空数据和常量数据按业务规则处理。boundaries 为 2～20 个严格递增的有限数字，限制与原数字范围一致；自定义时额外统计首边界以下及末边界以上的尾组，中间左闭右开。返回分组的数值上下界及包含性，界面按这些字段展示，不能仅用四舍五入后的标签重新计算。

可读版本但没有任何统计来源时返回 200 空统计，明确 source_survey_count=0；无权读取版本或任何相关上下文时返回 404。基础统计可用但内容来源数为 0 时，contents 返回 200 空列表和权限说明，不把它显示成所有人都未填。单选、多选调用 contents 返回 422。

不提供跨版本合计接口。系列各版本对比由入口筛选 series_id 后逐版本读取展示，每组清楚标注版本及来源范围。撤销授权后的后续请求重新计算范围，前端也清除当前页面旧结果再加载，不能把旧缓存当成最新授权结果。

### 9. 权限矩阵

| 操作 | 题目拥有者 | 有效共享接收者 | 仅保留既有引用者 | 仅收到单题统计授权者 |
| --- | --- | --- | --- | --- |
| 查看源系列历史 | 可以，含归档历史 | 可以，系列需 active | 不可以 | 不可以 |
| 新增使用 | active 时可以 | active 且授权有效时可以 | 不可以 | 不可以 |
| 修改源系列、恢复版本 | active 时可以 | 不可以；可派生 | 不可以 | 不可以 |
| 查看既有问卷内快照 | 仅限自己问卷或另有统计授权 | 同左 | 可看自己原问卷 | 仅获授权题目 |
| 查询全局使用数量 | 可以 | 不可以 | 不可以 | 不可以 |
| 跨问卷基础统计 | 自己问卷与收到的授权范围 | 同左 | 自己问卷与收到的授权范围 | 仅有效授权范围 |
| 查看逐条填空内容 | 自己问卷与额外内容授权范围 | 同左 | 同左 | 仅 allow_contents=true 的来源 |

题目拥有者不因拥有题目就取得其他用户的回答；问卷拥有者负责自己问卷的统计授权。不同身份可叠加，最终按具体操作和具体资源判断。

### 10. 开发批次与接口验证

1. 实现系列、正式版本、恢复及派生；验证请求去重、分支、归档和不可覆盖。
2. 扩展原问卷保存与投影；验证选题、直接编题、替换版本、旧请求兼容和发布锁定。
3. 实现使用共享及题库；验证撤销后保留原引用、阻止新使用和题库并发冲突。
4. 实现使用查询、统计授权及跨问卷统计；验证按问卷题成对过滤、范围去重、内容权限和数字分布。
5. 在独立数据库完成迁移与第一阶段回归，再更新实际 API 文档；当前不将本文计划接口写成已运行接口。
