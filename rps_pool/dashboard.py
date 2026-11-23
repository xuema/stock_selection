#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第五步 · 可视化看板: 把每日入选结果 + 回测净值合成一个自包含 HTML

  python3 dashboard.py                    # 取最新一次 screen 结果
  python3 dashboard.py --date 20261123

输出 out/dashboard.html (无外部依赖, 双击即可看)
"""
import argparse, glob, json, os, sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

SCREEN = os.path.join(C.OUT, "screen")
BT = os.path.join(C.OUT, "backtest")
OUTHTML = os.path.join(C.OUT, "dashboard.html")


def latest_screen_dir(date: str | None = None) -> str:
    ds = sorted(os.path.basename(p) for p in glob.glob(os.path.join(SCREEN, "*"))
                if os.path.isdir(p))
    if not ds:
        raise SystemExit("out/screen 为空, 先跑 screen_daily.py")
    if date and date in ds:
        return os.path.join(SCREEN, date)
    return os.path.join(SCREEN, ds[-1])


def hist_dates(tag: str = "main"):
    """"信号强度"曲线: 优先读回测的逐日入选数(全样本都有), 否则用跑过的 screen 结果。"""
    cp = os.path.join(BT, f"counts_{tag}.csv")
    if os.path.exists(cp):
        d = pd.read_csv(cp, index_col=0)
        return ([{"d": str(r), "s1": int(d.loc[r, "s1"]), "s2": int(d.loc[r, "s2"]),
                 "all": int(d.loc[r, "sxhcg"])} for r in d.index], "backtest")
    rows = []
    for p in sorted(glob.glob(os.path.join(SCREEN, "*", "summary.txt"))):
        d = os.path.basename(os.path.dirname(p))
        txt = open(p, encoding="utf-8").read()
        n1 = n2 = nall = None
        for line in txt.splitlines():
            if "过 RPS 选股" in line:
                nall = int(line.split("全条)")[1].split("只")[0].strip())
            if "策略1 RPS+周线RSI多头确认" in line:
                n1 = int(line.split(":")[1].replace("只", "").strip())
            if "策略2 RPS+接近一年新高" in line:
                n2 = int(line.split(":")[1].replace("只", "").strip())
        rows.append({"d": f"{d[:4]}-{d[4:6]}-{d[6:]}", "s1": n1, "s2": n2, "all": nall})
    return rows, "screen"


def read_bt(tag: str):
    out = {}
    navp = os.path.join(BT, f"nav_all_{tag}.csv")
    if os.path.exists(navp):
        nv = pd.read_csv(navp, index_col=0)
        out["nav"] = {"dates": list(nv.index.astype(str)),
                      "series": {c: [None if pd.isna(v) else round(float(v), 5) for v in nv[c]]
                                 for c in nv.columns}}
    for st in ("策略1", "策略2"):
        mp = os.path.join(BT, f"metrics_{st}_{tag}.json")
        if os.path.exists(mp):
            out.setdefault("metrics", {})[st] = json.load(open(mp, encoding="utf-8"))
        tp = os.path.join(BT, f"trades_{st}_{tag}.csv")
        if os.path.exists(tp):
            t = pd.read_csv(tp, dtype={"code": str})
            out.setdefault("trades", {})[st] = t.tail(60)[
                ["code", "name", "entry_date", "exit_date", "days", "ret", "reason"]
            ].to_dict("records")
    sp = os.path.join(BT, "sweep.csv")
    if os.path.exists(sp):
        out["sweep"] = pd.read_csv(sp).to_dict("records")
    return out


HTML = r"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RPS 股票池 · 每日双策略看板</title>
<style>
:root{--bg:#0f1419;--fg:#e6e9ee;--mut:#8b97a8;--card:#171e26;--line:#25303c;--up:#ef4d4d;--dn:#2eb37a;--ac:#4c9aff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
h1{font-size:19px;margin:0 0 4px}
h2{font-size:15px;margin:0 0 10px;color:var(--ac);font-weight:600}
.wrap{max-width:1420px;margin:0 auto;padding:20px}
.sub{color:var(--mut);font-size:12px;margin-bottom:18px}
.grid{display:grid;gap:16px}
.g2{grid-template-columns:1fr 1fr}
@media(max-width:1000px){.g2{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th{color:var(--mut);font-weight:500;text-align:right;padding:6px 7px;border-bottom:1px solid var(--line);
   position:sticky;top:0;background:var(--card);cursor:pointer;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th:nth-child(2),td:nth-child(2){text-align:left}
td{padding:5px 7px;text-align:right;border-bottom:1px solid rgba(37,48,60,.5);white-space:nowrap}
tbody tr:hover{background:#1d2731}
.pos{color:var(--up)}.neg{color:var(--dn)}
.badge{display:inline-block;padding:1px 7px;border-radius:20px;font-size:11px;background:#22303e;color:#9dc3f0}
.badge.on{background:#2a3a1e;color:#a8d97a}
.kv{display:flex;flex-wrap:wrap;gap:8px 22px;margin-bottom:12px}
.kv div{font-size:12px;color:var(--mut)}
.kv b{display:block;font-size:19px;color:var(--fg);font-weight:600}
.scroll{max-height:520px;overflow:auto}
.note{color:var(--mut);font-size:12px;margin-top:10px}
svg{display:block;width:100%;height:auto}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin-top:6px}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle}
.tabs{display:flex;gap:6px;margin-bottom:10px}
.tabs button{background:#22303e;color:var(--mut);border:1px solid var(--line);border-radius:6px;
 padding:5px 12px;font-size:13px;cursor:pointer;font-family:inherit}
.tabs button.on{background:var(--ac);color:#0b1016;border-color:var(--ac);font-weight:600}
.spark{width:120px;height:26px}
</style></head><body><div class="wrap">
<h1>RPS 股票池 · 每日双策略</h1>
<div class="sub" id="hdr"></div>
<div class="grid g2" id="pick"></div>
<div class="card" style="margin-top:16px"><h2>卖出提示 · 周线 RSI 死叉（参考卖点）</h2>
  <div id="sellbox"></div></div>
<div class="card" style="margin-top:16px"><h2>回测净值（1 元起）</h2><div id="nav"></div></div>
<div class="card" style="margin-top:16px"><h2>参数敏感性（同一段回测，只改一个变量）</h2>
  <div class="scroll" id="sweep"></div></div>
<div class="card" style="margin-top:16px"><h2>已平仓交易（最近 60 笔）</h2>
  <div class="tabs" id="ttabs"></div><div class="scroll" id="trades"></div></div>
<div class="card" style="margin-top:16px"><h2>历史每日入选数量</h2><div id="sig"></div></div>
<div class="note">买入价 = 当日最后一根日线收盘（本机 13:50 抓取 ≈ 收盘前 1 小时）。
卖出 = 周线 RSI1 下穿 RSI2 且 RSI1 &lt; RSI3。
股票池为“当前”条件回溯历史 → 存在前视/幸存者偏差；北向持股为季报前十大流通股东席位口径。
本页面仅为研究参考，不构成投资建议。</div>
</div>
<script id="D" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('D').textContent);
const f=(x,n=2)=>x==null?'—':Number(x).toFixed(n);
const pct=(x,n=1)=>x==null?'—':(100*x).toFixed(n)+'%';
const cls=x=>x>0?'pos':(x<0?'neg':'');
document.getElementById('hdr').innerHTML=
 `数据日期 <b>${D.date}</b> · 股票池 ${D.pool_n} 只 · 通过 RPS 选股 ${D.sxhcg_n} 只 · `+
 `策略1 ${D.s1.length} 只 · 策略2 ${D.s2.length} 只`;

// ── 折线图 ───────────────────────────────────────────────
function line(el,series,opts={}){
  const W=opts.w||1200,H=opts.h||300,P={l:44,r:12,t:10,b:22};
  const ks=Object.keys(series);if(!ks.length){el.innerHTML='<div class="note">无数据</div>';return}
  const n=series[ks[0]].length;
  const all=ks.flatMap(k=>series[k]).filter(v=>v!=null);
  let lo=Math.min(...all),hi=Math.max(...all);
  if(opts.zero){lo=Math.min(lo,opts.zero)}
  const pad=(hi-lo)*.08||1;lo-=opts.lo0?0:pad;hi+=pad;
  const X=i=>P.l+(W-P.l-P.r)*i/(n-1),Y=v=>P.t+(H-P.t-P.b)*(1-(v-lo)/(hi-lo));
  const cols=opts.cols||['#4c9aff','#ef4d4d','#f0b429','#2eb37a','#b06ef7'];
  let g='';
  for(let t=0;t<=4;t++){const v=lo+(hi-lo)*t/4,y=Y(v);
    g+=`<line x1="${P.l}" y1="${y}" x2="${W-P.r}" y2="${y}" stroke="#25303c"/>`+
       `<text x="${P.l-6}" y="${y+4}" fill="#8b97a8" font-size="10" text-anchor="end">${v.toFixed(opts.dp??2)}</text>`}
  const lbl=opts.labels||[];
  for(let t=0;t<=6;t++){const i=Math.round((n-1)*t/6);
    if(lbl[i])g+=`<text x="${X(i)}" y="${H-6}" fill="#8b97a8" font-size="10" text-anchor="middle">${lbl[i]}</text>`}
  ks.forEach((k,j)=>{const s=series[k];let d='',st=null;
    s.forEach((v,i)=>{if(v==null){if(d&&st!=null){g+=`<path d="${d}" fill="none" stroke="${cols[j%5]}" stroke-width="1.6"/>`}d='';st=null;return}
      d+=(d?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)+' ';st=v});
    if(d)g+=`<path d="${d}" fill="none" stroke="${cols[j%5]}" stroke-width="1.6"/>`});
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${g}</svg>`+
   `<div class="legend">${ks.map((k,j)=>`<span><i style="background:${cols[j%5]}"></i>${k}</span>`).join('')}</div>`;
}

// ── 两个策略表 ───────────────────────────────────────────
function tbl(rows,id){
  const cols=[['code','代码'],['name','名称'],['close','收盘'],['rps120','RPS120'],['rps250','RPS250'],
    ['newhigh','距一年高点'],['wrsi1','周RSI1'],['wrsi2','周RSI2'],['golddays','金叉N日'],
    ['turnover','换手%'],['dd20','结构回撤'],['fund','基金持仓%'],['north_yi','北向(亿)']];
  let sort=null,asc=false;
  const draw=()=>{
    const r=[...rows];
    if(sort)r.sort((a,b)=>{const x=a[sort],y=b[sort];const n=(v)=>v==null?-1e9:v;
      return asc?n(x)-n(y):n(y)-n(x)});
    document.getElementById(id).innerHTML=
     `<div class="scroll"><table><thead><tr>${cols.map(c=>`<th data-k="${c[0]}">${c[1]}</th>`).join('')}</tr></thead><tbody>`+
     r.map(x=>`<tr>${cols.map(c=>{const k=c[0];let v=x[k];
        if(k==='code'||k==='name')return `<td>${v??''}</td>`;
        if(k==='golddays')return `<td>${v==null?'<span class="badge">更早</span>':v}</td>`;
        if(k==='newhigh')return `<td class="${v>=.98?'pos':''}">${f(v,3)}</td>`;
        if(k==='rps120'||k==='rps250')return `<td class="${v>=90?'pos':''}">${f(v,1)}</td>`;
        if(k==='wrsi1')return `<td class="${v>=50?'pos':'neg'}">${f(v,1)}</td>`;
        return `<td>${typeof v==='number'?f(v,2):'—'}</td>`}).join('')}</tr>`).join('')+
     `</tbody></table></div>`+
     `<div class="note">共 ${r.length} 只 · 点击表头排序</div>`;
    document.querySelectorAll('#'+id+' th').forEach(t=>t.onclick=()=>{
      const k=t.dataset.k;asc=(sort===k)?!asc:false;sort=k;draw()});
  };draw();
}
const pk=document.getElementById('pick');
pk.innerHTML=['s1','s2'].map((k,i)=>`<div class="card"><h2>${
  i?'策略2 · RPS + 接近一年新高 (C/HHV(H,250)>0.90)':'策略1 · RPS + 周线RSI多头确认'}</h2>
  <div id="${k}"></div></div>`).join('');
tbl(D.s1,'s1');tbl(D.s2,'s2');

// ── 卖出提示 ────────────────────────────────────────────
(function(){
 const S=D.sell||[];const el=document.getElementById('sellbox');
 if(!S.length){el.innerHTML='<div class="note">近 '+(D.sell_win||10)+' 个交易日内没有股票出现周线 RSI 死叉。</div>';return}
 el.innerHTML=`<div class="scroll"><table><thead><tr><th>代码</th><th>名称</th><th>收盘</th>
  <th>死叉距今</th><th>上次入选</th><th>周RSI1</th><th>周RSI2</th><th>RPS合计</th><th>近120日入选过</th></tr></thead><tbody>`+
  S.map(x=>`<tr><td>${x.code}</td><td>${x.name||''}</td><td>${f(x.close,2)}</td>
   <td class="${x.days<=2?'neg':''}">${x.days==null?'—':x.days+'日'}</td>
   <td class="${x.pick_age!=null&&x.pick_age<=15?'neg':''}">${x.pick_age==null?'—':x.pick_age+'日前'}</td>
   <td class="${x.wrsi1>=50?'pos':'neg'}">${f(x.wrsi1,1)}</td><td>${f(x.wrsi2,1)}</td>
   <td>${f(x.rps_sum,1)}</td><td>${[x.was_s1?'S1':null,x.was_s2?'S2':null].filter(Boolean).join('+')||'—'}</td></tr>`).join('')+
   `</tbody></table></div><div class="note">口径：周线 RSI1 下穿 RSI2 且 RSI1 &lt; RSI3(50轴) 的那一根, 只列近 ${D.sell_win} 个交易日内死叉、且近 ${D.pick_lookback} 个交易日内入选过策略的票。"上次入选"越近说明这越是真实持仓的出场信号; 回测的出场即使用该死叉信号。</div>`;
})();

// ── 回测 ────────────────────────────────────────────────
if(D.bt&&D.bt.nav){
  const s=D.bt.nav.series,dates=D.bt.nav.dates;
  const lbl=dates.map((d,i)=>i%Math.ceil(dates.length/7)===0?d.slice(0,7):'');
  line(document.getElementById('nav'),s,{h:320,zero:1,labels:lbl,dp:2});
  const m=D.bt.metrics||{};
  document.getElementById('nav').insertAdjacentHTML('afterbegin',Object.keys(m).map(k=>{
    const x=m[k];return `<div class="kv"><div>方案<b>${k}</b></div><div>年化<b class="${cls(x['年化'])}">${pct(x['年化'])}</b></div>`+
    `<div>总收益<b class="${cls(x['总收益'])}">${pct(x['总收益'])}</b></div>`+
    `<div>最大回撤<b class="neg">${pct(x['最大回撤'])}</b></div><div>夏普<b>${f(x['夏普'],2)}</b></div>`+
    `<div>胜率<b>${pct(x['胜率'],0)}</b></div><div>盈亏比<b>${f(x['盈亏比'],2)}</b></div>`+
    `<div>交易数<b>${x['交易数']??"—"}</b></div><div>均持有<b>${x['平均持有天数']??"—"}日</b></div>`+
    `<div>基准同期<b class="${cls(x['基准同期'])}">${pct(x['基准同期'])}</b></div></div>`}).join(''));
}
// ── 敏感性 ──────────────────────────────────────────────
if(D.bt&&D.bt.sweep&&D.bt.sweep.length){
  const sw=D.bt.sweep;
  const cols=[['universe','样本'],['strategy','策略'],['sell_mode','卖出口径'],['max_pos','持仓数'],
    ['three_line','RSI3=MA24'],['rps_sum','RPS阈值'],['年化','年化'],['总收益','总收益'],['最大回撤','最大回撤'],
    ['夏普','夏普'],['胜率','胜率'],['盈亏比','盈亏比'],['交易数','交易数'],['平均持有天数','均持有日'],
    ['超时平仓占比','超时占比'],['基准同期','基准同期']];
  document.getElementById('sweep').innerHTML=
   `<table><thead><tr>${cols.map(c=>`<th>${c[1]}</th>`).join('')}</tr></thead><tbody>`+
   sw.map(r=>`<tr>${cols.map(c=>{let v=r[c[0]];
     if(typeof v==='boolean')return `<td>${v?'是':'否'}</td>`;
     if(['年化','总收益','最大回撤','胜率','超时平仓占比','基准同期'].includes(c[0]))
       return `<td class="${cls(v)}">${v==null?'—':pct(v)}</td>`;
     if(['夏普','盈亏比','平均持有天数'].includes(c[0]))return `<td>${f(v,2)}</td>`;
     return `<td>${v??'—'}</td>`}).join('')}</tr>`).join('')+`</tbody></table>`;
}
// ── 交易明细 ────────────────────────────────────────────
const TT=D.bt&&D.bt.trades||{};const ks=Object.keys(TT);
if(ks.length){
  const box=document.getElementById('ttabs');
  const draw=(k)=>{const r=TT[k];
    document.getElementById('trades').innerHTML=
     `<table><thead><tr><th>代码</th><th>名称</th><th>买入日</th><th>卖出日</th><th>持有</th><th>收益</th><th>卖出理由</th></tr></thead><tbody>`+
     r.map(x=>`<tr><td>${x.code}</td><td>${x.name||''}</td><td>${x.entry_date}</td><td>${x.exit_date}</td>`+
       `<td>${x.days}</td><td class="${cls(x.ret)}">${pct(x.ret)}</td><td>${x.reason}</td></tr>`).join('')+
     `</tbody></table>`;
    [...box.children].forEach(b=>b.classList.toggle('on',b.dataset.k===k))};
  box.innerHTML=ks.map(k=>`<button data-k="${k}">${k}</button>`).join('');
  [...box.children].forEach(b=>b.onclick=()=>draw(b.dataset.k));draw(ks[0]);
}
// ── 历史入选数 ──────────────────────────────────────────
if(D.hist&&D.hist.length>1){
  const series={策略1:D.hist.map(h=>h.s1),策略2:D.hist.map(h=>h.s2),过RPS选股:D.hist.map(h=>h.all)};
  line(document.getElementById('sig'),series,{h:170,labels:D.hist.map(h=>h.d),dp:1,lo0:true});
  document.getElementById('sig').insertAdjacentHTML('beforeend',
    `<div class="note">共 ${D.hist.length} 个交易日。${D.hist_from==='backtest'
      ? '整段曲线由回测逐日重放得到(与每日筛选同一套信号), 之后每日跑 run_daily.sh 还会留下真实快照。'
      : '来自 out/screen/ 的历史快照, 每日跑 run_daily.sh 会逐日累积。'}</div>`);
}else{document.getElementById('sig').innerHTML='<div class="note">历史记录不足: 需要 backtest --counts 或至少 2 天的 screen 快照。</div>'}
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--tag", default="main", help="回测产物后缀 nav_all_<tag>.csv")
    ap.add_argument("--out")
    a = ap.parse_args()
    sd = latest_screen_dir(a.date)
    dash = json.load(open(os.path.join(sd, "dashboard.json"), encoding="utf-8"))
    dash["hist"], dash["hist_from"] = hist_dates(a.tag)
    dash["bt"] = read_bt(a.tag)
    html = HTML.replace("__DATA__", json.dumps(dash, ensure_ascii=False))
    outp = a.out or OUTHTML
    with open(outp, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"看板 -> {outp}   ({os.path.getsize(outp)/1024:.0f} KB)   "
          f"策略1 {len(dash['s1'])} 只 / 策略2 {len(dash['s2'])} 只")


if __name__ == "__main__":
    main()
