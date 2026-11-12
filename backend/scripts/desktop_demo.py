"""Visible local API demonstration. Uses real HTTP; no password/token is displayed."""
import copy
import csv
import io
import json
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:5000'
credentials=json.loads((ROOT/'instance/demo-credentials.json').read_text(encoding='utf-8'))
session=requests.Session();session.trust_env=False
state={'model':'LIVE-DEMO-'+time.strftime('%m%d-%H%M%S'),'completed':False}
tokens={}
events=[]

root=tk.Tk();root.title('电子元器件参数提取系统 | 后端功能实机演示')
w=min(1240,root.winfo_screenwidth()-70);h=min(850,root.winfo_screenheight()-100)
root.geometry(f'{w}x{h}+35+35');root.configure(bg='#edf2f7')
style=ttk.Style();style.theme_use('clam')
style.configure('TFrame',background='#edf2f7')
style.configure('TLabel',background='#edf2f7',font=('Microsoft YaHei UI',11))
style.configure('Title.TLabel',font=('Microsoft YaHei UI',21,'bold'),foreground='#16334a')
style.configure('TButton',font=('Microsoft YaHei UI',12),padding=10)
style.configure('Treeview',font=('Microsoft YaHei UI',11),rowheight=35)
style.configure('Treeview.Heading',font=('Microsoft YaHei UI',11,'bold'))
outer=ttk.Frame(root,padding=20);outer.pack(fill='both',expand=True)
ttk.Label(outer,text='电子元器件参数提取 · 真实后端演示',style='Title.TLabel').pack(anchor='w')
ttk.Label(outer,text='本机 Flask + SQLite | 真实 HTTP 调用 | 演示数据为虚构 | 账号与密钥不显示').pack(anchor='w',pady=(5,14))
banner=tk.StringVar(value='准备就绪：点击“开始演示”，逐步展示提取、审核、查询和导出。')
ttk.Label(outer,textvariable=banner,foreground='#176746',wraplength=w-70).pack(anchor='w',pady=(0,12))
panels=ttk.Panedwindow(outer,orient='horizontal');panels.pack(fill='both',expand=True)
left=ttk.Frame(panels);right=ttk.Frame(panels);panels.add(left,weight=1);panels.add(right,weight=3)
labels=['1 连接服务、登录用户和审核员','2 上传 CSV 创建提取任务','3 查看提取草稿与单位归一化','4 验证审核前不可查询','5 验证普通用户无法审核','6 审核员修正为 5V 并批准','7 按 4V–6V 范围查询正式数据','8 对比两个器件、查看参数差异','9 导出实际 CSV 文件','10 检查审核记录并退出登录']
steps=tk.Listbox(left,font=('Microsoft YaHei UI',10),bg='#fff',fg='#33465a',selectbackground='#d9e9f5',selectforeground='#142e43',borderwidth=0,highlightthickness=0,width=38,activestyle='none')
steps.pack(fill='both',expand=True,padx=(0,14))
for label in labels:steps.insert('end','○ '+label)
summary=ttk.Treeview(right,columns=('field','value'),show='headings',height=5)
summary.heading('field',text='关键字段');summary.heading('value',text='当前实际结果');summary.column('field',width=150);summary.column('value',width=430)
summary.pack(fill='x',pady=(0,12))
for key,value in [('服务','等待连接'),('型号',state['model']),('任务状态','未创建'),('审核状态','未审核'),('电压','等待提取')]:summary.insert('', 'end',iid=key,values=(key,value))
details=tk.Text(right,wrap='word',font=('Consolas',10),bg='#142536',fg='#e1edf7',insertbackground='white',relief='flat',padx=12,pady=12)
details.pack(fill='both',expand=True)
controls=ttk.Frame(outer);controls.pack(fill='x',pady=(12,0))
button=ttk.Button(controls,text='开始演示');button.pack(side='left')
progress=ttk.Progressbar(controls,maximum=10,length=280);progress.pack(side='left',padx=18)
ttk.Label(controls,text='自动逐步执行，每一步约 4 秒；窗口会保留最终结果。').pack(side='left')

def show(title,data):
    details.delete('1.0','end');details.insert('end',title+'\n\n'+json.dumps(data,ensure_ascii=False,indent=2))
def field(key,value):summary.item(key,values=(key,value))
def api(method,path,role='demo',expected=200,**kw):
    headers={'Authorization':'Bearer '+tokens[role]} if role in tokens else {}
    response=session.request(method,BASE+path,headers=headers,timeout=15,**kw)
    events.append({'method':method,'path':path,'status':response.status_code})
    if response.status_code!=expected:raise RuntimeError(f'{method} {path}: HTTP {response.status_code} {response.text[:200]}')
    return response.json()['data']
def connect():
    health=api('GET','/api/health')
    for name in ('demo','auditor'):
        result=api('POST','/api/auth/login',role=name,json={'username':name,'password':credentials[name]['password']})
        tokens[name]=result['token']
    field('服务','HTTP 200 · 已登录 demo / auditor')
    show('健康检查与角色登录（密码、Token 均不展示）',health)
def upload():
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['model','manufacturer','category','voltage','current','package'])
    writer.writerow([state['model'],'Demo Electronics','ic','3300mV','200mA','SOT-23'])
    result=api('POST','/api/tasks/upload',expected=202,files={'file':('live_demo.csv',stream.getvalue().encode('utf-8'),'text/csv')})
    state['task_id']=result['task_id'];field('任务状态',f"任务 #{state['task_id']} · {result['status']}")
    show('POST /api/tasks/upload → HTTP 202',{'uploaded_row':{'model':state['model'],'voltage':'3300mV','current':'200mA'},'task':result})
def extracted():
    task=api('GET',f"/api/tasks/{state['task_id']}")
    if task['status'] in ('pending','processing'):return False
    if task['status']!='success':raise RuntimeError(task.get('error_msg'))
    state['component']=task['result']['components'][0]
    field('任务状态','success · 提取成功');field('审核状态','pending · 尚未发布');field('电压','3300mV → 3.3V；200mA → 0.2A')
    show('提取草稿：自动归一化并保留来源行号',task['result'])
def before_review():
    result=api('GET','/api/components',params={'keyword':state['model']})
    assert result['total']==0
    show('审核前查询正式库：0 条结果，草稿不会泄漏到正式参数',result)
def permission():
    response=session.post(BASE+f"/api/audit/tasks/{state['task_id']}",headers={'Authorization':'Bearer '+tokens['demo']},json={'action':'approve'},timeout=15)
    assert response.status_code==403
    events.append({'method':'POST','path':'/api/audit/tasks/{id}','status':403})
    show('普通用户尝试审核 → HTTP 403（符合预期）',response.json())
def approve():
    corrected=copy.deepcopy(state['component'])
    for parameter in corrected['parameters']:
        if parameter['name']=='voltage':parameter['value']=5;parameter['unit']='V'
    result=api('POST',f"/api/audit/tasks/{state['task_id']}",role='auditor',json={'action':'approve','components':[corrected],'comment':'实机演示：人工复核，将草稿电压3.3V修正为5V；虚构教学数据'})
    state['component_id']=result['component_ids'][0]
    field('审核状态','approved · 已正式发布');field('电压','人工修正后：5 V')
    show('审核员修正 + 批准：事务发布正式数据',result)
def search():
    result=api('GET','/api/components',params={'keyword':state['model'],'filters':json.dumps([{'name':'voltage','min':'4V','max':'6V'}])})
    assert result['total']==1
    show('组合查询：演示型号 + 电压 4V–6V，命中已审核的 5V 器件',result)
def compare():
    existing=api('GET','/api/components',params={'keyword':'DEMO-R1K'})['items'][0]
    result=api('GET','/api/components/compare',params={'ids':f"{state['component_id']},{existing['component_id']}"})
    show('跨器件参数对比：different 标记差异，null 标记缺失',{'models':[c['model'] for c in result['components']],'rows':result['rows']})
def export():
    response=session.get(BASE+'/api/export/components',params={'keyword':state['model'],'format':'csv'},headers={'Authorization':'Bearer '+tokens['demo']},timeout=15)
    assert response.status_code==200
    path=ROOT/'instance'/'desktop-demo-export.csv';path.write_bytes(response.content)
    state['export_file']=str(path)
    events.append({'method':'GET','path':'/api/export/components?format=csv','status':200})
    show('真实 CSV 已导出到本地文件',{'file':str(path),'bytes':len(response.content),'content':response.content.decode('utf-8-sig')})
def finish():
    logs=api('GET','/api/audit/logs',role='auditor',params={'task_id':state['task_id']})
    for role in ('demo','auditor'):api('POST','/api/auth/logout',role=role)
    state['completed']=True
    show('完整流程已完成：审核记录保留，演示登录已退出',{'model':state['model'],'task_id':state['task_id'],'component_id':state['component_id'],'audit_log':[{k:v for k,v in row.items() if k!='snapshot'} for row in logs['items']],'export_file':state['export_file'],'verification':'全部真实HTTP请求；无模拟成功响应'})
actions=[connect,upload,extracted,before_review,permission,approve,search,compare,export,finish]

def save_status():
    (ROOT/'instance/desktop-demo.json').write_text(json.dumps({**state,'events':events},ensure_ascii=False,indent=2),encoding='utf-8')
def run(index=0):
    if index>=len(actions):
        banner.set('演示完成：提取 → 权限拦截 → 审核修正 → 查询 → 对比 → 导出，全部通过。');save_status();return
    steps.selection_clear(0,'end');steps.selection_set(index);steps.see(index)
    banner.set(labels[index]);root.update_idletasks()
    try:
        result=actions[index]()
        if result is False:root.after(500,lambda:run(index));return
        steps.delete(index);steps.insert(index,'✓ '+labels[index]);steps.selection_set(index)
        progress['value']=index+1;save_status()
        root.after(4200,lambda:run(index+1))
    except Exception as exc:
        state['error']=str(exc);save_status();banner.set('演示暂停：'+str(exc));show('执行错误',{'error':str(exc)})
def begin():
    button.configure(state='disabled');run()
button.configure(command=begin)
root.lift();root.attributes('-topmost',True);root.after(2000,lambda:root.attributes('-topmost',False))
root.update_idletasks()
(ROOT/'instance/desktop-window.json').write_text(json.dumps({'button_center':[button.winfo_rootx()+button.winfo_width()//2,button.winfo_rooty()+button.winfo_height()//2],'window':[root.winfo_x(),root.winfo_y(),w,h]}),encoding='utf-8')
root.mainloop()
