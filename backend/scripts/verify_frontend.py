"""Real-browser isolated full-stack verification. No production data changes."""
import sys,threading,tempfile,secrets,json,csv,io,functools
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import create_app
from backend.db import connect
from backend.worker import start_worker
from werkzeug.security import generate_password_hash
from waitress import create_server
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1];FRONT=ROOT.parent/'frontend';OUT=ROOT/'reports/frontend_integration';OUT.mkdir(exist_ok=True)
PDF=ROOT.parent/'DS5003'/'元件'/'Datasheets_original_copy_precise'
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def main():
    checks=[];errors=[]
    with tempfile.TemporaryDirectory(prefix='component-browser-') as tmp:
        app=create_app({'TESTING':True,'DATABASE':str(Path(tmp)/'test.sqlite3'),'UPLOAD_DIR':str(Path(tmp)/'uploads'),'PDF_EXTRACTION_MODE':'verbatim','CORS_ORIGINS':['http://127.0.0.1:5511']})
        password=secrets.token_urlsafe(18);db=connect(app.config['DATABASE'])
        with db:db.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',('browser-auditor',generate_password_hash(password),'auditor'))
        db.close();stop,worker=start_worker(app)
        api=create_server(app,host='127.0.0.1',port=5051);threading.Thread(target=api.run,daemon=True).start()
        http=ThreadingHTTPServer(('127.0.0.1',5511),functools.partial(Quiet,directory=str(FRONT)));threading.Thread(target=http.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel='msedge',headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1050},accept_downloads=True)
                context.add_init_script("window.COMPONENT_API_BASE='http://127.0.0.1:5051';")
                page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
                page.goto('http://127.0.0.1:5511/login.html');page.locator('#username').fill('browser-auditor');page.locator('#password').fill('wrong-password');page.locator('#loginButton').click();expect(page.locator('#loginMessage')).to_contain_text('Invalid username or password');checks.append('Invalid login shows error and allows retry');page.locator('#username').fill('browser-auditor');page.locator('#password').fill(password);page.locator('#loginButton').click();page.wait_for_url('**/dashboard.html');checks.append('Browser login')
                for index,name in enumerate(['ad8675.pdf','ad8421.pdf']):
                    page.goto('http://127.0.0.1:5511/pages/extraction.html')
                    page.locator('#uploadFile').set_input_files(str(PDF/'Analog'/name));page.locator('#fileUploadForm button[type=submit]').click()
                    expect(page.locator('#taskStatus')).to_have_text('success',timeout=60000)
                    expect(page.locator('#extractedResults .spec-record').first).to_be_visible();checks.append(name+': uploaded and displayed original records')
                    page.locator('#extractedResults .spec-section').first.scroll_into_view_if_needed();page.screenshot(path=str(OUT/f'{index+1}-extraction.png'))
                    page.goto('http://127.0.0.1:5511/pages/audit.html');page.get_by_role('button',name='Review',exact=True).first.click();expect(page.locator('#editableComponents .spec-record').first).to_be_visible()
                    if index==0:
                        page.get_by_label('Filter original specifications',exact=True).fill('Input Voltage Range')
                        row=page.locator('#editableComponents .spec-record').first
                        row.get_by_label('Min',exact=True).fill('-3.0');row.get_by_label('Max',exact=True).fill('+3.0');row.get_by_label('Unit',exact=True).fill('V');row.get_by_label('Conditions',exact=True).fill('VS = +/-5.0 V')
                        page.locator('#editableComponents .spec-record').nth(1).locator('.spec-include input').uncheck()
                        row.get_by_role('button',name='View page 3').click();expect(page.locator('dialog img')).to_be_visible(timeout=15000)
                        assert page.locator('dialog img').evaluate('(im)=>im.complete && im.naturalWidth>0')
                        page.screenshot(path=str(OUT/'3-source-page.png'));page.locator('dialog').get_by_role('button',name='Close',exact=True).click();checks.append('Authenticated source page rendered')
                        page.locator('#approveButton').click();expect(page.locator('#detailMessage')).to_contain_text('Confirm that you reviewed');checks.append('Approval blocked without confirmation')
                        page.get_by_label('Filter original specifications',exact=True).fill('')
                        page.get_by_label('Filter original specifications',exact=True).fill('Input Voltage Range');expect(row.get_by_label('Min',exact=True)).to_have_value('-3.0')
                        page.locator('#editableComponents').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'4-review-range.png'))
                    page.get_by_label('Category',exact=True).select_option('ic');page.locator('#confirmSpecifications').check();page.locator('#approveButton').click()
                    expect(page.locator('#detailMessage')).to_contain_text('approved successfully',timeout=15000);checks.append(name+': browser audit and publication')
                page.goto('http://127.0.0.1:5511/pages/components.html');page.get_by_role('row').filter(has_text='AD8675').get_by_role('button',name='View Details').click()
                page.get_by_label('Filter original specifications',exact=True).fill('Input Voltage Range');expect(page.locator('.spec-record').first).to_contain_text('Min: -3.0');expect(page.locator('.spec-record').first).to_contain_text('Max: +3.0');assert page.locator('.spec-record').count()==1;checks.append('Edited ranges and exclusions persisted')
                with page.expect_download() as dl:page.get_by_role('button',name='CSV',exact=True).click()
                dl.value.save_as(str(OUT/'component.csv'));data=list(csv.DictReader((OUT/'component.csv').open(encoding='utf-8-sig')));assert data and {x['model'] for x in data}=={'AD8675'};assert any(x['min_text']=="'-3.0" for x in data);checks.append('Single-component CSV includes reviewed range and no other component')
                page.goto('http://127.0.0.1:5511/pages/comparison.html');expect(page.locator('#componentSelectionBody input')).to_have_count(2)
                page.locator('#componentSelectionBody input').nth(0).check();page.locator('#componentSelectionBody input').nth(1).check();page.locator('#compareButton').click()
                expect(page.locator('#rawSpecificationComparison .spec-compare-column')).to_have_count(2);page.get_by_label('Filter comparison specifications',exact=True).fill('voltage')
                page.locator('#rawSpecificationComparison').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'5-comparison.png'));checks.append('Two components compared with original text and source pages')
                for fmt in ['csv','xlsx','json']:
                    with page.expect_download() as dl:page.locator(f'.comparison-export button[data-format={fmt}]').click()
                    dl.value.save_as(str(OUT/f'comparison.{fmt}'));assert (OUT/f'comparison.{fmt}').stat().st_size>100
                from openpyxl import load_workbook
                wb=load_workbook(OUT/'comparison.xlsx',read_only=True);values=list(wb.active.values);wb.close();assert len(values)>100;assert 'source_page' in values[0]
                assert any('Input Voltage Range' in str(row) for row in values)
                js=json.loads((OUT/'comparison.json').read_text(encoding='utf-8'));assert len(js['components'])==2;assert all(c['specifications'] for c in js['components']);checks.append('CSV, XLSX and JSON comparison downloads contain original records')
                # Standard numeric comparison must not depend on the optional raw-record panel.
                import requests,time
                auth={'Authorization':'Bearer '+page.evaluate("localStorage.getItem('token')")}
                for model,value in [('NUMERIC-A','5V'),('NUMERIC-B','3.3V')]:
                    response=requests.post('http://127.0.0.1:5051/api/tasks',headers=auth,json={'component':{'model':model,'manufacturer':'Test','category':'ic','parameters':[{'name':'voltage','value':value}]}})
                    task_id=response.json()['data']['task_id']
                    for _ in range(100):
                        task=requests.get(f'http://127.0.0.1:5051/api/tasks/{task_id}',headers=auth).json()['data']
                        if task['status']=='success':break
                        time.sleep(.1)
                    approved=requests.post(f'http://127.0.0.1:5051/api/audit/tasks/{task_id}',headers=auth,json={'action':'approve'})
                    assert approved.status_code==200,approved.text
                page.goto('http://127.0.0.1:5511/pages/comparison.html')
                for name in ['NUMERIC-A','NUMERIC-B']:
                    page.get_by_role('row').filter(has_text=name).locator('input[type=checkbox]').check()
                # Exercise even an older/missing viewer on numeric-only records.
                page.evaluate('window.SpecUI=undefined')
                page.locator('#compareButton').click()
                expect(page.locator('#comparisonBody')).to_contain_text('voltage')
                expect(page.locator('#comparisonBody')).to_contain_text('3.3')
                expect(page.locator('#comparisonResult')).to_be_visible()
                page.screenshot(path=str(OUT/'8-numeric-comparison.png'))
                checks.append('Numeric-only comparison works even when SpecUI is unavailable')
                # Regression for the user's ESP32 upload: nonempty raw records must be visible.
                page.goto('http://127.0.0.1:5511/pages/extraction.html')
                esp=PDF/'ESP32'/'esp32-s31-wroom-3_wroom-3u_datasheet_en.pdf'
                page.locator('#uploadFile').set_input_files(str(esp));page.locator('#fileUploadForm button[type=submit]').click()
                expect(page.locator('#taskStatus')).to_have_text('success',timeout=60000)
                expect(page.locator('#extractedResults .spec-section h3')).to_have_text('Original specifications (130)')
                expect(page.locator('#extractedResults')).to_contain_text('512 KB shared SRAM')
                expect(page.locator('#fileUploadForm button[type=submit]')).not_to_have_text('Uploading...')
                tid=page.locator('#taskId').inner_text()
                page.goto('http://127.0.0.1:5511/pages/extraction.html?task='+tid)
                expect(page.locator('#taskStatus')).to_have_text('success',timeout=15000)
                expect(page.locator('#extractedResults .spec-section h3')).to_have_text('Original specifications (130)')
                page.locator('#extractedResults').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'6-esp32-reopened.png'))
                checks.append('ESP32: 130 raw specifications visible; status correct; existing task reopened without re-upload')
                page.goto('http://127.0.0.1:5511/pages/tasks.html')
                page.get_by_role('button',name='View Details',exact=True).first.click()
                expect(page.locator('#detailComponents .spec-section h3')).to_have_text('Original specifications (130)')
                page.locator('#refreshDetail').click()
                expect(page.locator('#detailComponents .spec-section h3')).to_have_text('Original specifications (130)')
                page.goto('http://127.0.0.1:5511/pages/tasks.html?task='+tid)
                expect(page.locator('#detailComponents .spec-section h3')).to_have_text('Original specifications (130)')
                expect(page.locator('#detailComponents')).to_contain_text('0 standardized parameters · 130 original specification records')
                page.locator('#detailComponents').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'7-task-details-esp32.png'))
                checks.append('Task list details, refresh and direct task link all display 130 original specifications')

                # All-page regression: additional input types and failure/recovery paths.
                page.goto('http://127.0.0.1:5511/pages/extraction.html')
                page.locator('[data-tab=manualPanel]').click()
                page.locator('#manualModel').fill('MANUAL-REGRESSION');page.locator('#manualManufacturer').fill('Test');page.locator('#manualCategory').select_option('ic')
                page.locator('.parameter-name').fill('voltage');page.locator('.parameter-value').fill('3.3');page.locator('.parameter-unit').fill('V')
                page.locator('#manualForm button[type=submit]').click();expect(page.locator('#taskStatus')).to_have_text('success',timeout=15000)
                manual_id=page.locator('#taskId').inner_text();checks.append('Manual input creates a successful draft')
                page.goto('http://127.0.0.1:5511/pages/audit.html?task='+manual_id)
                expect(page.locator('#editableComponents')).to_contain_text('MANUAL-REGRESSION')
                page.locator('#rejectButton').click();expect(page.locator('#detailMessage')).to_contain_text('comment is required')
                page.locator('#reviewComment').fill('Regression rejection');page.locator('#rejectButton').click();expect(page.locator('#detailMessage')).to_contain_text('rejected successfully')
                page.goto('http://127.0.0.1:5511/pages/tasks.html?task='+manual_id);expect(page.locator('#detailAudit')).to_contain_text('Regression rejection');checks.append('Rejection requires comment and appears in task audit history')
                from openpyxl import Workbook
                book=Workbook();book.active.append(['model','manufacturer','category','voltage']);book.active.append(['XLSX-REGRESSION','Test','ic','5V']);buf=io.BytesIO();book.save(buf)
                for filename,mime,content in [('test.csv','text/csv',b'model,manufacturer,category,voltage\nCSV-REGRESSION,Test,ic,3.3V\n'),('test.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buf.getvalue())]:
                    page.goto('http://127.0.0.1:5511/pages/extraction.html');page.locator('#uploadFile').set_input_files({'name':filename,'mimeType':mime,'buffer':content});page.locator('#fileUploadForm button[type=submit]').click();expect(page.locator('#taskStatus')).to_have_text('success',timeout=15000)
                    checks.append(filename+': browser upload and extraction')
                page.goto('http://127.0.0.1:5511/pages/extraction.html');page.locator('#uploadFile').set_input_files({'name':'bad.exe','mimeType':'application/octet-stream','buffer':b'test'});page.locator('#fileUploadForm button[type=submit]').click();expect(page.locator('#fileMessage')).to_contain_text('Only PDF')
                page.locator('[data-tab=urlPanel]').click();page.locator('#sourceUrl').fill('http://127.0.0.1/private');page.locator('#urlForm button[type=submit]').click();expect(page.locator('#urlMessage')).to_have_class('form-message error');checks.append('Unsupported upload type and private URL rejected with visible errors')
                page.goto('http://127.0.0.1:5511/pages/extraction.html');page.locator('#uploadFile').set_input_files({'name':'broken.pdf','mimeType':'application/pdf','buffer':b'%PDF-broken'});page.locator('#fileUploadForm button[type=submit]').click();expect(page.locator('#taskStatus')).to_have_text('failed',timeout=15000)
                failed_id=page.locator('#taskId').inner_text();page.locator('#retryTask').click();expect(page.locator('#taskStatus')).to_have_text('failed',timeout=15000)
                page.goto('http://127.0.0.1:5511/pages/tasks.html?task='+failed_id);expect(page.locator('#detailError')).to_be_visible();page.locator('#detailTerminate').click();expect(page.locator('#taskBasicInfo')).to_contain_text('Cancelled');checks.append('Broken PDF failure, retry, error details and cancellation')
                # Stop only the isolated test worker to exercise queued controls deterministically.
                stop.set();worker.join(timeout=10)
                pending=requests.post('http://127.0.0.1:5051/api/tasks',headers=auth,json={'component':{'model':'QUEUE-CONTROL','manufacturer':'Test','category':'ic','parameters':[{'name':'voltage','value':'5V'}]}}).json()['data']['task_id']
                page.goto(f'http://127.0.0.1:5511/pages/tasks.html?task={pending}');page.locator('#detailPause').click();expect(page.locator('#detailResume')).to_be_visible();page.locator('#detailResume').click();expect(page.locator('#detailPause')).to_be_visible();page.locator('#detailTerminate').click();expect(page.locator('#taskBasicInfo')).to_contain_text('Cancelled');stop,worker=start_worker(app);checks.append('Pending task pause, resume and terminate')
                page.locator('#statusFilter').select_option('cancelled');page.locator('#applyFilters').click();expect(page.locator('#tasksTableBody')).to_contain_text('Cancelled');page.locator('#resetFilters').click();expect(page.locator('#statusFilter')).to_have_value('');checks.append('Task status filtering and reset')
                # Every sidebar destination and its common viewer bundle.
                for name in ['dashboard','components','extraction','tasks','comparison','audit']:
                    page.goto(f'http://127.0.0.1:5511/pages/{name}.html');assert page.evaluate('typeof window.SpecUI.render')=='function'
                    assert page.evaluate("parseServerDate('2026-11-11 13:00:00').toISOString()")== '2026-11-11T13:00:00.000Z'
                    page.wait_for_load_state('networkidle');page.screenshot(path=str(OUT/f'page-{name}.png'))
                    for a in page.locator('aside a').all():
                        href=a.get_attribute('href');assert (FRONT/'pages'/href).exists(),href
                checks.append('All six signed-in pages load the common viewer and have valid navigation links')
                # A comparison selection change must invalidate the previous result.
                page.goto('http://127.0.0.1:5511/pages/comparison.html')
                for name in ['NUMERIC-A','NUMERIC-B']:page.get_by_role('row').filter(has_text=name).locator('input[type=checkbox]').check()
                page.locator('#compareButton').click();expect(page.locator('#comparisonResult')).to_be_visible()
                page.get_by_role('row').filter(has_text='AD8675').locator('input[type=checkbox]').check();expect(page.locator('#comparisonResult')).to_be_hidden();checks.append('Changing selected components invalidates stale comparison/export results')
                page.goto('http://127.0.0.1:5511/pages/dashboard.html');page.locator('#logoutButton').click();page.wait_for_url('**/login.html');assert page.evaluate('localStorage.getItem("token")') is None
                
                for protected in ['dashboard','components','extraction','tasks','comparison','audit']:
                    page.goto(f'http://127.0.0.1:5511/pages/{protected}.html');page.wait_for_url('**/login.html')
                checks.append('Logout clears token; all six protected pages redirect to login')
                page.evaluate('localStorage.setItem("token","expired-invalid-token")');page.goto('http://127.0.0.1:5511/pages/dashboard.html');page.wait_for_url('**/login.html');checks.append('Expired token redirects to login')
                requests.post('http://127.0.0.1:5051/api/auth/register',json={'username':'regular-browser','password':password})
                page.locator('#username').fill('regular-browser');page.locator('#password').fill(password);page.locator('#loginButton').click();page.wait_for_url('**/dashboard.html')
                page.goto('http://127.0.0.1:5511/pages/audit.html');expect(page.locator('#listMessage')).to_contain_text('Access denied');checks.append('Ordinary user cannot access audit approval')

                assert not errors,errors
                context.close();browser.close()
        finally:
            stop.set();worker.join(timeout=10);api.close();http.shutdown();http.server_close()
    (OUT/'result.json').write_text(json.dumps({'passed':True,'checks':checks,'browser_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(checks,ensure_ascii=False))
if __name__=='__main__':main()
