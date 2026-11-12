# 前后端接口约定

Base URL：`http://127.0.0.1:5000`。本文件和 `openapi.json` 对应实际实现。所有核心接口需Bearer Token；仅注册、登录、health公开。分页默认page=1、page_size=20，page_size最大100。

## 账户与角色

| 方法 | 路径 | 请求/用途 | 权限 |
|---|---|---|---|
| POST | /api/auth/register | username,password；只能注册user | 公开 |
| POST | /api/auth/login | username,password；返回token、expires_at、user | 公开 |
| POST | /api/auth/logout | 撤销当前Token | 登录 |
| GET | /api/auth/me | 当前用户 | 登录 |
| GET/POST | /api/users | 列表；创建username,password,role | admin |
| PUT | /api/users/{id} | role、disabled布尔、password可选 | admin |
| GET | /api/manufacturers | 分页列表（含aliases） | 登录 |
| POST | /api/manufacturers | name、website可选、aliases数组可选 | admin/auditor |
| PUT | /api/manufacturers/{id} | 同上 | admin/auditor |

密码8-256字符，用户名不区分大小写；Token默认24小时。禁用、改角色、改密码会撤销该用户全部Token；不能禁用/降级最后一个有效管理员。

## 任务创建

`POST /api/tasks` 人工录入示例：

```json
{"source_type":"manual","component":{"model":"R-1K","manufacturer":"Demo","category":"resistor","parameters":[{"name":"电阻","value":"1kΩ","confidence":1},{"name":"voltage","value":3.3,"unit":"V"},{"name":"package","value":"0603"}]}}
```

批量人工录入将 `component` 改为 `components:[...]`。类别为 `resistor/capacitor/diode/transistor/ic/inductor/other`，也接受对应中文类别。参数可采用数组，或 `{"voltage":{"value":3.3,"unit":"V"}}` 字典形式。缺失值不会转成0。

URL示例：`{"source_type":"url","url":"https://public-site.example/datasheet"}`。

`POST /api/tasks/upload`：`multipart/form-data`，字段 `file`。返回202及task_id。CSV/XLSX每行一个器件，必填列 `model,manufacturer,category`，其他列为参数名，值可写 `3.3V`；亦支持 `voltage`列数值＋`voltage_unit`列单位。UTF-8 CSV；中文必填列支持型号、厂商、类别。示例见examples目录。整个导入严格校验，不静默跳过坏行。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/tasks | 分页；status/review_status可筛选 |
| GET | /api/tasks/{id} | 状态、结果components、warnings、来源、审核历史 |
| GET | /api/tasks/{id}/source | 授权下载原上传文件 |
| POST | /api/tasks/{id}/retry | 仅failed；最多重试3次 |
| POST | /api/tasks/{id}/pause | 仅pending，可暂停排队 |
| POST | /api/tasks/{id}/resume | 仅paused，恢复排队 |
| POST | /api/tasks/{id}/terminate | 取消pending/paused/processing/failed任务 |
| DELETE | /api/tasks/{id} | admin，JSON `{"confirm":true}`；逻辑删除保留审计 |

status：pending/processing/success/failed/paused/cancelled。review_status：pending/approved/rejected。提取成功不代表已发布。对processing的terminate只阻止结果写回，不能取消已发给外部服务商的请求。

## 审核

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/audit/tasks | 待审核的成功任务分页 |
| GET | /api/audit/tasks/{id} | 审核详情 |
| POST | /api/audit/tasks/{id} | action=approve/reject，comment；可提交更正后的components数组 |
| GET | /api/audit/logs | 分页，可按task_id筛选，含原始与发布快照 |

以上仅admin/auditor；reject须填写comment。审批同一任务只能一次。更正数组须与原组件数一致，修正参数值/单位时应保留原source的page/row/snippet用于溯源。

已有同厂商同型号组件时，创建型任务不会直接覆盖。审批须额外提供 `confirm_overwrite:true`、`expected_revisions:{"组件ID":当前revision}`；原任务创建者没有该组件权限时仍禁止覆盖。组件更新型任务已在创建时绑定base_revision；旧版本审批返回409，应重新创建更新任务。

审批响应：`{"task_id":1,"review_status":"approved","component_ids":[1]}`。一批有任何失败，整批正式数据及审核记录都回滚。

## 正式元器件、范围查询与对比

`POST /api/search` 实现需求第3.4节“优先查询数据库，缺失再提取”：body为 `{"query":{"keyword":"R-1K","required_parameters":["voltage"]},"source":{"source_type":"manual","component":{...}}}`。query支持下表列表筛选，filters可直接传数组。已有满足条件的已发布数据返回200、mode=database且不创建任务；缺失并提供source则创建任务，202、mode=extraction；未提供source仅返回空列表和needs_extraction=true。文件缺失时应由用户在上传接口补充文件，不从任意磁盘路径读取。提取成功后仍须审核再查询。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/components | 查询已发布组件 |
| POST | /api/components | body为component对象；生成待审核人工任务，202 |
| GET | /api/components/{id} | 详情、parameters、已发布history |
| PUT | /api/components/{id} | 生成待审核的完整快照；未提供字段保留，提供parameters则整体替换 |
| DELETE | /api/components/{id} | admin；body `{"confirm":true}` |
| GET | /api/components/{id}/parameters | 参数数组 |
| POST | /api/components/{id}/parameters | 参数对象或parameters数组；合并后生成待审核任务 |
| GET | /api/components/compare?ids=1,2 | 2-10个不同ID；返回components和rows |

列表筛选：keyword（也支持q）、category、manufacturer_id、manufacturer（名称或简称）、package、filters。支持sort=component_id/model/category/manufacturer/created_time、order=asc/desc。关键词是转义后的字面模糊匹配，不将输入当SQL或LIKE通配符。

组合筛选filters是URL编码的JSON数组，各条件为AND。例如：

```json
[{"name":"voltage","min":"3.3V","max":"5V"},{"name":"resistance","min":"1kΩ","max":"10kΩ"}]
```

也可用数值与unit：`{"name":"voltage","min":3.3,"max":5,"unit":"V"}`。边界包含等号。至多10个范围条件；数值范围仅用于voltage/current/resistance/capacitance/frequency/power/tolerance，避免对未知量纲作错误比较。缺失参数不满足该范围条件。分页响应为items,total,page,page_size。

参数值为 `{name,value,value_num,value_text,unit,confidence,source,task_id}`。数值用value_num、文本用value_text，另一项为null。缺失参数没有记录；对比rows中用null及missing_component_ids表示，different用于前端高亮。

普通用户只能操作自己的组件和任务；admin/auditor可访问全部。**不能把审核员Token放在公开前端代码中**。

## 导出与日志

- `GET /api/export/components?format=csv|xlsx|json`：支持与列表相同筛选，导出所有匹配（最多10000），不受page限制。
- `GET /api/export/compare?ids=1,2&format=csv|xlsx|json`：对比导出。
- `GET /api/logs`：admin操作日志分页。
- `GET /api/health`：公开健康检查，不启动外部网络调用。

导出响应是文件，不是JSON包装；CSV/XLSX公式样式文本会加前导单引号，防止表格公式执行。JSON保留原始字符串。

HTTP错误：400输入/状态参数错误，401未认证，403无权限，404未找到，409重复/状态冲突，413文件过大，429登录限流，500内部错误。错误统一 `{code:HTTP状态,message:说明,data:null}`。

## 轮询流程（组员B）

提交任务后每1秒GET详情；pending/processing继续等待；failed展示error_msg与重试按钮；success展示result及review_status。不要用status=success显示“已入库”，应等review_status=approved。reject展示审核意见并允许用户新建修正任务。
