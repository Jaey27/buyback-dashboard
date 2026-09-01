# -*- coding: utf-8 -*-
import sys, json, statistics as st
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0,r"C:\Users\pjy09\buyback-dashboard\scripts")
import price_source as ps

sess = ps._session()
print("### (1) 추정치 vs 레퍼런스 실측 일별 체결금액")
for f,code,isur,nm in [("_ref/raoni_api_005930.json","005930","00593","삼성전자"),
                       ("_ref/raoni_api_000660.json","000660","00066","SK하이닉스")]:
    d=json.load(open(f,encoding="utf-8"))
    truth={h["date"]:h["filled"]["amountThousandKrw"]*1000 for h in d["kind"]["history"] if h.get("filled")}
    rows=ps.fetch_exec_detail(code,isur,nm,"2026-08-01","2026-09-01",sess=sess)
    errs=[]
    print(f"  {nm}")
    for r in rows:
        t=truth.get(r["date"])
        if t is None or not r["amount_krw"]: continue
        e=(r["amount_krw"]-t)/t*100; errs.append(e)
        print(f"    {r['date']}  est={r['amount_krw']:>19,}  true={t:>19,}  err={e:+.3f}%  "
              f"est평단={r['avg_price']:,.0f} true평단={t/r['quantity']:,.0f}")
    print(f"    -> MAE {st.mean([abs(x) for x in errs]):.3f}%  max|e| {max(abs(x) for x in errs):.3f}%  "
          f"총액오차 {(sum(r['amount_krw'] for r in rows)-sum(truth[r['date']] for r in rows))/sum(truth[r['date']] for r in rows)*100:+.7f}%")

print()
print("### (2) 정확경로(kind_trddetail) 동작 확인 - KOSDAQ NE능률 053290")
rows=ps.fetch_exec_detail("053290","","NE능률","2026-08-01","2026-09-01",sess=sess)
for r in rows[:8]:
    print("   ",r["date"],f'{r["quantity"]:>8,}',f'{r["amount_krw"]:>14,}',f'{r["avg_price"]:>10,.0f}',
          "close",r["close"],r["amount_source"],"exact" if r["amount_exact"] else "EST")
print("    총",len(rows),"행, exact비율",sum(1 for r in rows if r['amount_exact']),"/",len(rows))

print()
print("### (3) 스냅샷 기록")
store=ps.snapshot_decl([("005930","00593","삼성전자"),("000660","00066","SK하이닉스")], sess=sess)
print(json.dumps(store,ensure_ascii=False,indent=1))
