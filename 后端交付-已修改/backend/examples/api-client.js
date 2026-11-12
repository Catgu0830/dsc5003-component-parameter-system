// Native browser JS integration example. Serve your page over HTTP on port 5500.
const API_BASE = 'http://127.0.0.1:5000';
let token = sessionStorage.getItem('componentToken');

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
    options = {...options, body: JSON.stringify(options.body)};
  }
  const response = await fetch(API_BASE + path, {...options, headers});
  const envelope = await response.json();
  if (!response.ok || envelope.code !== 0) throw new Error(envelope.message);
  return envelope.data;
}

export async function login(username, password) {
  const result = await api('/api/auth/login', {method:'POST', body:{username,password}});
  token = result.token;
  sessionStorage.setItem('componentToken', token);
  return result.user;
}

export async function logout() {
  try { await api('/api/auth/logout', {method:'POST'}); }
  finally { token = null; sessionStorage.removeItem('componentToken'); }
}

export function search({keyword = '', category, filters = []} = {}) {
  const params = new URLSearchParams({keyword, filters:JSON.stringify(filters)});
  if (category) params.set('category',category);
  return api('/api/components?' + params);
}

export function upload(file) {
  const form = new FormData(); form.append('file',file);
  return api('/api/tasks/upload', {method:'POST',body:form});
}

export async function waitForExtraction(taskId, {signal, timeoutMs=180000} = {}) {
  const deadline=Date.now()+timeoutMs;
  while (Date.now()<deadline) {
    if (signal?.aborted) throw new Error('Polling cancelled');
    const task=await api(`/api/tasks/${taskId}`, {signal});
    if (task.status==='failed') throw new Error(task.error_msg);
    if (['success','cancelled','paused'].includes(task.status)) return task;
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  throw new Error('Polling timed out; the task can still be checked in the task list');
}

export function review(taskId, action, comment='', components) {
  const body={action,comment}; if (components) body.components=components;
  return api(`/api/audit/tasks/${taskId}`, {method:'POST',body});
}

export async function downloadComponents(filters=[], format='xlsx') {
  const query=new URLSearchParams({filters:JSON.stringify(filters),format});
  const response=await fetch(API_BASE+'/api/export/components?'+query,{headers:{Authorization:`Bearer ${token}`}});
  if (!response.ok) throw new Error((await response.json()).message);
  const url=URL.createObjectURL(await response.blob());
  const link=document.createElement('a');link.href=url;link.download=`components.${format}`;
  link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
