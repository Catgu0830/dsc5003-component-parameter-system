"""Exercise real TCP/HTTP requests against Waitress with an isolated database."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import io,json,tempfile,threading,time,platform
from contextlib import closing
import requests
from waitress import create_server
from werkzeug.security import generate_password_hash
from backend import create_app
from backend.db import connect
from backend.worker import start_worker
from scripts.seed_demo import sample_pdf

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temp:
    app=create_app({'DATABASE':str(Path(temp)/'live.db'),'UPLOAD_DIR':str(Path(temp)/'uploads'),'EXTRACTION_MODE':'rules'})
    with closing(connect(app.config['DATABASE'])) as db,db:
        for username,role in [('admin','admin'),('auditor','auditor'),('demo','user')]:
            db.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',(username,generate_password_hash('SmokeOnly123!'),role))
    server=create_server(app,host='127.0.0.1',port=0,threads=4)
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    stop,worker=start_worker(app)
    base=f'http://127.0.0.1:{server.effective_port}';steps=[]
    session=requests.Session();session.trust_env=False
    def req(method,path,expected=200,token=None,**kw):
        headers={'Authorization':'Bearer '+token} if token else {}
        started=time.perf_counter();response=session.request(method,base+path,headers=headers,timeout=15,**kw)
        assert response.status_code==expected,(method,path,response.status_code,response.text[:300])
        steps.append({'method':method,'path':path,'status':response.status_code,'milliseconds':round((time.perf_counter()-started)*1000,2)})
        return response
    try:
        req('GET','/api/health')
        req('GET','/api/components',401)
        tokens={name:req('POST','/api/auth/login',json={'username':name,'password':'SmokeOnly123!'}).json()['data']['token'] for name in ('admin','auditor','demo')}
        user=tokens['demo'];auditor=tokens['auditor']
        task=req('POST','/api/tasks',202,user,json=json.loads((root/'examples/manual.json').read_text(encoding='utf-8'))).json()['data']['task_id']
        def wait(tid):
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                task=req('GET',f'/api/tasks/{tid}',token=user).json()['data']
                if task['status']=='success':return task
                assert task['status']!='failed',task['error_msg']
                time.sleep(.1)
            raise AssertionError('Worker timeout')
        wait(task)
        assert req('GET','/api/components',token=user).json()['data']['total']==0
        req('POST',f'/api/audit/tasks/{task}',403,user,json={'action':'approve'})
        cid=req('POST',f'/api/audit/tasks/{task}',token=auditor,json={'action':'approve'}).json()['data']['component_ids'][0]
        pdf=Path(temp)/'demo.pdf';sample_pdf(pdf)
        with pdf.open('rb') as f:tid=req('POST','/api/tasks/upload',202,user,files={'file':('demo.pdf',f,'application/pdf')}).json()['data']['task_id']
        wait(tid);req('POST',f'/api/audit/tasks/{tid}',token=auditor,json={'action':'approve'})
        with (root/'examples/components.csv').open('rb') as f:tid=req('POST','/api/tasks/upload',202,user,files={'file':('components.csv',f,'text/csv')}).json()['data']['task_id']
        wait(tid);res=req('POST',f'/api/audit/tasks/{tid}',token=auditor,json={'action':'approve'}).json()['data']
        another=res['component_ids'][0]
        query=json.dumps([{'name':'voltage','min':'3V','max':'60V'}])
        assert req('GET','/api/components',token=user,params={'filters':query}).json()['data']['total']==4
        assert req('POST','/api/search',token=user,json={'query':{'keyword':'DEMO-R1K','required_parameters':['resistance']}}).json()['data']['mode']=='database'
        req('GET',f'/api/components/compare?ids={cid},{another}',token=user)
        for kind in ('json','csv','xlsx'):req('GET','/api/export/components?format='+kind,token=user)
        req('GET','/api/logs',token=tokens['admin'])
        req('GET','/api/audit/logs',token=auditor)
        req('POST','/api/auth/logout',token=user)
        req('GET','/api/auth/me',401,user)
        with closing(connect(app.config['DATABASE'])) as db:
            integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        result={'passed':True,'http_requests':len(steps),'transport':'Real loopback HTTP with Waitress and background worker','python':platform.python_version(),'steps':steps,'integrity_check':integrity,'external_llm_called':False,'external_website_called':False}
        (root/'reports').mkdir(exist_ok=True)
        (root/'reports/http-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Real HTTP smoke passed: {len(steps)} requests; integrity={integrity}')
    finally:
        session.close();stop.set();worker.join(5)
        server.close();thread.join(5)
