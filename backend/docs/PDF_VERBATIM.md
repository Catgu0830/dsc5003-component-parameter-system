# PDF 原文规格 API

## 运行

安装 requirements.txt（或 requirements-lock.txt）并重新启动后端。默认 PDF_EXTRACTION_MODE=verbatim。EXTRACTION_MODE 继续用于网页及 legacy PDF。没有调用外部模型、没有上传资料到第三方，也没有使用原型目录中的机器专属依赖路径。

## 数据含义

这是原文候选提取，不是自动验证的电气规格。逐页扫描文本层，提取带数值单位的规格文字和具有可识别表头的表格行。没有 OCR、没有完整跨页表格重建、没有自动变体分配。

范围、正负号和描述留在 value_text。table_row 的 value_text 使用竖线分隔非空原文单元格；它不是已对齐的 Min/Typ/Max 数组。source.table_cells 与 table_headers 保存原文及坐标，供前端按原位置展示。空白列、多个等级列不得仅凭竖线顺序推断。min_text/typ_text/max_text/unit_text/conditions_text/applicability_text 可由审核员确认补充，自动提取默认不猜这些字段。

同名规格可重复，独立存储在 specifications 表。标准数值 parameters 表保持不变。数值筛选仅覆盖标准数值表；原文支持 keyword 检索和 JSON/CSV/XLSX 导出。当结果包含原文规格时，CSV/XLSX 切换为每条记录一行，避免静默遗漏。

## 上传和结果

继续 POST /api/tasks/upload，轮询 GET /api/tasks/{id}。

- result.method = pdf_verbatim
- result.components[].parameters = []（除非之后人工补充）
- result.components[].specifications[] 包含 label、value_text、可选列字段、kind、review_status、source。
- source.page 为 PDF 的 1-based 物理页码，非印刷页码。
- source.bbox、table_cells[].bbox 是 PDF 点坐标，左上原点。
- source.task_id 是原始上传任务，修改后仍保留，GET /api/tasks/{source.task_id}/source 依现有权限取得原文件。
- coverage 报告所有文本页的扫描情况和缺少可读文本的页；all_pages_scanned 不等于所有规格都已提取。
- document_identity 是未确认的文档/系列候选，category 默认 other；审核员应确认类别及具体型号。一个系列 PDF 不会被伪装成每个变体已核实的规格。

## 审核与发布

沿用 POST /api/audit/tasks/{id}，但包含原文规格的任务必须显式确认：

```json
{"action":"approve","confirm_specifications":true,"components":[{"model":"reviewed model or family","manufacturer":"reviewed manufacturer","category":"ic","parameters":[],"specifications":["完整的规格对象，结构见任务结果"]}]}
```

以上 components 是结构说明，不是可直接发送的示例值。可以省略 components 接受原草稿，但必须实际核查原文和型号后确认。支持审核员更改/删除规格；空 parameters 加空 specifications 被拒绝。原文审核和入库仍在原有事务内，审核前不对外发布。

前端现已接入原文规格表、分页搜索、页码查看、范围/条件和型号校正以及记录排除。审核页面要求勾选确认后才发送 confirm_specifications。GET /api/tasks/{task_id}/source/page/{page_no} 返回带权限校验的 PNG 页面预览。

GET /api/components/{id}、列表、对比 JSON 都返回 specifications。数值对比 rows 仍只包含标准参数，前端已新增原文并排区及共同文本过滤，不把标签相似的两行自动认作可比。CSV/XLSX 为逐记录格式，保留型号、范围文本、条件、来源页和上下文；JSON 保留完整结构。

## 资源限制与验收

文件上传上限仍为 20 MiB。默认通道最多 2500 页、2000 万提取字符和 5000 个候选，超过限制报错而非静默截断。扫描件、无候选和损坏文件不能记作成功。

批量验证不修改正式数据库：

```powershell
.venv\Scripts\python.exe scripts\validate_pdf_corpus.py "E:\CityU Files\DS5003\元件\Datasheets_original_copy_precise" --out reports/pdf_verbatim_release
.venv\Scripts\python.exe -m pytest -q
```

文件有候选的比例不是参数精度/召回率。准确率验收仍需独立字段标注集；不能用生成候选数量或成功任务数代替。
