export class ApiError extends Error {
  constructor(message, status, field) { super(message); this.status=status; this.field=field; }
}
export async function api(path, options={}) {
  const token=sessionStorage.getItem('token');
  const headers={'Content-Type':'application/json', ...(token?{Authorization:`Bearer ${token}`}:{})};
  let response;
  try { response=await fetch(`/api${path}`, {cache:'no-store',...options, headers}); }
  catch { throw new Error('无法连接服务器，请检查后端是否运行'); }
  const data=await response.json();
  if(!response.ok) {
    if(response.status===401) sessionStorage.removeItem('token');
    throw new ApiError(typeof data.detail==='string'?data.detail:'请求失败',response.status,data.field);
  }
  return data;
}
export const post=(path,data={})=>api(path,{method:'POST',body:JSON.stringify(data)});
export const escapeHtml=(v)=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function toast(message) {
  const el=document.querySelector('#toast'); el.textContent=message; el.style.display='block';
  clearTimeout(window.toastTimer); window.toastTimer=setTimeout(()=>el.style.display='none',3500);
}
export function bindForm(form, fn) {
  form.addEventListener('submit',async e=>{
    e.preventDefault(); const button=form.querySelector('[type=submit]');
    const error=form.querySelector('.error'); if(error) error.textContent='';
    button.disabled=true;
    try {await fn(new FormData(form));} catch(e) {if(error) error.textContent=e.message;else toast(e.message);}
    finally {button.disabled=false;}
  });
}
