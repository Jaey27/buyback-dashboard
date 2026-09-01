# -*- coding: utf-8 -*-
"""buyback.json -> 자기완결 dashboard.html 렌더러.

- data/buyback.json 을 인라인 JSON 으로 박아넣는다.
- vendor/chart.umd.min.js 를 <script> 안에 인라인으로 삽입한다.
- 외부 요청 0건(폰트·CDN·이미지 전부 없음).

usage: python scripts/render.py [--out PATH] [--data PATH]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "buyback.json"
VENDOR_PATH = ROOT / "vendor" / "chart.umd.min.js"
OUT_PATH = ROOT / "dashboard.html"
# GitHub Pages 는 main 브랜치의 /docs 를 그대로 서빙한다. dashboard.html 과 같은
# 내용을 docs/index.html 로도 굽는다(바탕화면 바로가기가 가리키는 기존 경로는 유지).
DOCS_PATH = ROOT / "docs" / "index.html"

# 페이지 하단 stale 배너에 붙는 "어떻게 갱신하나" 안내문. 로컬 사본과 공개 페이지는
# 독자가 다르므로 문구도 달라야 한다(공개 페이지 독자는 스크립트를 돌릴 수 없다).
DEFAULT_HINT = "최신화하려면 프로젝트 폴더에서 갱신 스크립트(macOS: run_daily.sh · Windows: run_daily.bat)를 실행하세요."
DOCS_HINT = "이 페이지는 평일 18:30(KST) 자동 갱신됩니다. 이 안내가 계속 보이면 수집이 멈춘 것입니다."


def js_safe_json(obj) -> str:
    """<script> 안에 그대로 넣어도 안전한 JSON 문자열."""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    # JSON 구조 문자에는 < > & 가 없으므로 전부 문자열 내부다 -> \u 이스케이프해도 값이 보존된다.
    for raw, e in (
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        s = s.replace(raw, e)
    return s


def script_safe(src: str) -> str:
    """벤더 스크립트 안의 </script 시퀀스 차단."""
    return src.replace("</script", "<\\/script")


# --------------------------------------------------------------------------
# CSS
# --------------------------------------------------------------------------
CSS = r"""
:root{
  --hl-teal:#97FCE4; --hl-teal-dim:#50D2C1; --hl-teal-soft:rgba(151,252,228,.12);
  --hl-teal-border:rgba(151,252,228,.25);
  --bg-0:#061E20; --surface:rgba(15,53,55,.55);
  --text:#E8FFFA; --text-dim:#7FA8A4; --text-muted:#4F7773;
  --up:#F87171; --down:#60A5FA; --warn:#FBBF24;
  --shadow:0 4px 30px rgba(0,0,0,.4);
}
*{box-sizing:border-box;margin:0;padding:0}
/* 한국어 페이지 표준: 단어 중간에서 끊지 않는다('KB증권'이 'KB'/'증권'으로 쪼개짐 방지) */
body,.meta-grid .v,.cmp-table td,.cmp-rows .v,.notice,footer,.eta-sub,.card-sub,.stat-card .s{
  word-break:keep-all;overflow-wrap:anywhere}
html,body{
  background:radial-gradient(ellipse at top,#0F3537 0%,#061E20 60%,#03100F 100%);
  background-attachment:fixed;
  color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;
  min-height:100vh;-webkit-font-smoothing:antialiased;letter-spacing:-.01em;scrollbar-gutter:stable;
}
body::before{content:'';position:fixed;inset:0;
  background:radial-gradient(circle at 20% 10%,rgba(151,252,228,.08),transparent 40%),
             radial-gradient(circle at 80% 90%,rgba(80,210,193,.06),transparent 50%);
  pointer-events:none;z-index:0}
.container{position:relative;z-index:1;max-width:1100px;margin:0 auto;padding:32px 24px 48px}
@media (max-width:520px){.container{padding:20px 14px 36px}}

header{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px;flex-wrap:wrap;gap:16px}
.brand{display:flex;align-items:center;gap:12px;text-decoration:none;color:inherit}
.logo-dot{width:12px;height:12px;border-radius:50%;background:var(--hl-teal);box-shadow:0 0 16px var(--hl-teal);animation:pulse 2s ease-in-out infinite;flex-shrink:0}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.6;transform:scale(.85)}}
.brand h1{font-size:18px;font-weight:600}
.brand .sub{font-size:12px;color:var(--text-dim)}
.stamp{font-size:11px;color:var(--text-muted);font-variant-numeric:tabular-nums;text-align:right;line-height:1.6}

.top-nav-row{display:flex;justify-content:flex-start;margin:0 0 18px}
@media (max-width:768px){.top-nav-row{justify-content:center}}
.top-nav{display:inline-flex;align-items:center;gap:4px;background:rgba(151,252,228,.04);
  border:1px solid rgba(151,252,228,.10);border-radius:999px;padding:4px;max-width:100%;overflow-x:auto;scrollbar-width:none}
.top-nav::-webkit-scrollbar{display:none}
.nav-link{padding:6px 14px;border-radius:999px;font-size:13px;font-weight:500;color:var(--text-dim);
  text-decoration:none;transition:color .2s ease,background .2s ease;white-space:nowrap;flex-shrink:0;
  background:none;border:none;font-family:inherit;cursor:pointer;letter-spacing:-.01em}
.nav-link:hover{color:var(--hl-teal)}
.nav-link.active{color:var(--bg-0);background:var(--hl-teal);box-shadow:0 0 14px rgba(151,252,228,.28);font-weight:600}
.nav-link:focus-visible{outline:2px solid var(--hl-teal);outline-offset:2px}

/* 안내문은 정보 손실이 큰 문장(추정치 고지 등)이라 --text-dim(5.75:1)으로 올린다 */
.notice{font-size:12px;color:var(--text-dim);line-height:1.65;background:rgba(151,252,228,.04);
  border:1px dashed rgba(151,252,228,.16);border-radius:12px;padding:11px 14px;margin-bottom:18px}
.notice b{color:var(--text)}

/* ── 신선도 배너 ────────────────────────────────────────────── */
.stale{display:flex;align-items:flex-start;gap:10px;font-size:13px;line-height:1.6;
  border-radius:12px;padding:12px 15px;margin-bottom:16px;font-weight:600}
.stale code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
  background:rgba(0,0,0,.28);border-radius:5px;padding:1px 6px}
.stale.warn{color:var(--warn);background:rgba(251,191,36,.10);border:1px solid rgba(251,191,36,.34)}
.stale.bad{color:#FCA5A5;background:rgba(248,113,113,.12);border:1px solid rgba(248,113,113,.45)}
.stale .ico{font-size:15px;line-height:1.3;flex-shrink:0}
.stamp .stale-chip{display:inline-block;margin-top:3px;padding:1px 7px;border-radius:999px;
  font-size:10px;font-weight:700;color:var(--warn);background:rgba(251,191,36,.12);
  border:1px solid rgba(251,191,36,.30)}

.card{background:var(--surface);border:1px solid rgba(151,252,228,.08);border-radius:20px;padding:22px 24px;
  backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);box-shadow:var(--shadow);margin-bottom:18px}
@media (max-width:520px){.card{padding:18px 14px;border-radius:16px}}
.card-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.card-title{font-size:14px;font-weight:700}
.card-sub{font-size:11.5px;color:var(--text-muted);margin-top:3px}

.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}
.stat-card{background:var(--surface);border:1px solid rgba(151,252,228,.08);border-left-width:3px;
  border-left-color:var(--hl-teal-border);border-radius:14px;padding:14px 16px;
  backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
.stat-card .k{font-size:11px;color:var(--text-muted);margin-bottom:5px}
.stat-card .v{font-size:21px;font-weight:800;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.stat-card .u{font-size:11px;color:var(--text-muted);font-weight:500;margin-left:3px}
.stat-card .s{font-size:11px;color:var(--text-dim);margin-top:4px;font-variant-numeric:tabular-nums;line-height:1.5}
@media (max-width:780px){.cards{grid-template-columns:1fr 1fr}.stat-card .v{font-size:18px}}

/* ── 완료 예상 카드 ─────────────────────────────────────────── */
.eta-card{background:linear-gradient(135deg,rgba(151,252,228,.13),rgba(80,210,193,.05));
  border:1px solid var(--hl-teal-border);border-radius:20px;padding:20px 24px;margin-bottom:18px;
  box-shadow:0 0 40px rgba(151,252,228,.10)}
@media (max-width:520px){.eta-card{padding:18px 14px;border-radius:16px}}
.eta-top{display:flex;align-items:center;gap:8px;margin-bottom:14px;flex-wrap:wrap}
.eta-dot{width:8px;height:8px;border-radius:50%;background:var(--hl-teal);box-shadow:0 0 10px var(--hl-teal);
  animation:pulse 1.6s ease-in-out infinite;flex-shrink:0}
.eta-label{font-size:11px;font-weight:700;color:var(--hl-teal);letter-spacing:.04em}
.eta-asof{font-size:11px;color:var(--text-muted);margin-left:auto;font-variant-numeric:tabular-nums}
.eta-grid{display:grid;grid-template-columns:1fr 1fr 1.1fr;gap:18px;align-items:start}
.eta-cell.sep{padding-left:18px;border-left:1px solid rgba(151,252,228,.16)}
.eta-cap{font-size:10.5px;color:var(--text-muted);margin-bottom:4px;letter-spacing:.02em}
.eta-main{font-size:34px;font-weight:800;font-variant-numeric:tabular-nums;letter-spacing:-.03em;line-height:1.15}
.eta-main.pace{color:var(--hl-teal);text-shadow:0 0 22px rgba(151,252,228,.28)}
.eta-main.gap{font-size:42px;color:var(--warn);text-shadow:0 0 22px rgba(251,191,36,.35)}
.eta-main.gap.bad{color:var(--up);text-shadow:0 0 22px rgba(248,113,113,.35)}
.eta-main .unit{font-size:16px;font-weight:600;color:var(--text-dim);margin-left:4px}
.eta-sub{font-size:12px;color:var(--text-dim);margin-top:6px;line-height:1.55;font-variant-numeric:tabular-nums}
.eta-sub .em{color:var(--text)}
.eta-warnline{font-size:11px;color:var(--warn);margin-top:6px;line-height:1.5}
@media (max-width:980px){.eta-grid{grid-template-columns:1fr 1fr}
  .eta-cell.wide{grid-column:1/-1;padding-left:0;padding-top:14px;border-left:none;border-top:1px solid rgba(151,252,228,.16)}}
@media (max-width:640px){.eta-grid{grid-template-columns:1fr;gap:14px}
  .eta-cell.sep{padding-left:0;padding-top:14px;border-left:none;border-top:1px solid rgba(151,252,228,.16)}
  .eta-main{font-size:26px}.eta-main.gap{font-size:32px}}

.eta-bar{display:flex;height:20px;border-radius:999px;overflow:hidden;border:1px solid rgba(151,252,228,.12);
  background:rgba(151,252,228,.07);margin-top:18px}
.eta-seg{height:100%}
.eta-seg.pace{background:linear-gradient(90deg,var(--hl-teal-dim),var(--hl-teal));box-shadow:0 0 18px rgba(151,252,228,.35)}
.eta-seg.slack{background:repeating-linear-gradient(45deg,rgba(251,191,36,.30) 0 6px,rgba(251,191,36,.12) 6px 12px)}
.eta-seg.over{background:repeating-linear-gradient(45deg,rgba(248,113,113,.55) 0 6px,rgba(248,113,113,.20) 6px 12px)}
.eta-legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:9px;font-size:11px;color:var(--text-dim);
  font-variant-numeric:tabular-nums}
.eta-legend span{display:inline-flex;align-items:center;gap:6px}
.eta-legend i{width:9px;height:9px;border-radius:3px;display:inline-block;flex-shrink:0}
.eta-legend i.pace{background:var(--hl-teal)}
.eta-legend i.slack{background:rgba(251,191,36,.55)}
.eta-legend i.over{background:var(--up)}

.badge{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
.badge.ok{color:var(--hl-teal);background:rgba(151,252,228,.12);border:1px solid var(--hl-teal-border)}
.badge.tight{color:var(--warn);background:rgba(251,191,36,.10);border:1px solid rgba(251,191,36,.30)}
.badge.bad{color:#FCA5A5;background:rgba(248,113,113,.12);border:1px solid rgba(248,113,113,.40)}
.badge.none{color:var(--text-muted);background:rgba(151,252,228,.05);border:1px solid rgba(151,252,228,.12)}

/* ── 진행률 ─────────────────────────────────────────────────── */
.prog-wrap{margin:6px 0 4px;position:relative;padding-top:18px}
.prog-track{position:relative;height:26px;border-radius:999px;background:rgba(151,252,228,.07);
  border:1px solid rgba(151,252,228,.12);overflow:hidden}
.prog-track{display:flex}
.prog-fill{height:100%;background:linear-gradient(90deg,var(--hl-teal-dim),var(--hl-teal));
  box-shadow:0 0 18px rgba(151,252,228,.35);transition:width .6s ease}
/* 확정 구간 오른쪽에 이어 붙는 '오늘 신청분 반영 시' 잠정 구간 */
.prog-prov{height:100%;background:repeating-linear-gradient(45deg,
    rgba(151,252,228,.34) 0 5px,rgba(151,252,228,.13) 5px 10px);
  border-left:1px solid rgba(151,252,228,.45);transition:width .6s ease}
.prog-ticks{position:absolute;inset:0;pointer-events:none}
.prog-ticks i{position:absolute;top:0;bottom:0;width:1px;background:rgba(151,252,228,.16)}
.prog-ticks i.major{background:rgba(151,252,228,.30)}
.prog-scale{display:flex;justify-content:space-between;margin-top:4px;font-size:9.5px;color:var(--text-muted);font-variant-numeric:tabular-nums}
.prog-marker{position:absolute;top:18px;height:26px;width:2px;background:var(--warn);box-shadow:0 0 8px rgba(251,191,36,.6);z-index:5}
.prog-marker::after{content:attr(data-label);position:absolute;top:-16px;left:50%;transform:translateX(-50%);
  font-size:10px;color:var(--warn);white-space:nowrap}
.prog-head{position:absolute;top:31px;width:9px;height:9px;border-radius:50%;background:var(--hl-teal);
  box-shadow:0 0 10px var(--hl-teal);transform:translate(-50%,-50%);z-index:4;transition:left .6s ease;pointer-events:none}
.prog-head::after{content:'';position:absolute;inset:0;border-radius:50%;background:var(--hl-teal);
  animation:chartPulse 1.6s ease-out infinite}
.prog-legend{display:flex;justify-content:space-between;gap:12px;font-size:11px;color:var(--text-muted);
  margin-top:8px;font-variant-numeric:tabular-nums;flex-wrap:wrap}

.meta-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px 20px;font-size:12.5px;margin-top:20px}
.meta-grid .k{color:var(--text-muted);font-size:11px;margin-bottom:3px}
.meta-grid .v{font-variant-numeric:tabular-nums;line-height:1.45}

/* ── 차트 ───────────────────────────────────────────────────── */
.chart-pulse{position:absolute;width:9px;height:9px;border-radius:50%;background:var(--c,var(--hl-teal));
  box-shadow:0 0 8px var(--c,var(--hl-teal));transform:translate(-50%,-50%);pointer-events:none;z-index:3}
.chart-pulse::after{content:'';position:absolute;inset:0;border-radius:50%;background:var(--c,var(--hl-teal));
  animation:chartPulse 1.6s ease-out infinite}
@keyframes chartPulse{0%{transform:scale(1);opacity:.55}100%{transform:scale(3.6);opacity:0}}
.chart-box{position:relative;height:340px}
.chart-box.short{height:260px}
@media (max-width:768px){.chart-box{height:280px}.chart-box.short{height:230px}}

/* ── 표 ─────────────────────────────────────────────────────── */
.ep-table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
.ep-table th{text-align:right;font-size:11px;font-weight:600;color:var(--text-muted);padding:6px 10px;
  border-bottom:1px solid rgba(151,252,228,.12);white-space:nowrap}
.ep-table th:first-child,.ep-table td:first-child{text-align:left}
.ep-table td{padding:8px 10px;border-bottom:1px solid rgba(151,252,228,.05);text-align:right;white-space:nowrap}
.ep-table tr:last-child td{border-bottom:none}
.ep-table .cheap{color:var(--down)}
.ep-table .rich{color:var(--up)}
.ep-table .dim{color:var(--text-muted)}
.ep-table tr.prov td{background:rgba(151,252,228,.045)}
.prov-tag{font-size:9.5px;font-weight:700;color:var(--bg-0);background:var(--hl-teal-dim);border-radius:4px;
  padding:1px 4px;margin-left:4px;vertical-align:1px}
.est-tag{font-size:9.5px;font-weight:700;color:var(--warn);background:rgba(251,191,36,.12);
  border:1px solid rgba(251,191,36,.30);border-radius:4px;padding:0 3px;margin-left:4px;vertical-align:1px}
/* 가로 스크롤 컨테이너: 오른쪽 페이드로 '더 있다'는 걸 보이게 한다 */
.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;position:relative;
  -webkit-mask-image:linear-gradient(90deg,#000 0,#000 calc(100% - 34px),transparent 100%);
  mask-image:linear-gradient(90deg,#000 0,#000 calc(100% - 34px),transparent 100%)}
.table-scroll.no-fade{-webkit-mask-image:none;mask-image:none}
.scroll-hint{font-size:10.5px;color:var(--text-dim);margin-top:6px;text-align:right}
.badge.cancel{color:var(--hl-teal);background:rgba(151,252,228,.12);border:1px solid var(--hl-teal-border);
  font-size:11px;padding:3px 9px}
.badge.comp{color:var(--warn);background:rgba(251,191,36,.10);border:1px solid rgba(251,191,36,.30);
  font-size:11px;padding:3px 9px}
a.src{color:var(--hl-teal-dim);text-decoration:none;border-bottom:1px dotted rgba(80,210,193,.45)}
a.src:hover{color:var(--hl-teal);border-bottom-color:var(--hl-teal)}
a.src:focus-visible{outline:2px solid var(--hl-teal);outline-offset:2px}

/* ── 비교 뷰 ────────────────────────────────────────────────── */
.cmp-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px}
@media (max-width:780px){.cmp-grid{grid-template-columns:1fr}}
.cmp-name{font-size:15px;font-weight:700;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.cmp-name .code{font-size:11px;color:var(--text-muted);font-weight:500;font-variant-numeric:tabular-nums}
.cmp-big{font-size:30px;font-weight:800;letter-spacing:-.03em;font-variant-numeric:tabular-nums;margin:10px 0 2px;color:var(--hl-teal)}
.cmp-big .unit{font-size:14px;color:var(--text-dim);font-weight:600;margin-left:3px}
.cmp-rows{margin-top:14px;font-size:12.5px}
.cmp-rows div.r{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px solid rgba(151,252,228,.05)}
.cmp-rows div.r:last-child{border-bottom:none}
.cmp-rows .k{color:var(--text-muted);font-size:11.5px}
.cmp-rows .v{font-variant-numeric:tabular-nums;text-align:right}
.cmp-table td.lbl{text-align:left;color:var(--text-dim);font-size:11.5px}
.cmp-table td.win{color:var(--hl-teal);font-weight:700}
.cmp-table tr.hero td{background:rgba(151,252,228,.05);border-bottom-color:rgba(151,252,228,.14)}

/* 좁은 화면에서는 비교표를 행 단위 카드로 접어 두 회사 값을 동시에 보이게 한다 */
@media (max-width:640px){
  .cmp-table thead{display:none}
  .cmp-table,.cmp-table tbody,.cmp-table tr,.cmp-table td{display:block;width:100%}
  .cmp-table tr{border:1px solid rgba(151,252,228,.10);border-radius:12px;padding:9px 11px;margin-bottom:9px;
    background:rgba(151,252,228,.03)}
  .cmp-table td{border-bottom:none;padding:2px 0;text-align:left;white-space:normal}
  .cmp-table td.lbl{font-weight:700;color:var(--text-dim);margin-bottom:4px}
  .cmp-table td.a::before{content:attr(data-co)' · ';color:var(--text-muted);font-size:11px}
  .cmp-table td.b::before{content:attr(data-co)' · ';color:var(--text-muted);font-size:11px}
  .cmp-grid + .card .table-scroll{-webkit-mask-image:none;mask-image:none}
}

footer{margin-top:32px;padding-top:20px;border-top:1px solid rgba(151,252,228,.10);
  font-size:12px;color:var(--text-dim);line-height:1.75}
footer b{color:var(--text)}
footer ul{margin:8px 0 0 16px;font-size:12px}
footer li{margin-bottom:3px}
footer details{margin-top:14px}
footer summary{font-size:11px;font-weight:700;color:var(--text-muted);letter-spacing:.04em;
  cursor:pointer;list-style:none;display:inline-flex;align-items:center;gap:6px}
footer summary::-webkit-details-marker{display:none}
footer summary::before{content:'▸';font-size:9px;transition:transform .15s ease}
footer details[open] summary::before{transform:rotate(90deg)}
footer details ul{color:var(--text-muted);font-size:11px}
.foot-h{font-size:11px;font-weight:700;color:var(--text-dim);letter-spacing:.04em;margin-top:14px;margin-bottom:4px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media (prefers-reduced-motion:reduce){
  .logo-dot,.eta-dot,.chart-pulse::after,.prog-head::after{animation:none}
  .prog-fill{transition:none}
}
"""

# --------------------------------------------------------------------------
# JS
# --------------------------------------------------------------------------
JS = r"""
(function(){
'use strict';
var D = window.__BUYBACK__;
/* ★ 종목 목록은 데이터에서 유도한다(하드코딩하면 종목 교체 시 화면이 통째로 빈다). */
var ORDER = Object.keys(D.companies || {});
var DASH = '—';
var DART_DOC = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=';
var KIND_URL = 'https://kind.krx.co.kr/corpgeneral/treasurystk.do?method=loadInitPage';
var DART_API = 'https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS005';
/* ★ 갱신 방법 안내는 OS·배포처마다 다르다(Windows: run_daily.bat / macOS: run_daily.sh /
   공개 페이지: 자동 갱신). 렌더 시점에 주입된 D.refresh_hint 만 쓰고 하드코딩하지 않는다. */
var REFRESH_HINT = D.refresh_hint || '';

/* ── 포맷 (DESIGN_SPEC §7) ───────────────────────────────── */
function fmt(n){ return (n===null||n===undefined||isNaN(n)) ? DASH : Number(n).toLocaleString('ko-KR'); }
function fmtR(n){ return (n===null||n===undefined||isNaN(n)) ? DASH : Math.round(Number(n)).toLocaleString('ko-KR'); }
/* ★ NaN·Infinity 방어선: 0으로 나눈 비율이 'Infinity%'/'NaN%' 로 새어나가지 않게 한다. */
function pct(r,d){ return (r===null||r===undefined||!isFinite(r)) ? DASH : (r*100).toFixed(d==null?1:d)+'%'; }
function pctp(v,d){ return (v===null||v===undefined||!isFinite(v)) ? DASH : Number(v).toFixed(d==null?1:d)+'%'; }
/* 부호 붙은 거래일/‰p 표기 — null 이면 '−0' 대신 DASH */
function sgn(v,unit,d){
  if(v===null||v===undefined||!isFinite(v)) return DASH;
  var n=Number(v);
  return (n>=0?'+':'−')+(d==null? Math.abs(n) : Math.abs(n).toFixed(d))+(unit||'');
}
function won(n){
  if(n===null||n===undefined||!isFinite(n)) return DASH;
  if(n>=1e12) return (n/1e12).toFixed(n>=1e13?1:2)+'조';
  if(n>=1e8)  return Math.round(n/1e8).toLocaleString('ko-KR')+'억';
  if(n>=1e4)  return Math.round(n/1e4).toLocaleString('ko-KR')+'만';
  return fmt(n);
}
function shortBroker(b){
  if(!b) return '';
  return String(b).replace(/\([^)]*\)/g,'').split(',')
    .map(function(x){ return x.trim(); }).filter(Boolean).join(', ');
}
var WD = ['일','월','화','수','목','금','토'];
function wday(d){ if(!d) return ''; var p=d.split('-'); return WD[new Date(Date.UTC(+p[0],+p[1]-1,+p[2])).getUTCDay()]; }
function dlabel(d){ return d ? d+'('+wday(d)+')' : DASH; }
function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

/* ── 신선도(stale) 판정 ──────────────────────────────────────
   뷰어 시간대와 무관하게 '서울 오늘'을 구해 데이터 기준일과 대조한다.
   file:// 에서는 fetch 가 막혀 데이터 재적재가 불가능하므로 배너로 알린다. */
function seoulToday(){
  try{
    var f=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'});
    return f.format(new Date());               // 'YYYY-MM-DD'
  }catch(e){ return new Date().toISOString().slice(0,10); }
}
var HOLI = {};
(D.holidays_kr||[]).forEach(function(h){ HOLI[h]=1; });
function isBizDay(iso){
  var p=iso.split('-'), w=new Date(Date.UTC(+p[0],+p[1]-1,+p[2])).getUTCDay();
  return w!==0 && w!==6 && !HOLI[iso];
}
function bizDaysBetween(a,b){            /* (a, b] 안의 거래일 수. b<a 면 0 */
  if(!a||!b||b<=a) return 0;
  var p=a.split('-'), cur=new Date(Date.UTC(+p[0],+p[1]-1,+p[2])), n=0, guard=0;
  while(guard++ < 800){
    cur.setUTCDate(cur.getUTCDate()+1);
    var iso=cur.toISOString().slice(0,10);
    if(iso>b) break;
    if(isBizDay(iso)) n++;
  }
  return n;
}
function freshness(){
  var today=seoulToday(), as_of=D.as_of;
  if(!as_of) return {lag:null, today:today};
  return {lag: bizDaysBetween(as_of, today), today:today, as_of:as_of};
}
function staleBannerHtml(){
  var f=freshness();
  if(f.lag===null || f.lag<=0) return '';
  var cls = f.lag>=2 ? 'bad' : 'warn';
  var head = f.lag>=2
    ? '데이터가 '+f.lag+'거래일 지났습니다 — 지금 보이는 수치는 현재 값이 아닙니다.'
    : '전일 기준 데이터입니다.';
  return '<div class="stale '+cls+'" role="status">'
    + '<span class="ico" aria-hidden="true">'+(f.lag>=2?'⚠':'●')+'</span>'
    + '<span>'+head+'<br><span style="font-weight:500">기준일 '+esc(f.as_of)
    + ' · 오늘(서울) '+esc(f.today)+'. '+esc(D.refresh_hint||'')+'</span></span></div>';
}

/* ── 차트 공통 ───────────────────────────────────────────── */
var TEAL='#97FCE4', DIM='#50D2C1', WARN='#FBBF24', BLUE='#60A5FA';
var GRID='rgba(151,252,228,0.07)', TICK='#4F7773';
function baseOpts(extra){
  var o={responsive:true,maintainAspectRatio:false,animation:{duration:500},
    interaction:{mode:'index',intersect:false},
    plugins:{legend:{labels:{color:'#7FA8A4',boxWidth:10,font:{size:11}}},
      tooltip:{backgroundColor:'rgba(6,30,32,0.95)',borderColor:'rgba(151,252,228,0.2)',borderWidth:1}},
    scales:{}};
  return Object.assign(o, extra||{});
}
function axis(o){ return Object.assign({grid:{color:GRID},ticks:{color:TICK,font:{size:10}}}, o||{}); }

if(!window._bbPulseReg){
  window._bbPulseReg = true;
  Chart.register({
    id:'endPulse',
    afterDatasetsDraw:function(chart){
      var wrap=chart.canvas.parentNode, area=chart.chartArea;
      if(!wrap||!area) return;
      chart._pulseDots=chart._pulseDots||{};
      var ctx=chart.ctx, used={};
      chart.data.datasets.forEach(function(ds,di){
        if(!ds.pulse) return;
        var meta=chart.getDatasetMeta(di);
        if(!meta||meta.hidden||!meta.data||!meta.data.length) return;
        var k=ds.data.length-1;
        while(k>=0 && (ds.data[k]==null)) k-=1;
        if(k<0||!meta.data[k]) return;
        var x=meta.data[k].x, y=meta.data[k].y;
        if(!isFinite(x)||!isFinite(y)) return;
        used[di]=true;
        ctx.save(); ctx.setLineDash([3,4]); ctx.lineWidth=1; ctx.globalAlpha=.32;
        ctx.strokeStyle=ds.borderColor||ds.backgroundColor;
        ctx.beginPath(); ctx.moveTo(area.left,y); ctx.lineTo(area.right,y); ctx.stroke(); ctx.restore();
        var dot=chart._pulseDots[di];
        if(!dot){ dot=document.createElement('div'); dot.className='chart-pulse'; wrap.appendChild(dot); chart._pulseDots[di]=dot; }
        dot.style.setProperty('--c', ds.borderColor||ds.backgroundColor);
        dot.style.left=x+'px'; dot.style.top=y+'px'; dot.style.display='';
      });
      Object.keys(chart._pulseDots).forEach(function(k){ if(!used[k]) chart._pulseDots[k].style.display='none'; });
    },
    afterDestroy:function(chart){
      if(!chart._pulseDots) return;
      Object.keys(chart._pulseDots).forEach(function(k){ chart._pulseDots[k].remove(); delete chart._pulseDots[k]; });
    }
  });
}

var live=[];
function killCharts(){ live.forEach(function(c){ try{c.destroy();}catch(e){} }); live=[]; }
function mk(id,cfg){ var c=document.getElementById(id); if(!c) return; live.push(new Chart(c,cfg)); }

/* ── 조각 ────────────────────────────────────────────────── */
function ticksHtml(){
  var t='';
  for(var g=10; g<=90; g+=10) t += '<i class="'+(g===50?'major':'')+'" style="left:'+g+'%"></i>';
  return t;
}
function scaleHtml(){
  var s='';
  for(var v=0; v<=100; v+=10) s += '<span>'+v+'</span>';
  return s;
}
function verdictBadge(v, gapBd){
  var code=(v&&v.code)||'none', cls='none', gl='●';
  if(code==='ok'){ cls='ok'; gl='✔'; }
  else if(code==='tight'){ cls='tight'; gl='⚠'; }
  else if(code==='unlikely'||code==='impossible'){ cls='bad'; gl='✖'; }
  else if(code==='ended'){ cls='none'; gl='■'; }
  var txt = gl+' '+((v&&v.label)||'판정 불가');
  return '<span class="badge '+cls+'">'+esc(txt)+'</span>';
}
/* 취득 목적: 소각(발행주식수 실제 감소 → EPS 상승) vs 보상 재원(감소 없음) */
function purposeBadge(p){
  if(p.is_cancellation===true)  return '<span class="badge cancel">소각 · 주식수 감소</span>';
  if(p.is_cancellation===false) return '<span class="badge comp">보상 재원 · 소각 없음</span>';
  return '<span class="badge none">소각 여부 미상</span>';
}
/* 확정 진행 구간 + 오늘 신청분 반영 잠정 구간 */
function progBarHtml(v, opts){
  opts = opts || {};
  var prog=v.progress_ratio||0, prov=v.provisional_ratio;
  var pw=Math.max(0,Math.min(100,prog*100));
  var vw=(prov!=null)? Math.max(0,Math.min(100,prov*100)-pw) : 0;
  var head=Math.min(100, pw+vw);
  var aria='취득 진행률 '+pct(prog)+(prov!=null? ', 오늘 신청 반영 시 '+pct(prov):'')
    +(opts.elapsed!=null? ', 일정 경과 '+pct(opts.elapsed):'');
  return '<div class="prog-track" role="img" aria-label="'+aria+'">'
    + '<div class="prog-fill" style="width:'+pw+'%"></div>'
    + (vw>0? '<div class="prog-prov" style="width:'+vw+'%" title="오늘 신청분이 전량 체결되면 도달할 진행률(잠정)"></div>':'')
    + '<div class="prog-ticks">'+ticksHtml()+'</div></div>'
    + (opts.elapsed!=null? '<div class="prog-marker" data-label="일정 '+pct(opts.elapsed)+'" style="left:'+Math.min(100,opts.elapsed*100)+'%"></div>':'')
    + '<div class="prog-head" style="left:'+head+'%"></div>';
}
function provLegend(v){
  if(v.provisional_ratio==null) return '';
  return ' <span style="color:var(--hl-teal-dim)">＋ 오늘 신청 '+fmt(v.provisional_applied)
    + '주 반영 시 '+pct(v.provisional_ratio)+' (잠정)</span>';
}
function paceBadge(gapPp){
  if(gapPp===null||gapPp===undefined) return '<span class="badge none">● 체결 집계 전</span>';
  var ahead = gapPp >= 0;
  return '<span class="badge '+(ahead?'ok':'tight')+'">'+(ahead?'▲ 일정보다 앞섬 ':'▼ 일정보다 뒤짐 ')
    + Math.abs(gapPp).toFixed(1)+'%p</span>';
}

/* ── 완료 예상 카드 (사용자 핵심 요구) ── */
function etaCardHtml(co){
  var v=co.derived, p=co.program;
  var bdl=v.business_days_left, need=v.pace_eta_business_days, slack=v.pace_margin_business_days;
  var over = (need!=null && bdl!=null && need>bdl);
  var paceSeg = (need==null) ? 0 : Math.max(0, Math.min(need, bdl==null?need:bdl));
  var slackSeg = (slack==null||slack<0) ? 0 : slack;
  var overSeg = over ? (need-bdl) : 0;
  var bar='';
  if(need!=null){
    bar = '<div class="eta-bar" role="img" aria-label="남은 거래일 '+bdl+'일 중 페이스 소요 '+need+'거래일, 여유 '+slack+'거래일">'
      + '<div class="eta-seg pace" style="flex:'+paceSeg+'"></div>'
      + (slackSeg? '<div class="eta-seg slack" style="flex:'+slackSeg+'"></div>':'')
      + (overSeg? '<div class="eta-seg over" style="flex:'+overSeg+'"></div>':'')
      + '</div>'
      + '<div class="eta-legend">'
      + '<span><i class="pace"></i>페이스 소요 '+need+'거래일 → '+esc(v.pace_eta_date)+'</span>'
      + (slackSeg? '<span><i class="slack"></i>마감까지 여유 '+slackSeg+'거래일</span>':'')
      + (overSeg? '<span><i class="over"></i>기한 초과 '+overSeg+'거래일</span>':'')
      + '</div>';
  }
  var dlNote;
  if(v.deadline_is_business_day===false){
    dlNote = '<span class="em">공시 종료일 '+esc(dlabel(v.deadline_raw))+' 은 휴장</span> → 실질 마지막 매매일 '
      + esc(dlabel(v.deadline_business_day));
  } else {
    dlNote = '공시 종료일 '+esc(dlabel(v.deadline_raw))+' 이 그대로 마지막 매매일입니다 (휴장 없음)';
  }
  var ss = v.deadline_short_session;
  if(ss) dlNote += '<br><span style="color:var(--warn)">※ '+esc(ss.name)+' — 이날 증시는 '
    + esc(ss.open||'10:00')+' 개장·'+esc(ss.close||'16:30')+' 폐장으로 순연되어 체결 여력이 평소보다 짧습니다.</span>';
  var gapCls = (v.completion_verdict && (v.completion_verdict.code==='unlikely'||v.completion_verdict.code==='impossible')) ? ' bad' : '';
  /* ★ null 가드: 산출 불가일 때 'null거래일' / '−0거래일' 이 새어나가지 않게 한다. */
  var etaSub = (need==null)
    ? '<span class="em">페이스 산출 불가</span> — 체결 집계 전이거나 최근 체결이 없습니다'
    : dlabel(v.pace_eta_date).slice(-3)+' · 지금 페이스로 <span class="em">'+need+'거래일</span>';
  var paceLine = (v.recent5_avg==null)
    ? '최근 체결 페이스 없음'
    : '최근 '+(v.pace_window_bd||0)+'거래일 평균 '+fmtR(v.recent5_avg)+'주/일'
      + ((v.pace_window_target_bd && v.pace_window_bd < v.pace_window_target_bd)
         ? ' <span class="est-tag" title="표본이 목표('+v.pace_window_target_bd+'일)보다 적어 ETA 신뢰도가 낮습니다">표본 '+v.pace_window_bd+'일</span>' : '');
  var etaLabel = (co.meta.status==='ended')
    ? '최종 결산 · 종료된 프로그램' : '완료 예상 · 페이스 vs 공시 마감';
  var gapMain = (slack==null) ? DASH : sgn(slack)+'<span class="unit">거래일</span>';
  var needLine = (v.required_daily_avg==null)
    ? '필요 일평균 '+DASH+(bdl===0? ' (남은 거래일 없음)' : ' (산출 불가)')
    : '필요 일평균 <span class="em">'+fmtR(v.required_daily_avg)+'주</span> '
      + '(1일 한도 '+fmt(p.daily_limit)+'주의 '+pct(p.daily_limit? v.required_daily_avg/p.daily_limit : null)+')';
  return ''
  + '<section class="eta-card" aria-label="완료 예상">'
  + '<div class="eta-top"><span class="eta-dot" aria-hidden="true"></span>'
  +   '<span class="eta-label">'+etaLabel+'</span>'
  +   verdictBadge(v.completion_verdict)
  +   '<span class="eta-asof">'+esc(D.as_of)+' 기준</span></div>'
  + '<div class="eta-grid">'
  +   '<div class="eta-cell">'
  +     '<div class="eta-cap">(a) 현재 페이스 기준 완료 예상일</div>'
  +     '<div class="eta-main pace">'+esc(v.pace_eta_date||DASH)+'</div>'
  +     '<div class="eta-sub">'+etaSub+'<br>'+paceLine+'</div>'
  +   '</div>'
  +   '<div class="eta-cell sep">'
  +     '<div class="eta-cap">(b) 공시 기준 마감일 (실질 마지막 매매일)</div>'
  +     '<div class="eta-main">'+esc(v.deadline_business_day||DASH)+'</div>'
  +     '<div class="eta-sub">'+dlNote+'<br>마지막 신청일 '+esc(dlabel(v.last_application_day))
  +       ' · 남은 거래일 '+(bdl==null?DASH:bdl+'일')+'</div>'
  +   '</div>'
  +   '<div class="eta-cell sep wide">'
  +     '<div class="eta-cap">(a)→(b) 격차 · 기한 내 완료 가능성</div>'
  +     '<div class="eta-main gap'+gapCls+'">'+gapMain+'</div>'
  +     '<div class="eta-sub">'+esc((v.completion_verdict&&v.completion_verdict.reason)||'')+'<br>'
  +       needLine+'</div>'
  +   '</div>'
  + '</div>'
  + bar
  + '</section>';
}

/* ── 회사 뷰 ─────────────────────────────────────── */
function companyHtml(code){
  var co=D.companies[code], p=co.program, v=co.derived, rows=co.daily;
  var last=rows[rows.length-1] || {};
  var estDays=0, i;
  for(i=0;i<rows.length;i++){ if(rows[i].amount_exact===false) estDays++; }

  var cards=[
    {k:esc(last.date||'')+' 신청', v:fmt(last.applied), u:'주',
     s:p.daily_limit? '1일 한도의 '+pct(last.applied/p.daily_limit)+' · 신청일 '+esc(last.applied_date||'') : ''},
    {k:'체결', v: last.filled==null? '집계 전' : fmt(last.filled), u: last.filled==null? '':'주',
     s: last.fill_rate!=null? '체결률 '+pct(last.fill_rate) : '18시 이후 공시로 확정'},
    {k:'누적 진행률', v:pct(v.progress_ratio), u:'',
     s: fmt(v.cum_filled)+' / '+fmt(p.plan_shares)+'주 · '+won(v.spent_krw)+'원 매입'
        + (v.provisional_ratio!=null? '<br>오늘 신청 '+fmt(v.provisional_applied)+'주 반영 시 '
           + pct(v.provisional_ratio)+' <span class="prov-tag">잠정</span>' : '')},
    {k:'완료 예상 (페이스)', v:esc(v.pace_eta_date||DASH), u:'',
     s: v.pace_eta_business_days==null
        ? '페이스 산출 불가 (체결 집계 전)'
        : '지금 페이스로 '+v.pace_eta_business_days+'거래일 · 마감 여유 '
          + (v.pace_margin_business_days==null? DASH : sgn(v.pace_margin_business_days,'거래일'))}
  ];
  var cardsHtml = cards.map(function(c){
    return '<div class="stat-card"><div class="k">'+c.k+'</div><div class="v">'+c.v
      + (c.u? '<span class="u">'+c.u+'</span>':'') + '</div>'
      + (c.s? '<div class="s">'+c.s+'</div>':'') + '</div>';
  }).join('');

  var meta=[
    ['취득예정', fmt(p.plan_shares)+'주 · '+won(p.plan_amount_krw)+'원'],
    ['발행주식 대비', pctp(v.pct_of_shares_outstanding,4)+' ('+fmt(p.shares_outstanding)+'주)'],
    ['매입 금액', won(v.spent_krw)+'원'],
    ['잔여', fmt(v.remaining_shares)+'주 · 약 '+won(v.remaining_est_krw)+'원'
      + (v.amount_headroom_krw!=null && v.amount_headroom_krw<0
         ? '<br><span style="color:var(--warn)">현 평단 유지 시 공시 취득예정금액 대비 +'
           + Math.abs(v.amount_headroom_pct).toFixed(2)+'% 초과 (정정공시 필요)</span>' : '')],
    ['평균 매입단가', fmt(v.avg_cost)+'원'],
    ['1일 매수한도', fmt(p.daily_limit)+'주'],
    ['최근 '+(v.pace_window_bd||0)+'거래일 평균', fmtR(v.recent5_avg)+'주'],
    ['필요 일평균', fmtR(v.required_daily_avg)+'주'],
    ['남은 거래일', (v.business_days_left==null?DASH:v.business_days_left+'일')
      +' / 전체 '+v.business_days_total+'일'],
    ['체결 집계일수', v.settled_days+'일 (최종 '+esc(v.last_settled_date||DASH)+')'],
    ['이사회 결의일', esc(p.decision_date)+' · 공시 '
      + (p.rcept_no? '<a class="src" href="'+DART_DOC+encodeURIComponent(p.rcept_no)
         +'" target="_blank" rel="noopener">'+esc(p.rcept_no)+' ↗</a>' : DASH)],
    ['취득 방법', esc(p.method||DASH)],
    ['위탁 증권사', '<span title="'+esc(p.broker||'')+'">'+esc(shortBroker(p.broker)||DASH)+'</span>'],
    ['취득 목적', esc(p.purpose||DASH)+' '+purposeBadge(p)]
  ];
  var metaHtml = meta.map(function(x){ return '<div><div class="k">'+x[0]+'</div><div class="v">'+x[1]+'</div></div>'; }).join('');

  var prog=v.progress_ratio||0, elapsed=v.elapsed_ratio||0;
  var notice = '<div class="notice"><b>'+esc(co.meta.name)+'('+esc(code)+')</b> 자기주식 취득 프로그램. '
    + '출처는 KRX <b>KIND 자기주식매매 신청/체결내역</b>과 <b>DART 자기주식 취득 결정</b>입니다. '
    + '장중 실시간 체결량은 공개되지 않으며 <b>당일 체결량은 18시 이후</b> 공시로 확정됩니다(신청량은 전영업일 저녁에 먼저 나옵니다). '
    + '완료 예상일과 남은 거래일은 <b>KRX 공휴일까지 반영한 영업일 기준</b>입니다.'
    + (estDays? ' 일별 체결금액 '+estDays+'일은 <b>추정치</b>입니다(표의 ※ 배지 참조).':'')
    + '</div>'
    + (co.meta.status==='ended'
       ? '<div class="notice"><b>종료된 프로그램입니다.</b> 취득기간('+esc(p.period_from)+' ~ '
         + esc(p.period_to)+')이 끝나 아래는 최종 결산 수치입니다. 진행 중인 새 취득결정이 '
         + '공시되면 자동으로 그쪽으로 전환됩니다.</div>' : '');

  return ''
  + notice
  + '<div class="cards">'+cardsHtml+'</div>'
  + etaCardHtml(co)
  + '<div class="card">'
  +   '<div class="card-head"><div><div class="card-title">취득 진행률</div>'
  +     '<div class="card-sub">'+esc(p.period_from)+' ~ '+esc(p.period_to)+' · '+esc(p.method||'')+(p.broker?' · '+esc(shortBroker(p.broker)):'')+'</div></div>'
  +     paceBadge(v.on_schedule_gap_pp)+'</div>'
  +   '<div class="prog-wrap">'
  +     progBarHtml(v, {elapsed: elapsed})
  +     '<div class="prog-scale">'+scaleHtml()+'</div>'
  +     '<div class="prog-legend"><span>진행 '+pct(prog)+' ('+fmt(v.cum_filled)+'주) 확정'+provLegend(v)+'</span>'
  +       '<span>일정 '+pct(elapsed)+' 경과 (거래일 기준 '+v.business_days_elapsed+'/'+v.business_days_total+'일)</span></div>'
  +   '</div>'
  +   '<div class="meta-grid">'+metaHtml+'</div>'
  + '</div>'
  + '<div class="card"><div class="card-head"><div><div class="card-title">일별 체결량 &amp; 누적</div>'
  +   '<div class="card-sub">막대는 일별 체결, 선은 누적. 오른쪽 축 상한은 취득예정 수량</div></div></div>'
  +   '<div class="chart-box"><canvas id="chartFill"></canvas></div></div>'
  + '<div class="card"><div class="card-head"><div><div class="card-title">평균 체결단가 vs 종가</div>'
  +   '<div class="card-sub">회사가 그날 종가보다 싸게 샀는지 — 아래쪽일수록 잘 산 것'+(estDays? ' (단가 '+estDays+'일은 추정 배분값)':' (KIND 체결금액누계 차분 · 실측)')+'</div></div></div>'
  +   '<div class="chart-box short"><canvas id="chartPrice"></canvas></div></div>'
  + '<div class="card"><div class="card-head"><div><div class="card-title">체결률 &amp; 거래량 내 자사주 비중</div>'
  +   '<div class="card-sub">체결률 = 체결 ÷ 신청 · 비중 = 체결 ÷ 그날 거래량</div></div></div>'
  +   '<div class="chart-box short"><canvas id="chartRate"></canvas></div></div>'
  + '<div class="card"><div class="card-head"><div><div class="card-title">일자별 내역</div>'
  +   '<div class="card-sub" id="tableSub"></div></div></div>'
  +   '<div class="table-scroll"><table class="ep-table" id="tbl"></table></div>'
  +   '<div class="scroll-hint">← 좌우로 스크롤할 수 있습니다</div></div>';
}

function renderTable(rows){
  var head='<thead><tr><th>매매일</th><th>신청</th><th>체결</th><th>체결률</th>'
    +'<th>체결금액</th><th>평단</th><th>종가</th><th>평단−종가</th>'
    +'<th>거래량 비중</th><th>누적</th><th>신청일</th></tr></thead>';
  var body=rows.slice().reverse().map(function(r){
    var diff=r.avg_vs_close;
    var cls = diff==null? 'dim' : (diff<0? 'cheap':'rich');
    var diffTxt = diff==null? DASH : (diff>0?'+':'−')+Math.abs(diff*100).toFixed(2)+'%';
    var amt = r.amount_krw==null? DASH : won(r.amount_krw)
      + (r.amount_exact===false? '<span class="est-tag" title="추정치">※추정</span>':'');
    return '<tr'+(r.provisional?' class="prov"':'')+'>'
      + '<td>'+esc(r.date)+'('+wday(r.date)+')'+(r.provisional?' <span class="prov-tag">잠정</span>':'')+'</td>'
      + '<td>'+fmt(r.applied)+'</td>'
      + '<td>'+(r.filled==null? '집계 전':fmt(r.filled))+'</td>'
      + '<td>'+pct(r.fill_rate)+'</td>'
      + '<td>'+amt+'</td>'
      + '<td>'+fmt(r.avg_price)+'</td>'
      + '<td>'+fmt(r.close)+'</td>'
      + '<td class="'+cls+'">'+diffTxt+'</td>'
      + '<td>'+pct(r.share_of_volume,2)+'</td>'
      + '<td>'+fmt(r.cumulative)+'</td>'
      + '<td class="dim">'+esc(r.applied_date||DASH)+'</td>'
      + '</tr>';
  }).join('');
  document.getElementById('tbl').innerHTML = head+'<tbody>'+(body||'<tr><td>데이터 없음</td></tr>')+'</tbody>';
}

function drawCompanyCharts(co){
  var rows=co.daily, plan=co.program.plan_shares;
  var estN=0; for(var ei=0;ei<rows.length;ei++){ if(rows[ei].amount_exact===false) estN++; }
  var labels=rows.map(function(r){ return r.date.slice(5); });
  mk('chartFill',{
    data:{labels:labels,datasets:[
      {type:'bar',label:'일별 체결',data:rows.map(function(r){return r.filled;}),
        backgroundColor:'rgba(151,252,228,0.45)',borderRadius:3,yAxisID:'y'},
      {type:'line',label:'누적',data:rows.map(function(r){return r.filled==null?null:r.cumulative;}),
        borderColor:WARN,backgroundColor:WARN,pointRadius:0,borderWidth:2,tension:.25,yAxisID:'y1',spanGaps:true,pulse:true}
    ]},
    options:baseOpts({scales:{
      x:axis(),
      y:axis({position:'left',title:{display:true,text:'일별(주)',color:TICK,font:{size:10}}}),
      y1:axis({position:'right',grid:{drawOnChartArea:false},suggestedMax:plan||undefined,
        ticks:{color:TICK,font:{size:10}},title:{display:true,text:'누적(주)',color:TICK,font:{size:10}}})
    }})
  });
  mk('chartPrice',{
    type:'line',
    data:{labels:labels,datasets:[
      {label:'평균 체결단가'+(estN? '(일부 추정)':''),data:rows.map(function(r){return r.avg_price;}),
        borderColor:TEAL,pointRadius:2,borderWidth:2,tension:.2,spanGaps:true,pulse:true},
      {label:'종가',data:rows.map(function(r){return r.close;}),
        borderColor:'rgba(127,168,164,0.7)',borderDash:[4,3],pointRadius:0,borderWidth:1.5,tension:.2,spanGaps:true}
    ]},
    options:baseOpts({scales:{x:axis(),
      y:axis({ticks:{color:TICK,font:{size:10},callback:function(v){return Number(v).toLocaleString('ko-KR');}}})}})
  });
  mk('chartRate',{
    data:{labels:labels,datasets:[
      {type:'line',label:'체결률',data:rows.map(function(r){return r.fill_rate==null?null:r.fill_rate*100;}),
        borderColor:DIM,pointRadius:0,borderWidth:2,tension:.2,spanGaps:true,yAxisID:'y',pulse:true},
      {type:'bar',label:'거래량 내 비중',data:rows.map(function(r){return r.share_of_volume==null?null:r.share_of_volume*100;}),
        backgroundColor:'rgba(96,165,250,0.35)',borderRadius:3,yAxisID:'y1'}
    ]},
    options:baseOpts({scales:{
      x:axis(),
      /* 0/20/40/60/80/100 균등 눈금. autoSkip 을 끄지 않으면 1/3 간격으로 뭉개진다. */
      y:axis({position:'left',min:0,max:100,
        ticks:{color:TICK,font:{size:10},stepSize:20,autoSkip:false,
               callback:function(v){return v+'%';}}}),
      y1:axis({position:'right',min:0,grid:{drawOnChartArea:false},ticks:{color:TICK,font:{size:10},callback:function(v){return v+'%';}}})
    }})
  });
}

/* ── 비교 뷰 ─────────────────────────────────────── */
function cmpPanel(code){
  var co=D.companies[code], p=co.program, v=co.derived;
  var rows=[
    ['취득 목적', purposeBadge(p)],
    ['진행 / 일정', pct(v.progress_ratio)+' / '+pct(v.elapsed_ratio)+' 경과'],
    ['누적 체결', fmt(v.cum_filled)+'주'],
    ['잔여', fmt(v.remaining_shares)+'주'],
    ['최근 '+(v.pace_window_bd||0)+'거래일 평균', fmtR(v.recent5_avg)+'주/일'],
    ['필요 일평균', fmtR(v.required_daily_avg)+'주/일'],
    ['(a) 페이스 완료 예상', v.pace_eta_business_days==null
      ? '산출 불가 (체결 집계 전)'
      : esc(v.pace_eta_date)+' ('+v.pace_eta_business_days+'거래일)'],
    ['(b) 공시 마감(실질)', esc(v.deadline_business_day)+(v.deadline_is_business_day===false? ' ← 공시 '+esc(v.deadline_raw)+' 휴장':'')],
    ['(a)→(b) 여유', sgn(v.pace_margin_business_days,'거래일')]
  ];
  return '<div class="card" style="margin-bottom:0">'
    + '<div class="cmp-name">'+esc(co.meta.name)+'<span class="code">'+esc(code)+'</span>'+verdictBadge(v.completion_verdict)+'</div>'
    + '<div class="cmp-big">'+pct(v.progress_ratio)+'<span class="unit">진행</span></div>'
    + '<div class="card-sub">'+fmt(v.cum_filled)+' / '+fmt(p.plan_shares)+'주 · '+won(v.spent_krw)+'원 / '+won(p.plan_amount_krw)+'원</div>'
    + '<div class="prog-wrap" style="padding-top:16px">'
    +   progBarHtml(v, {elapsed: v.elapsed_ratio})
    + '</div>'
    + (v.provisional_ratio!=null
       ? '<div style="font-size:11px;color:var(--text-dim);margin-top:8px">'+provLegend(v)+'</div>' : '')
    + '<div class="cmp-rows">'+rows.map(function(r){
        return '<div class="r"><span class="k">'+r[0]+'</span><span class="v">'+r[1]+'</span></div>'; }).join('')+'</div>'
    + '</div>';
}

function compareHtml(){
  var A=D.companies[ORDER[0]], B=D.companies[ORDER[1]];
  var pa=A.derived, pb=B.derived;

  /* ★ row(label, accessor, winnerRule) — 값 접근자를 하나만 받는다.
     A/B 에 같은 함수를 두 번 넘기던 중복을 없애 '한쪽만 바꿔 쓰는' 실수를 구조적으로 막고,
     승자도 리터럴이 아니라 값 비교로만 정한다(하드코딩 'b' 금지). */
  function row(label, f, winner, opts){
    opts = opts||{};
    var w = (typeof winner==='function') ? winner(A,B) : null;   // 'a' | 'b' | null
    return '<tr'+(opts.hero?' class="hero"':'')+'><td class="lbl">'+label+'</td>'
      + '<td class="a'+(w==='a'?' win':'')+'" data-co="'+esc(A.meta.name)+'">'+f(A)+'</td>'
      + '<td class="b'+(w==='b'?' win':'')+'" data-co="'+esc(B.meta.name)+'">'+f(B)+'</td></tr>';
  }
  /* 큰 쪽 / 작은 쪽 승자 규칙. null 이 섞이면 승자 없음. */
  function bigger(get){ return function(a,b){
    var x=get(a), y=get(b);
    if(x==null||y==null||!isFinite(x)||!isFinite(y)) return null;
    return x>=y?'a':'b'; }; }
  function smaller(get){ return function(a,b){
    var x=get(a), y=get(b);
    if(x==null||y==null||!isFinite(x)||!isFinite(y)) return null;
    return x<=y?'a':'b'; }; }
  function earlier(get){ return function(a,b){
    var x=get(a), y=get(b);
    if(!x||!y) return null;
    return x<=y?'a':'b'; }; }
  /* 소각분끼리만 '발행주식 대비' 승자를 준다 — 소각 여부를 모르면 강조하지 않는다. */
  function biggerIfSameKind(get){ return function(a,b){
    if(a.program.is_cancellation!==b.program.is_cancellation) return null;
    return bigger(get)(a,b); }; }

  var body=[
    row('취득 목적 · 소각 여부',
        function(c){ return purposeBadge(c.program)
          + '<div style="font-size:11px;color:var(--text-dim);margin-top:4px">'+esc(c.program.purpose||DASH)+'</div>'; },
        null, {hero:true}),
    row('취득예정 주식수', function(c){return fmt(c.program.plan_shares)+'주';},
        bigger(function(c){return c.program.plan_shares;})),
    row('취득예정 금액', function(c){return won(c.program.plan_amount_krw)+'원';},
        bigger(function(c){return c.program.plan_amount_krw;})),
    row('발행주식 대비', function(c){
          return pctp(c.derived.pct_of_shares_outstanding,4)
            + '<div style="font-size:11px;color:var(--text-dim);margin-top:3px">'
            + (c.program.is_cancellation===true ? '소각 시 EPS 증가 효과'
               : c.program.is_cancellation===false ? '보상 재원 — 주식수 감소 없음' : '소각 여부 미상')
            + '</div>'; },
        biggerIfSameKind(function(c){return c.derived.pct_of_shares_outstanding;})),
    row('취득 기간', function(c){return esc(c.program.period_from)+' ~ '+esc(c.program.period_to);}),
    row('취득 방법', function(c){return esc(c.program.method||DASH);}),
    row('위탁 증권사', function(c){return esc(shortBroker(c.program.broker)||DASH);}),
    row('이사회 결의일 · 공시', function(c){
          return esc(c.program.decision_date||DASH)
            + (c.program.rcept_no? '<br><a class="src" href="'+DART_DOC+encodeURIComponent(c.program.rcept_no)
               + '" target="_blank" rel="noopener">'+esc(c.program.rcept_no)+' ↗</a>' : ''); }),
    row('누적 체결', function(c){return fmt(c.derived.cum_filled)+'주';},
        bigger(function(c){return c.derived.cum_filled;})),
    row('진행률', function(c){return pct(c.derived.progress_ratio);},
        bigger(function(c){return c.derived.progress_ratio;})),
    row('일정 경과율(거래일)', function(c){return pct(c.derived.elapsed_ratio);}),
    row('일정 대비', function(c){return sgn(c.derived.on_schedule_gap_pp,'%p',1);},
        bigger(function(c){return c.derived.on_schedule_gap_pp;})),
    row('매입 금액', function(c){return won(c.derived.spent_krw)+'원';},
        bigger(function(c){return c.derived.spent_krw;})),
    row('평균 매입단가', function(c){return fmt(c.derived.avg_cost)+'원';}),
    row('잔여 수량', function(c){return fmt(c.derived.remaining_shares)+'주';}),
    row('잔여 금액(추정)', function(c){
          var h=c.derived.amount_headroom_pct;
          return '약 '+won(c.derived.remaining_est_krw)+'원'
            + (h==null? '' : '<div style="font-size:11px;margin-top:3px;color:'
               + (h<0?'var(--warn)':'var(--text-dim)')+'">공시 취득예정금액 대비 '
               + (h<0? '+'+Math.abs(h).toFixed(2)+'% 초과 우려'
                     : Math.abs(h).toFixed(2)+'% 여유')+'</div>'); }),
    row('최근 페이스 평균', function(c){
          var d=c.derived;
          return (d.recent5_avg==null? DASH : fmtR(d.recent5_avg)+'주/일')
            + '<div style="font-size:11px;color:var(--text-dim);margin-top:3px">'
            + (d.pace_window_bd? '표본 '+d.pace_window_bd+'거래일' : '체결 집계 전')+'</div>'; },
        bigger(function(c){return c.derived.recent5_avg;})),
    row('필요 일평균', function(c){return fmtR(c.derived.required_daily_avg)+'주/일';}),
    row('페이스 여력(필요/최근)', function(c){
          var d=c.derived;
          return pct(d.recent5_avg? d.required_daily_avg/d.recent5_avg : null); },
        smaller(function(c){
          var d=c.derived;
          return d.recent5_avg? d.required_daily_avg/d.recent5_avg : null; })),
    row('1일 매수한도', function(c){return fmt(c.program.daily_limit)+'주';}),
    row('(a) 페이스 완료 예상일', function(c){
          return c.derived.pace_eta_date? esc(c.derived.pace_eta_date) : '산출 불가'; },
        earlier(function(c){return c.derived.pace_eta_date;})),
    row('(b) 공시 마감(실질 매매일)', function(c){
          return dlabel(c.derived.deadline_business_day)
            + (c.derived.deadline_is_business_day===false?' ⚠':'')
            + (c.derived.deadline_short_session
               ? '<div style="font-size:11px;color:var(--warn);margin-top:3px">'
                 + esc(c.derived.deadline_short_session.name)+' · 10:00 개장</div>' : ''); }),
    row('(a)→(b) 여유 거래일', function(c){return sgn(c.derived.pace_margin_business_days,'일');},
        bigger(function(c){return c.derived.pace_margin_business_days;})),
    row('기한 내 완료 판정', function(c){return verdictBadge(c.derived.completion_verdict);})
  ].join('');

  return ''
  + '<div class="notice">두 프로그램을 같은 기준(KRX 공휴일 반영 영업일)으로 나란히 놓은 요약입니다. '
  +   '틸색으로 강조된 값은 해당 항목에서 더 앞서거나 더 큰 쪽입니다(투자 판단이 아니라 대소 표시입니다). '
  +   '<b>취득 목적이 다르면 &lsquo;발행주식 대비&rsquo; 를 직접 비교할 수 없습니다</b> — '
  +   '소각은 발행주식수를 실제로 줄이지만 임직원 보상 재원은 줄이지 않습니다.</div>'
  + '<div class="cmp-grid">'+cmpPanel(ORDER[0])+cmpPanel(ORDER[1])+'</div>'
  + '<div class="card"><div class="card-head"><div><div class="card-title">진행률 추이 비교</div>'
  +   '<div class="card-sub">누적 체결 ÷ 취득예정 수량 (%) · 점선은 일정 경과율</div></div></div>'
  +   '<div class="chart-box"><canvas id="chartCmp"></canvas></div></div>'
  + '<div class="card"><div class="card-head"><div><div class="card-title">항목별 대조</div>'
  +   '<div class="card-sub">'+esc(D.as_of)+' 기준</div></div></div>'
  +   '<div class="table-scroll"><table class="ep-table cmp-table">'
  +     '<thead><tr><th style="text-align:left">항목</th><th>'+esc(A.meta.name)+'</th><th>'+esc(B.meta.name)+'</th></tr></thead>'
  +     '<tbody>'+body+'</tbody></table></div>'
  +   '<div class="scroll-hint">← 좌우로 스크롤할 수 있습니다</div></div>';
}

function drawCompareChart(){
  var A=D.companies[ORDER[0]], B=D.companies[ORDER[1]];
  var set={}, i;
  [A,B].forEach(function(co){ co.daily.forEach(function(r){ set[r.date]=1; }); });
  var labels=Object.keys(set).sort();
  function series(co){
    var m={};
    co.daily.forEach(function(r){ m[r.date] = r.filled==null? null : r.cumulative/co.program.plan_shares*100; });
    return labels.map(function(d){ return m[d]===undefined? null : m[d]; });
  }
  function elapsedSeries(co){
    // ★ 경과율의 기준일은 derived.elapsed_ratio 와 같아야 한다 = '체결이 집계된 거래일'.
    //   체결 미집계 잠정행(오늘)을 세면 마지막 점이 표의 값보다 1일치 커진다.
    var n=0, tot=co.derived.business_days_total, m={};
    co.daily.forEach(function(r){
      if(r.filled==null) return;            // 잠정행은 경과에 세지 않는다
      n+=1; m[r.date]= n/tot*100;
    });
    return labels.map(function(d){ return m[d]===undefined? null : m[d]; });
  }
  mk('chartCmp',{
    type:'line',
    data:{labels:labels.map(function(d){return d.slice(5);}),datasets:[
      {label:A.meta.name+' 진행률',data:series(A),borderColor:TEAL,backgroundColor:TEAL,
        pointRadius:2,borderWidth:2,tension:.2,spanGaps:true,pulse:true},
      {label:B.meta.name+' 진행률',data:series(B),borderColor:WARN,backgroundColor:WARN,
        pointRadius:2,borderWidth:2,tension:.2,spanGaps:true,pulse:true},
      {label:A.meta.name+' 일정 경과',data:elapsedSeries(A),borderColor:'rgba(151,252,228,0.45)',
        borderDash:[4,3],pointRadius:0,borderWidth:1.2,tension:.2,spanGaps:true},
      {label:B.meta.name+' 일정 경과',data:elapsedSeries(B),borderColor:'rgba(251,191,36,0.45)',
        borderDash:[4,3],pointRadius:0,borderWidth:1.2,tension:.2,spanGaps:true}
    ]},
    options:baseOpts({scales:{x:axis(),
      y:axis({min:0,ticks:{color:TICK,font:{size:10},callback:function(v){return v+'%';}}})}})
  });
}

/* ── 푸터 ─────────────────────────────────────────── */
function footerHtml(){
  var w=D.warnings||[];
  var acc=D.estimator_accuracy_text||'';
  var notes=[];
  ORDER.forEach(function(code){
    var co=D.companies[code];
    var est=co.daily.filter(function(r){return r.amount_exact===false;}).length;
    if(est) notes.push('<b>'+esc(co.meta.name)+'</b> 일별 체결금액 · 평균단가 '+est+'일은 <b>추정치</b>입니다. '
      + '유가증권시장 직접취득은 거래소 공시에 일별 체결금액 칸이 비어 있어, 그날 (고가+저가)/2 로 '
      + '가중 배분한 뒤 총액을 거래소 누계에 맞췄습니다. '+esc(acc)+' <b>총액과 누적 평균단가는 정확합니다.</b>');
  });
  var dq = ''
    + '<li>기준일: '+esc(D.as_of)+' · 생성 '+esc(D.generated_at)+' (KST)</li>'
    + '<li>휴장일 캘린더 커버리지: '+esc((D.holiday_coverage||{}).from)+' ~ '+esc((D.holiday_coverage||{}).to)+'</li>'
    + '<li>데이터 정합성 점검 '+(D.invariants_passed?'통과':'실패')+'</li>'
    + (D.build_failures && Object.keys(D.build_failures).length
       ? '<li style="color:var(--warn)">일부 종목 갱신 실패: '+esc(Object.keys(D.build_failures).join(', '))+'</li>' : '')
    + w.map(function(x){return '<li>'+esc(x)+'</li>';}).join('');

  return ''
  + '<div><b>데이터 갱신</b> '+esc((D.generated_at||'').slice(0,16).replace('T',' '))+' (KST) · 기준일 '+esc(D.as_of)+'</div>'
  + '<div class="foot-h">출처</div>'
  + '<ul>'
  +   '<li><a class="src" href="'+KIND_URL+'" target="_blank" rel="noopener">KRX KIND 자기주식 취득·처분 신청/체결내역 ↗</a>'
  +     ' — 신고·신청·체결·체결금액누계</li>'
  +   '<li><a class="src" href="'+DART_API+'" target="_blank" rel="noopener">DART 전자공시 (자기주식 취득결정·발행주식총수) ↗</a></li>'
  +   '<li>네이버 금융 일봉 시세 (종가·거래량·고저가)</li>'
  +   '<li>한국거래소 공식 휴장일 캘린더</li>'
  + '</ul>'
  + '<div class="foot-h">추정치 · 주의</div>'
  + '<ul>'+notes.map(function(n){return '<li>'+n+'</li>';}).join('')
  +   '<li>당일(잠정) 행은 신청량만 확정이고 체결·종가는 18시 이후 공시로 확정됩니다. '
  +     '진행률 바의 빗금 구간은 오늘 신청분이 전량 체결된다고 가정한 <b>잠정</b> 값입니다.</li>'
  +   '<li>완료 예상일은 '+esc(D.rules.pace_definition)+'</li>'
  +   '<li>기한 내 완료 판정: '+esc(D.rules.verdict_threshold)+'</li>'
  +   '<li>금액은 모두 원(KRW) 단위입니다.</li></ul>'
  + '<details><summary>데이터 품질 로그 ('+w.length+'건)</summary><ul>'+dq+'</ul></details>'
  + '<div style="margin-top:14px">이 페이지는 외부 요청 0건의 자기완결 HTML 입니다 — '
  +   '열려 있는 동안에도 스스로 갱신되지 않습니다. '
  +   (REFRESH_HINT ? esc(REFRESH_HINT)+' 그 뒤 새로고침하세요.' : '')+'</div>';
}

/* ── 라우팅 ───────────────────────────────────── */
/* 비교 탭은 회사가 2곳 이상일 때만. 1곳이면 탭 자체를 숨긴다. */
var TABS = ORDER.map(function(c){ return {id:c, label:D.companies[c].meta.name}; })
  .concat(ORDER.length>=2 ? [{id:'cmp', label:'비교'}] : []);

/* 실제로 넘칠 때만 페이드/힌트를 보인다(안 넘치면 오히려 방해가 된다). */
function syncScrollHints(){
  [].forEach.call(document.querySelectorAll('.table-scroll'), function(el){
    var over = el.scrollWidth > el.clientWidth + 1;
    el.classList.toggle('no-fade', !over);
    var hint = el.nextElementSibling;
    if(hint && hint.classList.contains('scroll-hint')) hint.style.display = over? '' : 'none';
  });
}
window.addEventListener('resize', syncScrollHints);

function setTab(id){
  killCharts();
  TABS.forEach(function(t){
    var b=document.getElementById('tab-'+t.id);
    if(!b) return;
    var on = (t.id===id);
    b.className = 'nav-link'+(on?' active':'');
    b.setAttribute('aria-selected', on? 'true':'false');
    b.setAttribute('tabindex', on? '0':'-1');
  });
  var view=document.getElementById('view');
  var banner = staleBannerHtml();
  if(id==='cmp'){
    view.innerHTML = banner + compareHtml();
    drawCompareChart();
    document.getElementById('subtitle').textContent =
      ORDER.map(function(c){ return D.companies[c].meta.name; }).join(' · ')+' 자사주 매입 비교';
  } else {
    var co=D.companies[id];
    view.innerHTML = banner + companyHtml(id);
    renderTable(co.daily);
    var provAny = co.daily.some(function(r){return r.provisional;});
    document.getElementById('tableSub').textContent = co.daily.length+'거래일 · 최신 '+co.daily[co.daily.length-1].date
      + (provAny? ' · 오늘은 신청량만 확정된 잠정 행(18시 공시로 확정)':'');
    drawCompanyCharts(co);
    document.getElementById('subtitle').textContent = co.meta.name+' ('+id+') · 자사주 매입 진행률';
  }
  syncScrollHints();
  try{ localStorage.setItem('bb_tab', id); }catch(e){}
  window.scrollTo({top:0,behavior:'auto'});
}

function boot(){
  var nav=document.getElementById('nav');
  nav.innerHTML = TABS.map(function(t){
    return '<button class="nav-link" id="tab-'+t.id+'" role="tab" aria-selected="false" tabindex="-1" '
      + 'aria-controls="view" data-tab="'+t.id+'">'+esc(t.label)+'</button>';
  }).join('');
  nav.addEventListener('click', function(e){
    var b=e.target.closest('button[data-tab]');
    if(b) setTab(b.getAttribute('data-tab'));
  });
  nav.addEventListener('keydown', function(e){
    if(e.key!=='ArrowRight' && e.key!=='ArrowLeft') return;
    var ids=TABS.map(function(t){return t.id;});
    var cur=ids.indexOf(document.querySelector('.nav-link.active').getAttribute('data-tab'));
    var nx=(cur + (e.key==='ArrowRight'?1:ids.length-1)) % ids.length;
    setTab(ids[nx]); document.getElementById('tab-'+ids[nx]).focus();
  });
  var fr=freshness();
  document.getElementById('stamp').innerHTML =
    '갱신 '+esc(String(D.generated_at||'').slice(0,16).replace('T',' '))+' KST<br>기준일 '+esc(D.as_of)
    + (fr.lag===1 ? '<br><span class="stale-chip">전일 기준</span>' : '')
    + (fr.lag>=2 ? '<br><span class="stale-chip">'+fr.lag+'거래일 경과</span>' : '');
  document.getElementById('foot').innerHTML = footerHtml();
  var saved=null;
  try{ saved=localStorage.getItem('bb_tab'); }catch(e){}
  setTab((saved && (saved==='cmp' || D.companies[saved])) ? saved : ORDER[0]);
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
"""

HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="color-scheme" content="dark" />
<meta name="theme-color" content="#061E20" />
<title>자사주 매입 진행률 — 삼성전자 · SK하이닉스</title>
<meta name="description" content="삼성전자·SK하이닉스 자기주식 취득 진행률, 일별 신청·체결, 현재 페이스 기준 완료 예상일과 공시 기준 마감일 비교." />
<style>__CSS__</style>
</head>
<body>
<div class="container">
  <header>
    <div class="brand">
      <span class="logo-dot" aria-hidden="true"></span>
      <div>
        <h1>자사주 매입 진행률</h1>
        <div class="sub" id="subtitle">삼성전자 · SK하이닉스</div>
      </div>
    </div>
    <div class="stamp" id="stamp"></div>
  </header>

  <nav class="top-nav-row" aria-label="회사 선택">
    <div class="top-nav" id="nav" role="tablist"></div>
  </nav>

  <main id="view" role="tabpanel" tabindex="-1"></main>

  <footer id="foot"></footer>
</div>

<script>window.__BUYBACK__ = __DATA__;</script>
<script>__CHARTJS__</script>
<script>__APP__</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA_PATH))
    ap.add_argument("--vendor", default=str(VENDOR_PATH))
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--docs-out", default=str(DOCS_PATH),
                    help="GitHub Pages 서빙용 사본 경로 (기본 docs/index.html)")
    ap.add_argument("--no-docs", action="store_true",
                    help="docs/index.html 사본을 만들지 않는다")
    ap.add_argument("--refresh-hint", default=DEFAULT_HINT,
                    help="로컬 사본의 stale 배너 안내문")
    ap.add_argument("--docs-refresh-hint", default=DOCS_HINT,
                    help="docs/index.html 의 stale 배너 안내문")
    ap.add_argument("--max-age-days", type=int, default=4,
                    help="buyback.json 의 as_of 가 이보다 오래되면 경고하고 페이지에 배너를 심는다 "
                         "(0 이면 검사 안 함)")
    args = ap.parse_args()

    data_path = Path(args.data)
    vendor_path = Path(args.vendor)
    out_path = Path(args.out)

    data = json.loads(data_path.read_text(encoding="utf-8"))
    if not data.get("companies"):
        print("ERROR: buyback.json 에 companies 가 없다.", file=sys.stderr)
        return 1
    if not data.get("invariants_passed"):
        print("WARN: invariants_passed 가 True 가 아니다 — 데이터 신뢰 불가.", file=sys.stderr)

    # ★ build 가 실패해도 render 는 낡은 buyback.json 을 그대로 읽어 '정상 페이지'를 찍는다.
    #   as_of 가 오래됐으면 여기서 경고하고, 페이지에도 그 사실을 심는다.
    data["render_stale_days"] = None
    if args.max_age_days and data.get("as_of"):
        try:
            age = (dt.date.today() - dt.date.fromisoformat(data["as_of"])).days
        except ValueError:
            age = None
        if age is not None:
            data["render_stale_days"] = age
            if age > args.max_age_days:
                print(f"WARN: buyback.json 의 as_of={data['as_of']} 가 {age}일 지났다 "
                      f"(허용 {args.max_age_days}일). build_data.py 가 실패했을 수 있다 "
                      f"— 페이지에 경고 배너를 심는다.", file=sys.stderr)

    chartjs = vendor_path.read_text(encoding="utf-8")
    if "Chart" not in chartjs:
        print("ERROR: vendor Chart.js 가 이상하다.", file=sys.stderr)
        return 1

    def build(hint: str) -> str:
        payload = dict(data)
        payload["refresh_hint"] = hint
        return (
            HTML.replace("__CSS__", CSS)
            .replace("__DATA__", js_safe_json(payload))
            .replace("__CHARTJS__", script_safe(chartjs))
            .replace("__APP__", JS)
        )

    out_path.write_text(build(args.refresh_hint), encoding="utf-8")
    size = out_path.stat().st_size
    print(f"wrote {out_path}  ({size:,} bytes)")

    # docs/index.html : 내용은 같고 stale 배너 안내문만 공개 페이지용으로 바꾼다.
    if not args.no_docs:
        docs_path = Path(args.docs_out)
        docs_path.parent.mkdir(parents=True, exist_ok=True)
        docs_path.write_text(build(args.docs_refresh_hint), encoding="utf-8")
        # GitHub Pages 의 Jekyll 처리를 끈다(_ 로 시작하는 경로가 생겨도 그대로 서빙).
        nojekyll = docs_path.parent / ".nojekyll"
        if not nojekyll.exists():
            nojekyll.write_text("", encoding="utf-8")
        print(f"wrote {docs_path}  ({docs_path.stat().st_size:,} bytes)  [GitHub Pages]")
    print(f"  companies: {', '.join(data['companies'].keys())}")
    print(f"  chart.js : {len(chartjs):,} chars inlined (v4.x, from {vendor_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
