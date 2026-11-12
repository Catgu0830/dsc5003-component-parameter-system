"""Populate the running LOCAL service through real role-checked APIs."""
import sys,json,time
from pathlib import Path
import requests
root=Path(__file__).resolve().parents[1]
credentials=json.loads((root/'instance/demo-credentials.json').read_text(encoding='utf-8'))
base='http://127.0.0.1:5000';session=requests.Session();session.trust_env=False
def call(method,path,token=None,**kw):
    response=session.request(method,base+path,headers={'Authorization':'Bearer '+token} if token else {},timeout=15,**kw)
    assert response.ok,(path,response.status_code,response.text[:200])
    return response.json()['data']
tokens={name:call('POST','/api/auth/login',json={'username':name,'password':credentials[name]['password']})['token'] for name in ('demo','auditor')}
if call('GET','/api/components',tokens['demo'])['total']==0:
    tasks=[]
    tasks.append(call('POST','/api/tasks',tokens['demo'],json=json.loads((root/'examples/manual.json').read_text(encoding='utf-8')))['task_id'])
    for filename in ('components.csv','demo_datasheet.pdf','components.xlsx'):
        with (root/'examples'/filename).open('rb') as f:
            tasks.append(call('POST','/api/tasks/upload',tokens['demo'],files={'file':(filename,f)})['task_id'])
    for tid in tasks:
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            task=call('GET',f'/api/tasks/{tid}',tokens['demo'])
            if task['status']=='success':break
            if task['status']=='failed':raise RuntimeError(task['error_msg'])
            time.sleep(.2)
        else:raise RuntimeError('Task polling timed out')
        call('POST',f'/api/audit/tasks/{tid}',tokens['auditor'],json={'action':'approve','comment':'Fictional course demonstration data, checked against included source'})
result={'base_url':base,'health':call('GET','/api/health'),'published_demo_components':call('GET','/api/components',tokens['demo'])['total'],'credentials_file':'instance/demo-credentials.json','pid':int((root/'instance/server.pid').read_text().strip()),'sample_data':'Fictional demonstration only'}
for token in tokens.values():call('POST','/api/auth/logout',token)
(root/'reports/local-service.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='credentials_file'},indent=2))
