(function(){
  let cachedSession = null;

  async function api(url, options={}){
    const opts={credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})},...options};
    const res=await fetch(url,opts);
    let data={}; try{data=await res.json();}catch(e){}
    if(!res.ok){const err=new Error(data.error||`HTTP ${res.status}`);err.status=res.status;throw err;}
    return data;
  }

  async function getSession(){
    try{cachedSession=await api('/api/auth/me',{method:'GET'});return cachedSession;}catch(e){cachedSession=null;return null;}
  }

  async function login(username,password){
    try{cachedSession=await api('/api/auth/login',{method:'POST',body:JSON.stringify({username,password})});return cachedSession;}catch(e){return null;}
  }

  async function logout(){
    try{await api('/api/auth/logout',{method:'POST',body:'{}'});}catch(e){}
    cachedSession=null; location.href='admin-login.html';
  }

  async function requireAuth(){
    const s=await getSession();
    if(!s){const next=encodeURIComponent(location.pathname.split('/').pop()||'admin-dashboard.html');location.href='admin-login.html?next='+next;return null;}
    return s;
  }

  async function mountUser(){
    const s=cachedSession || await getSession(); if(!s)return;
    document.querySelectorAll('.admin-user').forEach(el=>{
      el.innerHTML=`<div class="admin-user-info"><strong>${escapeHtml(s.name)}</strong><span>${escapeHtml(s.role)} · ${escapeHtml(s.username)}</span></div><button class="admin-avatar" type="button" title="${escapeHtml(s.name)}">${escapeHtml((s.name||'?').charAt(0).toUpperCase())}</button><button class="admin-logout-btn" type="button">登出</button>`;
      el.querySelector('.admin-logout-btn').addEventListener('click',logout);
    });
  }

  async function logs(){try{return await api('/api/audit-logs',{method:'GET'})}catch(e){if(e.status===401)location.href='admin-login.html';return []}}
  async function clearLogs(){return api('/api/audit-logs',{method:'DELETE'});}
  function addLog(){ /* Flask API operations automatically create audit logs. */ }
  function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}

  window.AdminAuth={api,getSession,login,logout,requireAuth,mountUser,logs,clearLogs,addLog,escapeHtml};
})();
