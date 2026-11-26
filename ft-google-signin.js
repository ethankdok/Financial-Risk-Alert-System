/* Managed member authentication. All production passwords stay in Firebase. */
(function(){
"use strict";
const $=s=>document.querySelector(s);
const t=(zh,en)=>localStorage.getItem("ft-language")==="en"?en:zh;
let configPromise, sdkPromise, busy=false;
async function config(){
  if(!configPromise)configPromise=MemberAuth.api("/api/member/auth/web-config",{cache:"no-store"}).catch(e=>{configPromise=null;throw e;});
  return configPromise;
}
async function sdk(){
  if(!sdkPromise)sdkPromise=(async()=>{
    const c=await config();
    if(!c.configured||!c.firebase)throw Error(t("登入服務尚未設定。","Sign-in service is not configured."));
    const base="https://www.gstatic.com/firebasejs/10.14.1/";
    const [a,m]=await Promise.all([import(base+"firebase-app.js"),import(base+"firebase-auth.js")]);
    const app=a.getApps().find(x=>x.name==="fintrust-member")||a.initializeApp(c.firebase,"fintrust-member");
    const auth=m.getAuth(app);
    await m.setPersistence(auth,m.browserSessionPersistence);
    await auth.authStateReady();
    return {auth,m};
  })().catch(e=>{sdkPromise=null;throw e;});
  return sdkPromise;
}
function notice(msg,err=false){
  const error=$("#memberLoginError")||$("#memberRegisterError"), status=$("#memberAuthStatus");
  if(error){error.hidden=!err;error.textContent=err?msg:"";}
  if(status){status.hidden=err||!msg;status.textContent=err?"":msg;}
}
function message(e){
  const errors={
    "auth/invalid-credential":t("電子郵件或密碼錯誤。","Incorrect email or password."),
    "auth/wrong-password":t("電子郵件或密碼錯誤。","Incorrect email or password."),
    "auth/user-not-found":t("電子郵件或密碼錯誤。","Incorrect email or password."),
    "auth/email-already-in-use":t("此 Email 已有帳號，請使用原方式登入或重設密碼。","This email already has an account. Sign in or reset your password."),
    "auth/account-exists-with-different-credential":t("此 Email 已有帳號，請先以原方式登入，再至會員中心綁定。","Sign in with your existing method, then link Google in your account."),
    "auth/credential-already-in-use":t("此登入方式已屬於其他帳號，不能自動合併。","This credential belongs to another account; automatic merging is disabled."),
    "auth/popup-closed-by-user":t("已取消 Google 登入。","Google sign-in cancelled."),
    "auth/popup-blocked":t("請允許瀏覽器彈出視窗後重試。","Allow popups and try again."),
    "auth/unauthorized-domain":t("此網站尚未列入 Firebase 授權網域。","This domain is not authorized in Firebase."),
    "auth/too-many-requests":t("操作過於頻繁，請稍後再試。","Too many attempts; try again later."),
    "auth/requires-recent-login":t("請登出後重新登入，再設定登入方式。","Sign out and sign in again before linking."),
    "auth/weak-password":t("密碼強度不足。","Password is too weak."),
    "auth/invalid-email":t("請輸入有效的電子郵件。","Enter a valid email."),
    "auth/network-request-failed":t("網路連線失敗，請重試。","Network error; try again.")
  };
  return errors[e.code]|| (e.status?e.message:t("登入服務暫時無法完成操作，請重試。","Unable to complete authentication; try again."));
}
async function run(fn){
  if(busy)return;
  busy=true;notice("");
  const buttons=Array.from(document.querySelectorAll("#memberLoginForm button,#memberRegisterForm button,#ft-account-link button"));
  const disabled=buttons.map(b=>b.disabled);buttons.forEach(b=>b.disabled=true);
  try{await fn();}catch(e){notice(message(e),true);}
  finally{busy=false;buttons.forEach((b,i)=>b.disabled=disabled[i]);}
}
function next(){
  const n=new URLSearchParams(location.search).get("next")||"member.html";
  location.href=/^[a-z0-9_-]+\.html(?:\?[^#]*)?$/i.test(n)?n:"member.html";
}
async function establish(user){
  await user.reload();
  if(!user.emailVerified){
    $("#ft-resend-verification")?.removeAttribute("hidden");
    notice(t("請先完成 Email 驗證，再重新登入。","Verify your email, then sign in again."));
    return false;
  }
  await MemberAuth.api("/api/member/auth/firebase-login",{method:"POST",body:JSON.stringify({id_token:await user.getIdToken(true)})});
  return true;
}
async function google(){
  const {auth,m}=await sdk();
  const provider=new m.GoogleAuthProvider();provider.setCustomParameters({prompt:"select_account"});
  const result=await m.signInWithPopup(auth,provider);
  if(await establish(result.user))next();
}
async function emailLogin(form){
  const c=await config();
  if(!c.configured&&c.local_password_enabled){
    await MemberAuth.api("/api/member/auth/login",{method:"POST",body:JSON.stringify({email:form.email.value,password:form.password.value})});next();return;
  }
  const {auth,m}=await sdk();
  const r=await m.signInWithEmailAndPassword(auth,form.email.value.trim(),form.password.value);
  if(await establish(r.user))next();
}
async function register(form){
  const c=await config();
  if(!c.configured&&c.local_password_enabled){
    await MemberAuth.api("/api/member/auth/register",{method:"POST",body:JSON.stringify({email:form.email.value,password:form.password.value,display_name:form.display_name.value})});next();return;
  }
  const {auth,m}=await sdk();
  const r=await m.createUserWithEmailAndPassword(auth,form.email.value.trim(),form.password.value);
  await m.updateProfile(r.user,{displayName:form.display_name.value.trim()});
  await m.sendEmailVerification(r.user);
  await m.signOut(auth);
  form.reset();
  notice(t("已建立帳號並寄出驗證信。請驗證後返回登入。","Account created. Check your email to verify, then return to sign in."));
}
async function reset(){
  const email=$("#memberLoginForm").email.value.trim();
  if(!email||!$("#memberLoginForm").email.checkValidity()){notice(t("請先輸入有效的電子郵件。","Enter your email first."),true);return;}
  const {auth,m}=await sdk();
  try{await m.sendPasswordResetEmail(auth,email);}catch(e){if(e.code!=="auth/user-not-found")throw e;}
  notice(t("若此 Email 可使用密碼登入，將收到重設連結。","If this email supports password login, a reset link will be sent."));
}
async function resend(){
  const {auth,m}=await sdk();
  if(!auth.currentUser){notice(t("請先以 Email／密碼登入。","Sign in with email and password first."),true);return;}
  await m.sendEmailVerification(auth.currentUser);
  notice(t("已重寄驗證信。","Verification email sent."));
}
async function logout(){
  const c=await config();
  if(c.configured){const {auth,m}=await sdk();await m.signOut(auth);}
}
async function linkControls(){
  if(!$("#ft-account-link"))return;
  const c=await config();if(!c.configured)return;
  const {auth,m}=await sdk();
  const member=await MemberAuth.getMember();
  const user=auth.currentUser;
  if(!member||!user||user.uid!==member.uid||!user.emailVerified)return;
  $("#ft-account-link").hidden=false;
  const providers=new Set(user.providerData.map(p=>p.providerId));
  $("#ft-link-google").hidden=providers.has("google.com");
  $("#ft-link-password").hidden=providers.has("password");
  $("#ft-link-google").onclick=()=>run(async()=>{
    const provider=new m.GoogleAuthProvider();provider.setCustomParameters({prompt:"select_account"});
    const r=await m.linkWithPopup(user,provider);
    if(await establish(r.user))location.reload();
  });
  $("#ft-link-password").onsubmit=e=>{e.preventDefault();const password=e.currentTarget.password.value;run(async()=>{
    const r=await m.linkWithCredential(user,m.EmailAuthProvider.credential(user.email,password));
    if(await establish(r.user))location.reload();
  });};
}
window.FinTrustFirebase={logout};
document.addEventListener("DOMContentLoaded",()=>{
  $("#ft-google-signin")?.addEventListener("click",()=>run(google));
  $("#memberLoginForm")?.addEventListener("submit",e=>{e.preventDefault();const form=e.currentTarget;run(()=>emailLogin(form));});
  $("#memberRegisterForm")?.addEventListener("submit",e=>{e.preventDefault();const form=e.currentTarget;run(()=>register(form));});
  $("#ft-reset-password")?.addEventListener("click",()=>run(reset));
  $("#ft-resend-verification")?.addEventListener("click",()=>run(resend));
  if($("#memberLoginForm")||$("#memberRegisterForm"))config().then(c=>{if(c.configured)return sdk();if(c.local_password_enabled){if($("#ft-google-signin"))$("#ft-google-signin").hidden=true;if($("#ft-reset-password"))$("#ft-reset-password").hidden=true;}}).catch(()=>{});
  linkControls().catch(()=>{});
});
})();