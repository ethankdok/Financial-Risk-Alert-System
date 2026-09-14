(function(){
  let cachedMember=null;

  async function api(url,options={}){
    const opts={credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})},...options};
    const res=await fetch(url,opts);
    let data={};try{data=await res.json();}catch(e){}
    if(!res.ok){const err=new Error(data.error||`HTTP ${res.status}`);err.status=res.status;err.detail=data.detail;throw err;}
    return data;
  }

  function escapeHtml(value){
    return String(value??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  }

  async function getMember(){
    try{const data=await api('/api/member/me',{method:'GET'});cachedMember=data.member;return cachedMember;}catch(e){cachedMember=null;return null;}
  }

  async function requireMember(){
    const member=await getMember();
    if(!member){location.href='login.html?next='+encodeURIComponent(location.pathname.split('/').pop()||'member.html');return null;}
    return member;
  }

  async function logout(){
    try{await api('/api/member/auth/logout',{method:'POST',body:'{}'});}catch(e){}
    cachedMember=null;
    location.href='login.html';
  }

  function mountNav(member){
    document.querySelectorAll('[data-member-name]').forEach(el=>{el.textContent=member.display_name||member.email;});
    document.querySelectorAll('[data-member-email]').forEach(el=>{el.textContent=member.email;});
    document.querySelectorAll('[data-member-logout]').forEach(btn=>btn.addEventListener('click',logout));
  }

  window.MemberAuth={api,getMember,requireMember,logout,mountNav,escapeHtml};
})();
