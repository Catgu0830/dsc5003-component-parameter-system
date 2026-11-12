import sys,json,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import create_app

root=Path(__file__).resolve().parents[1]
app=create_app()
obj={'openapi':'3.0.3','info':{'title':'Component Parameter Extraction Backend','version':'1.0.0','description':'Group C backend. success extraction is not publication; audit approval is required. See docs/API.md for workflow and field details.'},'servers':[{'url':'http://127.0.0.1:5000'}],'security':[{'bearerAuth':[]}],'paths':{},'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer'}},'schemas':{
    'Parameter':{'type':'object','required':['name','value'],'properties':{'name':{'type':'string'},'value':{'oneOf':[{'type':'string'},{'type':'number'}]},'unit':{'type':'string','nullable':True},'confidence':{'type':'number','minimum':0,'maximum':1},'source':{'type':'object','properties':{'page':{'type':'integer'},'row':{'type':'integer'},'snippet':{'type':'string'}}}}},
    'ComponentInput':{'type':'object','required':['model','manufacturer','category'],'properties':{'model':{'type':'string'},'manufacturer':{'type':'string'},'category':{'type':'string','enum':['resistor','capacitor','diode','transistor','ic','inductor','other']},'parameters':{'type':'array','items':{'$ref':'#/components/schemas/Parameter'}}}},
    'Envelope':{'type':'object','required':['code','message','data'],'properties':{'code':{'type':'integer'},'message':{'type':'string'},'data':{'nullable':True}}}
}}}

def field(name,kind='string',**extra):return {'type':kind,**extra}
def jsonbody(properties,required=()):return {'required':True,'content':{'application/json':{'schema':{'type':'object','properties':properties,'required':list(required)}}}}
credentials=jsonbody({'username':field('username'),'password':field('password')},('username','password'))
for rule in app.url_map.iter_rules():
    if rule.endpoint=='static':continue
    path=re.sub(r'<(?:int:)?(\w+)>',r'{\1}',rule.rule)
    if '{action}' in path:
        paths=[path.replace('{action}',action) for action in ('pause','resume','terminate')]
    else:paths=[path]
    for path in paths:
        for method in sorted(rule.methods-{'HEAD','OPTIONS'}):
            operation={'operationId':rule.endpoint.replace('.','_')+'_'+method.lower()+(('_'+path.rsplit('/',1)[-1]) if '<action>' in rule.rule else ''),'tags':[path.split('/')[2]],'summary':rule.endpoint.replace('.',' / '),'responses':{str(s):{'description':description,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Envelope'}}}} for s,description in [(200,'Success'),(400,'Invalid request'),(401,'Missing or invalid token'),(403,'Forbidden'),(404,'Not found'),(409,'Conflict')]}}
            params=[{'name':name,'in':'path','required':True,'schema':{'type':'integer'}} for name in re.findall(r'{(\w+)}',path)]
            if method=='GET' and path in ('/api/components','/api/tasks','/api/users','/api/manufacturers','/api/logs','/api/audit/logs','/api/audit/tasks'):
                params += [{'name':n,'in':'query','schema':{'type':'integer','minimum':1,**({'maximum':100} if n=='page_size' else {})}} for n in ('page','page_size')]
            if path in ('/api/components','/api/export/components') and method=='GET':
                params += [{'name':n,'in':'query','schema':{'type':'string'}} for n in ('component_id','keyword','category','manufacturer','manufacturer_id','package','filters','sort','order')]
            if path in ('/api/components/compare','/api/export/compare'):params.append({'name':'ids','in':'query','required':True,'schema':{'type':'string'},'example':'1,2'})
            if path.startswith('/api/export/'):
                params.append({'name':'format','in':'query','schema':{'type':'string','enum':['csv','xlsx','json']}})
                operation['responses']['200']={'description':'Download file (not wrapped JSON)','content':{'text/csv':{'schema':{'type':'string','format':'binary'}},'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':{'schema':{'type':'string','format':'binary'}},'application/json':{'schema':{'type':'object'}}}}
            if path=='/api/tasks/{task_id}/source/page/{page_no}':operation['responses']['200']={'description':'Authorized source page image','content':{'image/png':{'schema':{'type':'string','format':'binary'}}}}
            if path=='/api/tasks/{task_id}/source':operation['responses']['200']={'description':'Download authorized source attachment','content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}}
            if params:operation['parameters']=params
            if path in ('/api/auth/login','/api/auth/register'):
                operation['security']=[];operation['requestBody']=credentials
            if path=='/api/auth/register' or path=='/api/users' and method=='POST':operation['responses']['201']={'description':'Created user'}
            if path=='/api/tasks/{task_id}/retry':operation['responses']['202']={'description':'Queued retry'}
            if path=='/api/tasks' and method=='GET':
                operation.setdefault('parameters',[]).extend([{'name':n,'in':'query','schema':{'type':'string'}} for n in ('status','review_status')])
            if path=='/api/audit/logs':operation.setdefault('parameters',[]).append({'name':'task_id','in':'query','schema':{'type':'integer'}})
            if path=='/api/health':operation['security']=[]
            if path=='/api/tasks' and method=='POST':
                operation['requestBody']=jsonbody({'source_type':field('source_type',enum=['manual','url']),'url':field('url'),'component':{'$ref':'#/components/schemas/ComponentInput'},'components':{'type':'array','items':{'$ref':'#/components/schemas/ComponentInput'}}})
                operation['responses']['202']={'description':'Queued task; not published'}
            if path=='/api/search':
                operation['requestBody']=jsonbody({'query':{'type':'object','description':'Component filters; filters and required_parameters may be arrays'},'source':{'type':'object','description':'Optional manual/URL task input on cache miss'}})
                operation['responses']['202']={'description':'Cache miss; extraction queued for review'}
            if path=='/api/tasks/upload':
                operation['requestBody']={
                    'required':True,
                    'content':{'multipart/form-data':{'schema':{
                        'type':'object','required':['file'],
                        'properties':{'file':{'type':'string','format':'binary'}}
                    }}}
                }
                operation['responses']['202']={'description':'Upload accepted; queued task'}
            if path=='/api/components' and method=='POST' or path=='/api/components/{component_id}' and method=='PUT':
                operation['requestBody']={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/ComponentInput'}}}};operation['responses']['202']={'description':'Queued draft; not published'}
                if method=='PUT':operation['requestBody']['content']['application/json']['schema']={'type':'object','description':'Partial component update; parameters, when supplied, replaces the entire parameter snapshot.','properties':obj['components']['schemas']['ComponentInput']['properties']}
            if path=='/api/components/{component_id}/parameters' and method=='POST':operation['requestBody']=jsonbody({'parameters':{'type':'array','items':{'$ref':'#/components/schemas/Parameter'}}},('parameters',));operation['responses']['202']={'description':'Queued parameter update draft'}
            if path=='/api/audit/tasks/{task_id}' and method=='POST':operation['requestBody']=jsonbody({'action':field('action',enum=['approve','reject']),'comment':field('comment'),'components':{'type':'array','items':{'$ref':'#/components/schemas/ComponentInput'}},'confirm_overwrite':{'type':'boolean'},'expected_revisions':{'type':'object','additionalProperties':{'type':'integer'}}},('action',))
            if method=='DELETE':operation['requestBody']=jsonbody({'confirm':{'type':'boolean','enum':[True]}},('confirm',))
            if path=='/api/users' and method=='POST':operation['requestBody']=jsonbody({'username':field('username'),'password':field('password'),'role':field('role',enum=['admin','auditor','user'])},('username','password'))
            if path=='/api/users/{user_id}' and method=='PUT':operation['requestBody']=jsonbody({'password':field('password'),'role':field('role',enum=['admin','auditor','user']),'disabled':{'type':'boolean'}})
            if path.startswith('/api/manufacturers') and method in ('POST','PUT'):operation['requestBody']=jsonbody({'name':field('name'),'website':field('website'),'aliases':{'type':'array','items':{'type':'string'}}},('name',))
            obj['paths'].setdefault(path,{})[method.lower()]=operation
(root/'docs/openapi.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
print('OpenAPI generated:',sum(len(v) for v in obj['paths'].values()),'operations')
