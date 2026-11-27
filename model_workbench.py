"""Bounded, reproducible exhibition model lab. Synthetic training data are never financial evidence."""
from functools import lru_cache
from itertools import combinations
from math import factorial
from collections import Counter
import re
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import confusion_matrix, precision_score, recall_score, f1_score, average_precision_score, roc_auc_score, accuracy_score, silhouette_score
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.decomposition import NMF

FEATURES = ["DSRI", "TATA", "RSST", "JSD"]
SCENARIOS = {
    "A": [1.46, .094, .142, .39],
    "B": [.98, -.032, .027, .12],
    "C": [1.17, .027, .081, .24],
}
TEXTS = [
    "本公司持續強化內部控制制度，依照相關法令辦理資訊揭露。營業收入及現金流量維持穩定。",
    "本公司持續強化內部控制制度，依照相關法令辦理資訊揭露。營業收入及現金流量小幅成長。",
    "本公司依照相關法令辦理資訊揭露，持續改善內部控制制度與營運效率。",
    "市場需求下降，應收帳款回收期間延長，存貨增加，現金流量承受壓力。",
    "市場需求下降，存貨及應收帳款增加，營運現金流量減少。",
    "資金調度與應收帳款回收面臨挑戰，市場需求下降，存貨跌價風險增加。",
    "董事會調整經營策略，強化法令遵循，持續改善資訊揭露及內部控制制度。",
    "公司接獲主管機關調查通知，會計估計與收入認列需重新檢視。",
    "公司接獲主管機關調查通知，收入認列及會計估計需重新檢視。",
]
DEFAULT_NEWS = "限時加入投資群組，保證獲利，內線消息指出股價即將翻倍，請立即買進。"
DICTIONARY = {
    "獲利承諾": ["保證獲利","穩賺不賠","零風險","翻倍"],
    "急迫推銷": ["限時","立即買進","立即匯款","最後機會"],
    "非公開資訊": ["內線消息","獨家消息","未公開消息"],
    "法遵事件": ["主管機關調查","裁罰","起訴","重編"],
}
def smote(x,y,seed=17):
    rng=np.random.default_rng(seed)
    minor=x[y==1]; majority=int(sum(y==0))
    if len(minor)<2 or len(minor)>=majority:
        return x,y
    scale=np.maximum(minor.std(axis=0),1e-9)
    distance=np.sum(((minor[:,None,:]-minor[None,:,:])/scale)**2,axis=2)
    np.fill_diagonal(distance,np.inf)
    neighbors=np.argsort(distance,axis=1)[:,:min(5,len(minor)-1)]
    extra=[]
    for _ in range(majority-len(minor)):
        i=int(rng.integers(len(minor))); j=int(rng.choice(neighbors[i]))
        extra.append(minor[i]+rng.random()*(minor[j]-minor[i]))
    return np.vstack([x,extra]),np.concatenate([y,np.ones(len(extra),dtype=int)])

@lru_cache(maxsize=6)
def train(algorithm="lr",balance=True):
    rng=np.random.default_rng(20261127)
    n=360
    x=np.column_stack([rng.normal(1.04,.22,n),rng.normal(.005,.052,n),rng.normal(.05,.055,n),rng.uniform(.04,.45,n)])
    x[:,0]=np.clip(x[:,0],.3,2.2); x[:,2]=np.clip(x[:,2],-.1,.3)
    z=-3.05+2.3*(x[:,0]-1)+13*x[:,1]+9*x[:,2]+4*x[:,3]+rng.normal(0,.35,n)
    y=(rng.random(n)<1/(1+np.exp(-z))).astype(int)
    a,b,ya,yb=train_test_split(x,y,test_size=.25,stratify=y,random_state=22)
    before=[int(sum(ya==0)),int(sum(ya==1))]
    fitx,fity=smote(a,ya) if balance else (a,ya)
    options={"lr":make_pipeline(StandardScaler(),LogisticRegression(max_iter=1000,random_state=22)),
             "dt":DecisionTreeClassifier(max_depth=4,min_samples_leaf=8,random_state=22),
             "rf":RandomForestClassifier(n_estimators=40,max_depth=5,min_samples_leaf=5,random_state=22,n_jobs=1)}
    model=options[algorithm].fit(fitx,fity)
    p=model.predict_proba(b)[:,1]; pred=(p>=.5).astype(int)
    metrics={"accuracy":float(accuracy_score(yb,pred)),"precision":float(precision_score(yb,pred,zero_division=0)),
        "recall":float(recall_score(yb,pred,zero_division=0)),"f1":float(f1_score(yb,pred,zero_division=0)),
        "roc_auc":float(roc_auc_score(yb,p)),"pr_auc":float(average_precision_score(yb,p))}
    report={"algorithm":algorithm,"feature_names":FEATURES,"seed":20261127,"train_count":len(a),"test_count":len(b),
        "training_before":before,"training_after":[int(sum(fity==0)),int(sum(fity==1))],
        "test_distribution":[int(sum(yb==0)),int(sum(yb==1))],
        "training_preview":[{"sample":i+1,"features":[float(v) for v in row],"label":"Y" if label else "N"} for i,(row,label) in enumerate(zip(a[:12],ya[:12]))],
        "confusion_matrix":confusion_matrix(yb,pred,labels=[0,1]).tolist(),"metrics":metrics,"threshold":.5,"smote":balance}
    # 16 fixed training rows, not holdout observations, used for exact interventional Shapley values.
    return model,a[:16],report

def explain(model,background,row):
    n=len(row); values={}
    for k in range(n+1):
        for subset in combinations(range(n),k):
            z=background.copy()
            if subset:z[:,list(subset)]=np.asarray(row)[list(subset)]
            values[subset]=float(model.predict_proba(z)[:,1].mean())
    phi=[]
    for i in range(n):
        v=0.
        for k in range(n):
            for s in combinations([j for j in range(n) if j!=i],k):
                w=factorial(k)*factorial(n-k-1)/factorial(n)
                v+=w*(values[tuple(sorted((*s,i)))]-values[s])
        phi.append(v)
    return {"base_value":values[()],"prediction":values[tuple(range(n))],
            "contributions":[{"feature":name,"value":float(x),"shap":float(v)} for name,x,v in zip(FEATURES,row,phi)],
            "method":"Exact interventional Shapley; 16 training background rows; probability scale"}

def tokens(s):
    result=[]
    for w in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+",s.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+",w):
            result.extend([w[i:i+2] for i in range(len(w)-1)] or [w])
        else:result.append(w)
    return result

def text_analysis(a,b,news):
    c1,c2=Counter(tokens(a)),Counter(tokens(b)); vocab=sorted(c1.keys()|c2.keys())
    if not c1 or not c2: raise ValueError("兩期文字皆須包含可分析詞彙")
    p=np.array([c1[k]/sum(c1.values()) for k in vocab]);q=np.array([c2[k]/sum(c2.values()) for k in vocab]);m=(p+q)/2
    def kl(u):
        z=u>0
        return float(np.sum(u[z]*np.log2(u[z]/m[z])))
    v=TfidfVectorizer(analyzer=tokens).fit_transform([a,b])
    cosine=float((v[0]@v[1].T).toarray()[0,0])
    docs=TEXTS+[a,b]
    vectorizer=TfidfVectorizer(analyzer=tokens)
    mat=vectorizer.fit_transform(docs)
    topic_model=NMF(n_components=3,init="nndsvda",max_iter=500,random_state=22)
    weights=topic_model.fit_transform(mat)
    names=vectorizer.get_feature_names_out()
    topics=[{"topic":i+1,"terms":[str(names[j]) for j in row.argsort()[-6:][::-1]],"prior_weight":float(weights[-2,i]),"current_weight":float(weights[-1,i])} for i,row in enumerate(topic_model.components_)]
    choices=[]
    for k in range(2,6):
        km=KMeans(n_clusters=k,n_init=5,random_state=22).fit(mat)
        if 1<len(set(km.labels_))<len(docs):
            choices.append((float(silhouette_score(mat,km.labels_,metric="cosine")),k,km.labels_))
    best=max(choices,key=lambda z:z[0]); groups=[{"cluster":int(i),"document":j+1,"text":d} for j,(i,d) in enumerate(zip(best[2],docs))]
    hits=[{"category":cat,"matches":[w for w in words if w in news]} for cat,words in DICTIONARY.items()]
    count=sum(len(h["matches"]) for h in hits); maximum=sum(map(len,DICTIONARY.values()))
    return {"jsd":(kl(p)+kl(q))/2,"cosine":cosine,"token_counts":[sum(c1.values()),sum(c2.values())],
        "terms":[{"term":k,"prior":int(c1[k]),"current":int(c2[k]),"change":float(q[i]-p[i])} for i,k in sorted(enumerate(vocab),key=lambda v:abs(q[v[0]]-p[v[0]]),reverse=True)[:12]],
        "topics":topics,"clusters":groups,"cluster_count":best[1],"silhouette":best[0],"cluster_options":[{"k":k,"silhouette":s} for s,k,_ in choices],
        "word_counts":[{"term":k,"count":int(v)} for k,v in (c1+c2).most_common(24)],
        "news":{"text":news,"score":round(100*count/maximum,1),"hits":hits,"matched":count,"dictionary_size":maximum},
        "method":"Chinese character bigrams / word tokens; base-2 JSD; pairwise TF-IDF cosine; KMeans on demonstration corpus"}

def run_workbench(payload):
    algorithm=payload.get("algorithm","lr"); scenario=payload.get("scenario","A"); balance=payload.get("smote",True)
    if algorithm not in ("lr","dt","rf") or scenario not in SCENARIOS or not isinstance(balance,bool):raise ValueError("invalid model settings")
    a=payload.get("prior_text",TEXTS[0]);b=payload.get("current_text",TEXTS[3]);news=payload.get("news",DEFAULT_NEWS)
    if not all(isinstance(v,str) and len(v)<=4000 for v in (a,b,news)):raise ValueError("text length must be at most 4000")
    model,bg,report=train(algorithm,balance)
    row=SCENARIOS[scenario]; result=explain(model,bg,row)
    return {"data_mode":"synthetic_workbench","scenario":scenario,"training":report,"prediction":result,
        "comparison":[{"algorithm":m,**train(m,balance)[2]["metrics"]} for m in ("lr","dt","rf")],
        "text_analysis":text_analysis(a,b,news),"inputs":{"prior_text":a,"current_text":b,"news":news}}
