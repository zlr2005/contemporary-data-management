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
