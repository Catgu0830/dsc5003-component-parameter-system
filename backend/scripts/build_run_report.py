"""Generate the handoff report from recorded test/benchmark evidence.
Run with a Python environment containing requirements-report.txt.
"""
import json,platform,xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/'reports'
pdfmetrics.registerFont(TTFont('CN','C:/Windows/Fonts/msyh.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('CNB','C:/Windows/Fonts/msyhbd.ttc',subfontIndex=0))
body=ParagraphStyle('body',fontName='CN',fontSize=10,leading=16,spaceAfter=7,wordWrap='CJK')
title=ParagraphStyle('title',parent=body,fontName='CNB',fontSize=21,leading=29,spaceAfter=16,textColor=colors.HexColor('#173c57'))
head=ParagraphStyle('heading',parent=body,fontName='CNB',fontSize=13,leading=20,spaceBefore=8,spaceAfter=9,textColor=colors.HexColor('#173c57'))
small=ParagraphStyle('small',parent=body,fontSize=8.5,leading=13)
code=ParagraphStyle('code',parent=small,backColor=colors.HexColor('#f1f4f7'),borderPadding=6,spaceBefore=5,spaceAfter=9)
def p(text,style=body):return Paragraph(escape(str(text)),style)
def table(rows,widths):
    t=Table([[p(cell,small) for cell in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e5eef4')),('LINEBELOW',(0,0),(-1,0),0.6,colors.HexColor('#507080')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,1),(-1,-1),0.3,colors.HexColor('#dddddd'))]))
    return t
bench=json.loads((REPORTS/'benchmark.json').read_text(encoding='utf-8'))
http=json.loads((REPORTS/'http-smoke.json').read_text(encoding='utf-8'))
local=json.loads((REPORTS/'local-service.json').read_text(encoding='utf-8'))
web=json.loads((REPORTS/'public-web-probe.json').read_text(encoding='utf-8'))
xml=ET.parse(REPORTS/'pytest.xml').getroot();suite=xml.find('testsuite') if xml.tag!='testsuite' else xml
tests=int(suite.attrib['tests']);fail=int(suite.attrib.get('failures',0));errors=int(suite.attrib.get('errors',0));skipped=int(suite.attrib.get('skipped',0));seconds=float(suite.attrib['time'])
assert fail==errors==0
spec=json.loads((ROOT/'docs/openapi.json').read_text(encoding='utf-8'));operations=sum(len(v) for v in spec['paths'].values())
story=[p('电子元器件参数自动提取系统',title),p('组员 C · 后端运行报告',title),p('交付日期：2026-10-15（Asia/Shanghai）'),p('技术栈：Python 3.13 / Flask / SQLite / Waitress'),p('1. 运行结论',head),p(f'本地后端已启动，健康检查返回 HTTP 200。已通过 {tests} 项自动化测试及 {http["http_requests"]} 次真实回环 HTTP 请求，数据库完整性检查为 ok。当前演示库含 {local["published_demo_components"]} 个虚构器件，均通过提取任务和审核流程发布。'),p('完成范围是组员C负责的后端服务、数据库访问、文档解析与可配置大模型连接器；没有把前端页面或真实厂商提取准确率验收当作已完成。'),table([['交付项','当前状态'],['服务地址',local['base_url']+'/api/health'],['API数量',f'{operations} 个方法/路径操作（见OpenAPI）'],['任务执行','SQLite持久队列，HTTP请求不等待解析；后台线程执行'],['提取默认模式','rules：无需外部密钥，可运行教学样例'],['审核发布','提取成功只生成草稿；人工批准才写正式参数'],['外部LLM','连接器及模拟响应已测；无真实API密钥，未做真实服务调用'],['公网抓取探测','example.com HTML与robots实际抓取成功' if web['passed'] else '本次公网连通性探测未通过；详见public-web-probe.json']],[115,396]),Spacer(1,10),p('说明：当前服务为本机后台进程，机器重启或进程退出后需重新启动。本报告记录交付时状态，不保证该进程永久在线。',small),
PageBreak(),p('2. 功能实现与需求对应',title),table([['模块','已实现能力','说明'],['认证与用户','注册、登录、退出、Token撤销、角色、禁用用户','普通注册不能指定高权限角色；禁用/改密码可撤销Token'],['来源与提取','人工、文本PDF、URL、CSV、XLSX；LLM兼容接口','保留文件摘要、页码、行号、片段；不猜缺失关键字段'],['审核','查看草稿、参数修正、批准、驳回、审核意见','整批原子发布；原始/发布快照保留'],['数据管理','型号/厂商唯一、标准参数、所有者、版本号','更新重新走审核；旧版本不能覆盖新修订'],['查询与比较','关键词/别名、类别/厂商/封装、多个数值范围AND筛选','单位换算后比较；分页排序；缺失值及差异标记'],['数据库优先','POST /api/search先查正式库；缺失时可排队提取','支持required_parameters；不在GET查询中隐式写数据'],['导出与日志','CSV、XLSX、JSON；操作/审核日志','下载是文件响应；表格公式文本做转义'],['任务可靠性','状态、失败原因、重试、排队暂停/恢复、取消','原子领取、10分钟租约；取消后旧处理结果不能写回'],['备份','CLI在线SQLite备份，禁止覆盖已有备份','附件需另行备份']],[70,222,219]),p('必要的数据库补充',head),p('保留需求书六个核心实体，并加入tokens、operation_logs、component_tasks及所有权、数值/文本类型、单位、审核状态和修订号。原因：原始最简表结构不能独立表达“待审核草稿”“数值范围查询”和“仅访问本人数据”。实际DDL见backend/schema.sql。'),
PageBreak(),p('3. 实际验证记录',title),p('自动化与HTTP验证',head),p(f'pytest：{tests} tests，{fail} failures，{errors} errors，{skipped} skipped；本轮耗时 {seconds:.2f} 秒。原始证据为reports/pytest.xml。真实HTTP验证：{http["http_requests"]}个请求，使用Waitress实际TCP服务与后台worker，不是仅调用路由函数。'),p('覆盖：登录退出、权限越界、未审核不可见、参数修正、驳回、整批回滚、重复审批、旧版本冲突、已删除目标保护、文件类型/大小、CSV/XLSX/PDF解析、缺单位、SSRF/DNS验证、robots与跳转、LLM模拟成功/失败、并发任务领取、租约恢复、导出、备份、OpenAPI路由对应与数据库优先查询。'),p('1万条合成数据查询测试',head),table([['场景','中位数(ms)','最大值(ms)','匹配记录'],['型号模糊查找',bench['model']['median_ms'],bench['model']['max_ms'],bench['model']['matched']],['类别＋厂商',bench['category_manufacturer']['median_ms'],bench['category_manufacturer']['max_ms'],bench['category_manufacturer']['matched']],['双参数范围组合',bench['combined_range']['median_ms'],bench['combined_range']['max_ms'],bench['combined_range']['matched']]],[170,110,110,121]),p('每种场景执行15次，返回分页20项；数据含10000个组件及20000条数值参数。耗时包含Flask测试客户端、SQLite查询、权限检查和JSON序列化。该结果不是公网延迟或高并发生产压测承诺。',small),p('1000条CSV批量验证',head),p(f'上传＋提取 {bench["batch_1000"]["upload_extract_seconds"]} 秒，审核发布 {bench["batch_1000"]["review_publish_seconds"]} 秒，总计 {bench["batch_1000"]["total_seconds"]} 秒；正式入库1000条。此处为结构化合成CSV，不含真实LLM调用耗时，也不等于1000份PDF的解析速度。'),p('数据库备份与完整性',head),p('在线backup-db命令已实跑；备份库与测试库的PRAGMA integrity_check均返回ok。依赖pip check与Python compileall检查均通过。'),
PageBreak(),p('4. 安全与数据一致性',title),p('已落实的保护',head),p('密码以Werkzeug scrypt哈希保存；服务端只保存Token摘要，退出后失效。SQL参数绑定与排序白名单防注入；普通用户按owner/user_id授权。上传保存为随机文件名，限制类型、签名、大小、行数和工作簿膨胀；原文件下载也需授权。'),p('网页只允许HTTP(S)公网地址与80/443端口，拒绝内网/回环/元数据IP、用户信息和非公网解析结果。连接固定到验证过的IP；HTTPS仍校验证书域名；遵守robots，跨站跳转重新检查。LLM输入明确视为不可信文档，输出需合法JSON及可核对原文片段。'),p('发布、参数替换、版本提升、任务审核状态和审核日志在同一个事务中提交；批量任一条冲突会全部回滚。修改任务绑定创建时版本，避免后来的审核覆盖更新后的参数。'),p('验证中发现并修复的问题',head),table([['问题','处理'],['单位边界浮点误差','使用Decimal进行换算，再转数值存储；3300mV与3.3V比较一致'],['Windows备份/临时数据库文件占用','显式关闭sqlite连接，不把事务上下文误当连接关闭'],['批量任务的组件历史缺失','增加component_tasks关联，逐组件可追踪批量发布历史'],['已删除对象的旧更新任务可能变成新增','审批检查base_revision与目标存在性，禁止意外恢复已删除组件'],['重复表头导致列被静默覆盖','CSV/XLSX强制唯一表头与列/行上限']],[170,341]),p('边界',head),p('当前是课程原型：登录限流是单进程内存级；文件解析未做独立进程的强资源隔离；外网部署需要反向代理、HTTPS、限流与进程守护。任务取消不能撤回已发出的外部模型请求；逻辑删除保留附件用于审计，暂无自动保留期清理。'),
PageBreak(),p('5. 启动与团队交接',title),p('本机重新启动',head),p("cd 'E:\\CityU Files\\component-extractor-backend'",code),p('.venv\\Scripts\\python.exe run.py',code),p('首次在另一台机器运行：先创建.venv，安装requirements-lock.txt，复制.env.example为.env，运行scripts/seed_demo.py创建随机密码演示账户。完整命令见README.md。'),p('登录与前端联调',head),p('账户admin / auditor / demo的本地随机密码位于instance/demo-credentials.json，未写入报告或发布ZIP。前端以HTTP端口5500启动，调用localhost:5000；其他前端端口须加入.env的CORS_ORIGINS。接口约定见docs/API.md，OpenAPI见docs/openapi.json，浏览器JS示例见examples/api-client.js。'),p('重新验证',head),p('.venv\\Scripts\\python.exe -m pytest -q --junitxml=reports/pytest.xml',code),p('.venv\\Scripts\\python.exe scripts/benchmark.py',code),p('.venv\\Scripts\\python.exe scripts/http_smoke.py',code),p('尚待实际环境完成的验收',head),p('1）配置团队自己的LLM_API_BASE、LLM_API_KEY和LLM_MODEL，使用真实公开数据手册测提取质量与调用费用；本次不承诺80%准确率。2）由组员B接入前端，完成上传进度、审核页、差异高亮和下载交互。3）由组员D用真实器件数据执行验收并记录错误样本。'),p('未实现的低优先级项',head),p('OCR扫描PDF、保存常用筛选、相似器件推荐、详情PDF导出；后端已有修订历史与原始/发布快照，未提供单独图形化版本diff页面。'),p('交付文件',head),p('后端源码、锁定依赖、数据库DDL、OpenAPI、中文运行/API/架构文档、示例文件、自动化测试、原始测试与性能证据、本运行报告；发布ZIP不包含虚拟环境、密码、.env、数据库、源附件或Git内部文件。')]

def footer(c,d):
    c.setStrokeColor(colors.HexColor('#c5d3dd'));c.line(42,37,A4[0]-42,37)
    c.setFont('CN',8);c.setFillColor(colors.HexColor('#566675'))
    c.drawString(42,23,'组员C后端交付 | 2026-10-15 | 本机课程原型实测')
    c.drawRightString(A4[0]-42,23,str(d.page))
out=REPORTS/'后端运行报告.pdf'
SimpleDocTemplate(str(out),pagesize=A4,leftMargin=42,rightMargin=42,topMargin=38,bottomMargin=48,title='电子元器件参数自动提取系统 - 后端运行报告',author='Backend delivery').build(story,onFirstPage=footer,onLaterPages=footer)
manifest={'delivery_date':'2026-10-15','tests':tests,'failures':fail,'errors':errors,'skipped':skipped,'http_requests':http['http_requests'],'openapi_operations':operations,'benchmark':bench,'external_llm_verified':False,'local_base_url':local['base_url'],'demo_components':local['published_demo_components']}
(REPORTS/'delivery-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(out)
