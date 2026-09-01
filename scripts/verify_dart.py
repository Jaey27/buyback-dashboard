# -*- coding: utf-8 -*-
"""DART_SPEC.md 에 적은 수치를 스냅샷/API 로 재검증."""
import json, sys, datetime as dt
sys.path.insert(0, r"C:\Users\pjy09\buyback-dashboard\scripts")
sys.stdout.reconfigure(encoding="utf-8")
import dart_source as ds

snap = json.load(open(r"C:\Users\pjy09\buyback-dashboard\data\dart_snapshot.json", encoding="utf-8"))
ok = True
def chk(label, got, exp):
    global ok
    good = got == exp
    ok &= good
    print(f"  [{'OK ' if good else 'FAIL'}] {label}: got={got!r} exp={exp!r}")

EXP = {
 "005930": dict(rn="20260821000616", qty=53285968, amt=14999999992000,
                ps="2026-08-24", pe="2026-11-21", ltd="2026-11-20", lad="2026-11-19",
                tot=61, ela=7, rem=54, shares=5846278608, pre=79870794, d1=7321653,
                dl_trading=False),
 "000660": dict(rn="20260819000254", qty=24070000, amt=40004340000000,
                ps="2026-08-20", pe="2026-11-19", ltd="2026-11-19", lad="2026-11-18",
                tot=62, ela=9, rem=53, shares=730492365, pre=1625769, d1=2407000,
                dl_trading=True),
}
for t, e in EXP.items():
    c = snap["companies"][t]; p = c["current_program"]; st = c["current_status"]
    print(f"\n== {c['name']}")
    chk("rcept_no", p["rcept_no"], e["rn"])
    chk("plan_qty_ostk", p["plan_qty_ostk"], e["qty"])
    chk("plan_amt_ostk", p["plan_amt_ostk"], e["amt"])
    chk("period_start", st["period_start"], e["ps"])
    chk("deadline_disclosed", st["deadline_disclosed"], e["pe"])
    chk("deadline_is_trading_day", st["deadline_is_trading_day"], e["dl_trading"])
    chk("last_trading_day", st["last_trading_day"], e["ltd"])
    chk("last_application_day", st["last_application_day"], e["lad"])
    chk("trading_days_total", st["trading_days_total"], e["tot"])
    chk("trading_days_elapsed", st["trading_days_elapsed"], e["ela"])
    chk("trading_days_remaining", st["trading_days_remaining"], e["rem"])
    chk("common_total_adjusted", c["shares"]["common_total_adjusted"], e["shares"])
    chk("pre_program_treasury", c["pre_program_treasury_ostk"], e["pre"])
    chk("daily_limit_ostk", p["daily_limit_ostk"], e["d1"])
    chk("amended", c["current_amendment_check"]["amended"], False)
    chk("crosscheck_ok", c["shares"]["crosscheck_ok"], True)
    chk("trust_contracts", len(c["trust_contracts"]), 0)
    chk("trust_cancellations", len(c["trust_cancellations"]), 0)
    pct = round(e["qty"] / e["shares"] * 100, 4)
    chk("plan_pct_of_shares", c["current_program_pct_of_shares"], pct)
    chk("projected_after", c["projected_treasury_after"], e["pre"] + e["qty"])

# 삼성 취득 전 보유 = 원문 표 재계산
chk("삼성 79,870,794 = 91,828,987+73,465,072-12,063,951-73,359,314",
    91828987 + 73465072 - 12063951 - 73359314, 79870794)
# 하이닉스 발행총수 = 반기 + 증자
chk("하이닉스 712,702,365+17,790,000", 712702365 + 17790000, 730492365)
# 거래일 수기검산
td = ds.trading_days(dt.date(2026,8,24), dt.date(2026,11,20))
chk("삼성 거래일 수기", len(td), 61)
chk("삼성 8월 거래일", len([d for d in td if d.month==8]), 6)
chk("삼성 9월 거래일", len([d for d in td if d.month==9]), 20)
chk("삼성 10월 거래일", len([d for d in td if d.month==10]), 20)
chk("삼성 11월 거래일", len([d for d in td if d.month==11]), 15)
chk("2026-11-21 요일", dt.date(2026,11,21).weekday(), 5)   # 5=토
chk("2026-11-21 거래일?", ds.is_trading_day(dt.date(2026,11,21)), False)
chk("2026-11-19 거래일?", ds.is_trading_day(dt.date(2026,11,19)), True)
chk("2026-11 휴장일 수", len([d for d in ds.holiday_set(2026) if d.startswith("2026-11")]), 0)
chk("2026-09-28 거래일?", ds.is_trading_day(dt.date(2026,9,28)), True)
chk("휴장일 소스(2026)", ds.HOLIDAY_SOURCE.get(2026), "KRX 공식 (holidays_kr.json)")
# 비율 재현
chk("삼성 estk 비율 반올림", round(13603461/815974664*100, 1), 1.7)
chk("하이닉스 ostk 비율 반올림", round(1625696/730492365*100, 1), 0.2)
chk("삼성 ostk 비율 반올림", round(79870794/5846278608*100, 1), 1.4)

print("\n=== ALL OK ===" if ok else "\n=== FAILURES PRESENT ===")
sys.exit(0 if ok else 1)
