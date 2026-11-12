"""Reproducible isolated benchmarks, never writes the application database."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import io,json,tempfile,time,statistics
from contextlib import closing
from werkzeug.security import generate_password_hash
from backend import create_app
from backend.auth import hash_token
from backend.db import connect,dump
from backend.worker import process_one

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temp:
    app=create_app({'TESTING':True,'DATABASE':str(Path(temp)/'bench.db'),'UPLOAD_DIR':str(Path(temp)/'uploads'),'EXTRACTION_MODE':'rules'})
    with closing(connect(app.config['DATABASE'])) as db, db:
        db.execute("INSERT INTO users(user_id,username,password_hash,role) VALUES(1,'bench',?,'admin')",(generate_password_hash('BenchmarkOnly123'),))
        db.execute("INSERT INTO tokens VALUES(?,1,'2099-01-01T00:00:00+00:00',CURRENT_TIMESTAMP)",(hash_token('benchmark'),))
        db.execute("INSERT INTO manufacturers VALUES(1,'Benchmark Manufacturer',NULL,'[]')")
        db.executemany('INSERT INTO components(component_id,model,category,manufacturer_id,owner_id) VALUES(?,?,?,?,?)',[(i,f'BENCH-{i:05d}','ic' if i%2 else 'resistor',1,1) for i in range(1,10001)])
        db.executemany('INSERT INTO parameters(component_id,parameter_name,value_num,unit,confidence,source_json) VALUES(?,?,?,?,?,?)',[(i,'voltage',float(i%50+1),'V',1,'{}') for i in range(1,10001)])
        db.executemany('INSERT INTO parameters(component_id,parameter_name,value_num,unit,confidence,source_json) VALUES(?,?,?,?,?,?)',[(i,'current',float(i%100+1)/1000,'A',1,'{}') for i in range(1,10001)])
    client=app.test_client();headers={'Authorization':'Bearer benchmark'}
    scenarios={'model':{'keyword':'BENCH-09'},'category_manufacturer':{'category':'ic','manufacturer':'Benchmark Manufacturer'},'combined_range':{'filters':json.dumps([{'name':'voltage','min':'3V','max':'12V'},{'name':'current','min':'5mA','max':'50mA'}])}}
    results={}
    for name,args in scenarios.items():
        timings=[]
        for _ in range(15):
            start=time.perf_counter();response=client.get('/api/components',query_string=args,headers=headers);timings.append((time.perf_counter()-start)*1000)
            assert response.status_code==200,response.json
        results[name]={'runs':15,'median_ms':round(statistics.median(timings),3),'max_ms':round(max(timings),3),'matched':response.json['data']['total']}
    csv='model,manufacturer,category,voltage,current\n'+''.join(f'IMPORT-{i},Import Manufacturer,ic,3.3V,20mA\n' for i in range(1000))
    start=time.perf_counter();response=client.post('/api/tasks/upload',data={'file':(io.BytesIO(csv.encode()),'1000.csv')},headers=headers)
    tid=response.json['data']['task_id'];assert process_one(app)
    processed=time.perf_counter()
    response=client.post(f'/api/audit/tasks/{tid}',json={'action':'approve'},headers=headers);assert response.status_code==200,response.json
    finished=time.perf_counter()
    results['batch_1000']={'components':len(response.json['data']['component_ids']),'upload_extract_seconds':round(processed-start,3),'review_publish_seconds':round(finished-processed,3),'total_seconds':round(finished-start,3)}
    with closing(connect(app.config['DATABASE'])) as db, db:
        results['integrity_check']=db.execute('PRAGMA integrity_check').fetchone()[0]
        assert db.execute('SELECT COUNT(*) FROM components').fetchone()[0]==11000
    results['scope']='Local Flask test client + SQLite; not a concurrent production load test. Generated synthetic records.'
    (root/'reports').mkdir(exist_ok=True)
    (root/'reports'/'benchmark.json').write_text(dump(results),encoding='utf-8')
    print(json.dumps(results,indent=2))
