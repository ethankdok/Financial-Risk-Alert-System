/* Google login through the existing Firebase ID-token backend API. */
(function(){
"use strict";
const $=s=>document.querySelector(s);
const t=(zh,en)=>localStorage.getItem("ft-language")==="en"?en:zh;
async function login(){
 const button=$("#ft-google-signin"),error=$("#memberLoginError");if(!button)return;
 error.hidden=true;button.disabled=true;
 try{
  const configResponse=await fetch("/api/member/auth/web-config",{credentials:"same-origin",cache:"no-store"});
  if(!configResponse.ok)throw Error(t("目前預覽頁尚未接通 Google 登入設定。","Google login is not configured in this preview."));
  const response=await configResponse.json();if(!response.configured||!response.firebase)throw Error(t("Google 登入尚未啟用，請先設定 Firebase 專案。","Enable Firebase web configuration first."));
  const sdk="https://www.gstatic.com/firebasejs/10.14.1/";
  const [{initializeApp,getApps},{getAuth,GoogleAuthProvider,signInWithPopup}]=await Promise.all([import(sdk+"firebase-app.js"),import(sdk+"firebase-auth.js")]);
  const app=getApps().length?getApps()[0]:initializeApp(response.firebase);
  const auth=getAuth(app),provider=new GoogleAuthProvider();
  const result=await signInWithPopup(auth,provider);
  const token=await result.user.getIdToken();
  await MemberAuth.api("/api/member/auth/firebase-login",{method:"POST",body:JSON.stringify({id_token:token})});
  const wanted=new URLSearchParams(location.search).get("next")||"member.html";
  location.href=/^[a-z0-9_-]+\.html(?:\?[^#]*)?$/i.test(wanted)?wanted:"member.html";
 }catch(e){error.textContent=e.message||t("無法使用 Google 登入。","Google sign in failed.");error.hidden=false;}
 button.disabled=false;
}
document.addEventListener("DOMContentLoaded",()=>{$("#ft-google-signin")?.addEventListener("click",login);});
})();