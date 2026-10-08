"""Self-contained operator dashboard for an existing contribution report."""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal, localcontext
from html import escape

from ._decimal import decimal_context

NUMERIC_FIELDS = (
    "units", "net_price_per_unit", "platform_fee_per_unit",
    "variable_cost_per_unit", "contribution_per_unit", "total_contribution",
)
MARGINS = {"positive": "양수 / Positive", "zero": "0 / Zero", "negative": "음수 / Negative"}


def amount(value: str) -> str:
    with localcontext(decimal_context(80)):
        return f"{Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def safe_json(value: object) -> str:
    """Keep JSON data inside its script element, including adversarial CSV text."""
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def sum_reported_values(values: list[str]) -> Decimal:
    """Sum the already-computed strings without adding order-dependent rounding."""
    decimals = [Decimal(value) for value in values]
    if not decimals:
        return Decimal(0)
    with localcontext(decimal_context(80)) as ctx:
        ctx.prec = max(
            80,
            max(value.adjusted() for value in decimals)
            - min(value.as_tuple().exponent for value in decimals)
            + len(str(len(decimals))) + 2,
        )
        return sum(decimals, Decimal(0))


def dashboard_data(report: dict) -> dict:
    """Retain decimal strings and create exact, bounded numeric sort ranks."""
    menus = report["menus"]
    ranks = {}
    for field in NUMERIC_FIELDS:
        values = sorted({Decimal(str(row[field])) for row in menus})
        ranks[field] = {value: index for index, value in enumerate(values)}
    rows = []
    for row in menus:
        values = {field: str(row[field]) for field in NUMERIC_FIELDS}
        rows.append({
            "rank": row["rank"], "menu": row["menu"], "category": row["category"],
            "margin_flag": row["margin_flag"], "values": values,
            "display": {field: f"{row[field]:,}" if field == "units" else amount(values[field])
                        for field in NUMERIC_FIELDS},
            "sort": {field: ranks[field][Decimal(values[field])] for field in NUMERIC_FIELDS},
        })
    if "channel_cost_scenario" in report:
        categories = [dict(row, units=str(row["units"]))
                      for row in report["channel_cost_scenario"]["categories"]]
    else:
        grouped = {}
        for row in menus:
            record = grouped.setdefault(row["category"], {"units": 0, "contributions": []})
            record["units"] += row["units"]
            record["contributions"].append(row["total_contribution"])
        categories = [{
            "category": key, "units": str(grouped[key]["units"]),
            "contribution_before_additional_cost": format(sum_reported_values(grouped[key]["contributions"]), "f"),
            "additional_variable_cost": "0",
            "contribution_after_additional_cost": format(sum_reported_values(grouped[key]["contributions"]), "f"),
        } for key in sorted(grouped)]
    summary = dict(report["totals"], total_units=str(report["total_units"]))
    for key in ("channel_cost_scenario", "fixed_cost_scenario"):
        if key in report:
            summary[key] = {field: value for field, value in report[key].items() if field != "categories"}
    return {"summary": summary, "categories": categories, "menus": rows}


def value_html(value: str, *, count: bool = False) -> str:
    rounded = f"{int(value):,}" if count else amount(value)
    return (f'<span class="amount" data-exact="{escape(value, quote=True)}" '
            f'data-rounded="{escape(rounded, quote=True)}" title="{escape(value, quote=True)}">'
            f'{escape(rounded)}</span>')


def render_html(report: dict) -> str:
    """Render without changing the source report or inferring its monetary unit."""
    data = dashboard_data(report)
    has_costs = "channel_cost_scenario" in report
    totals = report["totals"]
    cards = [
        ("판매 수량", "Units sold", str(report["total_units"]), True),
        ("부가세 제외 매출", "VAT-exclusive sales", totals["net_sales"], False),
        ("추가 채널비·고정비 차감 전" if has_costs else "고정비 차감 전 공헌이익",
         "Before additional channel and fixed costs" if has_costs else "Contribution before fixed costs",
         totals["contribution"], False),
    ]
    if has_costs:
        cards.append(("추가 채널비 차감 후 · 고정비 차감 전", "After channel costs, before fixed cost",
                      report["channel_cost_scenario"]["contribution_after_additional_costs"], False))
    if "fixed_cost_scenario" in report:
        cards.append(("지정 고정비 차감 후 공헌이익", "Contribution after specified fixed cost",
                      report["fixed_cost_scenario"]["contribution_after_specified_fixed_cost"], False))
    card_html = []
    for index, (label, english, value, count) in enumerate(cards):
        highlight = " highlight" if index == len(cards) - 1 and len(cards) > 3 else ""
        negative = " negative" if Decimal(value) < 0 else ""
        card_html.append(f'<article class="card{highlight}{negative}"><p>{escape(label)}'
                         f'<small lang="en">{escape(english)}</small></p><strong>'
                         f'{value_html(value, count=count)}</strong></article>')
    cost_details = []
    if has_costs:
        cost_details.append("추가 채널 변동비 / Additional channel costs: "
                            + value_html(report["channel_cost_scenario"]["total_additional_variable_cost"]))
    if "fixed_cost_scenario" in report:
        cost_details.append("지정 고정비 / Specified fixed cost: "
                            + value_html(report["fixed_cost_scenario"]["specified_fixed_cost"]))
    channels = []
    maximum = max((Decimal(row["contribution_after_additional_cost"]).copy_abs() for row in data["categories"]), default=Decimal(0))
    for row in data["categories"]:
        value = Decimal(row["contribution_after_additional_cost"])
        with localcontext(decimal_context(80)):
            width = format(abs(value) / maximum * 100, ".2f") if maximum else "0.00"
        side = "negative" if value < 0 else "positive"
        channels.append(
            '<tr><th scope="row">' + escape(row["category"]) + '</th><td class="num">'
            + value_html(row["units"], count=True) + '</td><td class="num">'
            + value_html(row["contribution_before_additional_cost"]) + '</td><td class="num">'
            + value_html(row["additional_variable_cost"]) + '</td><td class="bar-cell">'
            + f'<div class="bar-space" aria-hidden="true"><span class="bar {side}" style="width:{width}%"></span></div>'
            + '</td><td class="num ' + side + '">'
            + value_html(row["contribution_after_additional_cost"]) + '</td></tr>'
        )
    menu_rows = []
    for row in data["menus"]:
        cells = [f'<td class="num">{row["rank"]}</td>', '<th scope="row">' + escape(row["menu"]) + '</th>',
                 '<td>' + escape(row["category"]) + '</td>']
        for field in NUMERIC_FIELDS:
            cells.append('<td class="num">' + value_html(row["values"][field], count=field == "units") + '</td>')
        cells.append('<td><span class="badge ' + row["margin_flag"] + '">' + MARGINS[row["margin_flag"]] + '</span></td>')
        menu_rows.append('<tr>' + ''.join(cells) + '</tr>')
    categories = sorted({row["category"] for row in data["menus"]})
    options = ''.join(f'<option value="{escape(category, quote=True)}">{escape(category)}</option>' for category in categories)
    parts = {
        "CARDS": ''.join(card_html), "COST_DETAILS": ' · '.join(cost_details),
        "CHANNEL_ROWS": ''.join(channels), "MENU_ROWS": ''.join(menu_rows),
        "CATEGORY_OPTIONS": options, "MENU_COUNT": str(len(data["menus"])), "PAYLOAD": safe_json(data),
        "CHANNEL_BASIS": ("막대와 오른쪽 금액은 추가 채널비 차감 후, 지정 고정비 차감 전 공헌이익입니다."
                          if has_costs else "채널별 금액은 메뉴 공헌이익의 합계이며, 지정 고정비 차감 전입니다."),
    }
    # One substitution pass prevents CSV text resembling a template token from being expanded.
    return re.sub(r"@@([A-Z_]+)@@", lambda match: parts[match[1]], TEMPLATE)


TEMPLATE = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; font-src 'none'; base-uri 'none'; form-action 'none'">
<title>메뉴별 공헌이익 | F&amp;B Margin Kit</title>
<style>
:root{color-scheme:light;--ink:#172b43;--muted:#5c6d82;--line:#dce4ee;--teal:#087f85;--red:#b33c4f;--paper:#f4f7fb}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5}
button,input,select{font:inherit}button,input,select:focus{outline-offset:3px}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #30bfc4}
.shell{max-width:1510px;margin:auto;padding:32px 36px 48px}.brand{font-weight:750;letter-spacing:.03em;font-size:14px}.top{display:flex;justify-content:space-between;align-items:center;gap:20px}.offline{color:var(--teal);font-size:12px;margin-top:4px}
button{cursor:pointer;border:1px solid #b9c7d7;border-radius:9px;padding:9px 16px;color:var(--ink);background:#fff;font-weight:650}button:hover{background:#edf3f9}
h1{font-size:clamp(25px,3vw,38px);line-height:1.25;letter-spacing:-.04em;margin:28px 0 8px}h1 span{font-size:15px;font-weight:450;display:block;color:var(--muted);letter-spacing:0;margin-top:8px}.intro{color:var(--muted);margin:0 0 24px}
.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin:0 0 17px}h2{font-size:19px;margin:0;letter-spacing:-.02em}h2 small{display:block;font-size:11px;font-weight:500;letter-spacing:.04em;color:var(--muted);margin-top:3px;text-transform:uppercase}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.card{padding:20px 21px;background:#fff;border:1px solid var(--line);border-radius:13px;min-height:133px}.card p{margin:0;font-weight:600;font-size:13px;min-height:46px}.card small{display:block;color:var(--muted);font-size:11px;font-weight:400;margin-top:4px}.card strong{display:block;font-size:clamp(24px,2.2vw,32px);font-variant-numeric:tabular-nums;letter-spacing:-.035em;overflow-wrap:anywhere;margin-top:10px}.card.highlight{background:var(--ink);color:#fff;border-color:var(--ink)}.card.highlight small{color:#bbcbdc}.card.negative strong{color:var(--red)}.card.highlight.negative strong{color:#ffb0bc}
.cost-details{color:var(--muted);font-size:12px;margin:12px 0 0}.panel{background:#fff;border:1px solid var(--line);border-radius:14px;padding:24px;margin-top:24px}.note{font-size:12px;color:var(--muted);margin:12px 0 0}.subtle{color:var(--muted)}.exact-control{font-size:12px;display:flex;align-items:center;gap:7px;white-space:nowrap}.exact-control input{width:16px;height:16px;accent-color:var(--teal)}
.scroll{overflow-x:auto}.scroll:focus-visible{outline:3px solid #30bfc4;outline-offset:3px}.scroll-hint{display:none}table{width:100%;border-collapse:collapse;text-align:left;font-size:13px;font-variant-numeric:tabular-nums}th,td{padding:13px 12px;border-bottom:1px solid var(--line);vertical-align:middle}thead th{background:#f4f7fb;color:#4e627b;font-size:11px;font-weight:650}thead th small{display:block;font-weight:400;margin-top:3px}tbody th{font-weight:600}tbody tr:last-child th,tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:#f8fbfd}.num{text-align:right;white-space:nowrap}tbody th,tbody td:not(.num){overflow-wrap:anywhere}.positive{color:var(--teal)}.negative{color:var(--red)}.zero{color:var(--muted)}
.channel-table{min-width:780px}.bar-cell{width:22%;min-width:130px}.bar-space{height:10px;display:grid;grid-template-columns:1fr 1fr;position:relative;background:#f3f6fa}.bar-space:before{content:"";position:absolute;left:50%;height:16px;top:-3px;border-left:1px solid #b8c5d4}.bar{height:10px;border-radius:2px}.bar.positive{grid-column:2;background:var(--teal)}.bar.negative{grid-column:1;background:var(--red);justify-self:end}
.controls{display:grid;grid-template-columns:minmax(180px,1.7fr) repeat(3,minmax(145px,1fr)) auto;gap:12px;align-items:end;margin-bottom:14px}.control label{font-size:11px;font-weight:650;display:block;margin-bottom:6px}.control input,.control select{width:100%;border:1px solid #bdcbdc;border-radius:8px;padding:9px 10px;background:#fff;color:var(--ink);min-height:42px}.controls button{height:42px}.menu-table{min-width:1170px}.badge{display:inline-block;border-radius:5px;padding:3px 7px;font-size:10px;white-space:nowrap;background:#eef7f6}.badge.negative{background:#fff0f2}.badge.zero{background:#edf1f6}.count{font-size:12px;color:var(--muted);margin:0 0 13px}.empty{padding:30px;text-align:center;color:var(--muted)}.footer{margin-top:24px;color:var(--muted);font-size:12px}.footer p{margin:5px 0}.noscript{background:#fff5da;color:#715a14;border-radius:8px;padding:12px;font-size:13px}
@media(max-width:850px){.shell{padding:24px 18px 32px}.controls{grid-template-columns:1fr 1fr}.controls .control:first-child{grid-column:1/-1}.controls button{justify-self:start}.panel{padding:18px}.section-head{flex-wrap:wrap}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.card{padding:16px;min-height:142px}.card strong{font-size:25px}.exact-control{white-space:normal}.scroll-hint{display:block;font-size:11px;color:var(--muted);margin:10px 0}}
@media(max-width:420px){.cards{grid-template-columns:1fr}.top{gap:12px}.top button{padding:8px 11px}.controls{grid-template-columns:1fr}.controls .control:first-child{grid-column:auto}}
@page{size:A4 landscape;margin:12mm}
@media print{body{background:#fff;color:#111}.shell{max-width:none;padding:0}.top button,.controls,.exact-control,.noscript,.scroll-hint{display:none!important}h1{font-size:23px;margin-top:15px}.intro{margin-bottom:15px}.cards{grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.card{min-height:100px;padding:12px;border-radius:0;background:#fff!important;color:#111!important}.card p{font-size:10px;min-height:38px}.card small{color:#555!important}.card strong{font-size:19px}.panel{padding:15px 0;border:0;border-top:1px solid #bbb;border-radius:0;margin-top:20px}.scroll{overflow:visible}table,.channel-table,.menu-table{min-width:0;width:100%;font-size:9px;table-layout:fixed}th,td{padding:7px 4px;white-space:normal!important;overflow-wrap:anywhere}thead{display:table-header-group}thead th{font-size:8px}tr{break-inside:avoid}.section-head{break-after:avoid}h2{font-size:15px}.badge{white-space:normal;font-size:8px;padding:2px}.bar-cell{min-width:0}.bar,.badge{print-color-adjust:exact;-webkit-print-color-adjust:exact}.note,.footer,.count{font-size:10px}}
</style>
</head>
<body>
<main class="shell">
<header class="top"><div><div class="brand">F&amp;B MARGIN KIT</div><div class="offline">오프라인 리포트 · Offline report</div></div><button id="print-button" type="button">인쇄 / Print</button></header>
<h1>메뉴별 공헌이익<span lang="en">Sales-mix contribution dashboard</span></h1>
<p class="intro">원가와 수수료를 차감한 메뉴·채널별 공헌이익을 확인하세요.</p>
<section aria-labelledby="summary-title"><div class="section-head"><h2 id="summary-title">전체 요약<small lang="en">Report totals</small></h2><label class="exact-control"><input id="exact-values" type="checkbox">정밀한 계산값 보기 / Exact decimals</label></div><div class="cards">@@CARDS@@</div><p class="cost-details">@@COST_DETAILS@@</p></section>
<section class="panel" aria-labelledby="channel-title"><div class="section-head"><h2 id="channel-title">채널별 공헌이익 비교<small lang="en">Category contribution comparison</small></h2></div><p class="scroll-hint">표를 가로로 움직이면 모든 열을 볼 수 있습니다.</p><div class="scroll" tabindex="0" role="region" aria-label="채널별 공헌이익 표 / Category contribution table"><table class="channel-table"><thead><tr><th scope="col">채널·분류<small>Category</small></th><th scope="col" class="num">수량<small>Units</small></th><th scope="col" class="num">추가 채널비 차감 전<small>Before channel costs</small></th><th scope="col" class="num">추가 채널비<small>Additional cost</small></th><th scope="col">음수 ← 0 → 양수<small>Contribution magnitude</small></th><th scope="col" class="num">고정비 차감 전<small>Before fixed cost</small></th></tr></thead><tbody>@@CHANNEL_ROWS@@</tbody></table></div><p class="note">@@CHANNEL_BASIS@@ 채널은 CSV의 category 분류입니다.</p></section>
<section class="panel" aria-labelledby="menus-title"><div class="section-head"><h2 id="menus-title">전체 메뉴표<small lang="en">Menu contributions</small></h2></div>
<noscript><p class="noscript">전체 결과는 아래 표에 있습니다. 검색·필터·정렬·정밀도 전환은 JavaScript를 켜면 사용할 수 있습니다.</p></noscript>
<div class="controls"><div class="control"><label for="search">메뉴·분류 검색 / Search</label><input id="search" type="search" placeholder="메뉴 또는 분류" autocomplete="off"></div><div class="control"><label for="category">채널·분류 / Category</label><select id="category"><option value="">전체 / All</option>@@CATEGORY_OPTIONS@@</select></div><div class="control"><label for="margin">단위 공헌이익 / Unit margin</label><select id="margin"><option value="">전체 / All</option><option value="negative">음수 / Negative</option><option value="zero">0 / Zero</option><option value="positive">양수 / Positive</option></select></div><div class="control"><label for="sort">정렬 / Sort</label><select id="sort"><option value="total_desc">총 공헌이익 높은 순</option><option value="total_asc">총 공헌이익 낮은 순</option><option value="unit_desc">단위 공헌이익 높은 순</option><option value="unit_asc">단위 공헌이익 낮은 순</option><option value="units_desc">판매 수량 높은 순</option><option value="menu_asc">메뉴 이름순</option><option value="category_asc">분류 이름순</option></select></div><button id="reset" type="button">초기화 / Reset</button></div>
<p id="menu-count" class="count" role="status" aria-live="polite">총 @@MENU_COUNT@@개 메뉴 · 전체 입력 기준 순위 / Original ranks</p><p class="scroll-hint">표를 가로로 움직이면 모든 열을 볼 수 있습니다.</p><div class="scroll" tabindex="0" role="region" aria-label="메뉴 공헌이익 표 / Menu contribution table"><table class="menu-table"><thead><tr><th scope="col" class="num">순위<small>Rank</small></th><th scope="col">메뉴<small>Menu</small></th><th scope="col">채널·분류<small>Category</small></th><th scope="col" class="num">수량<small>Units</small></th><th scope="col" class="num">부가세 제외 단가<small>Net price/unit</small></th><th scope="col" class="num">수수료/개<small>Fee/unit</small></th><th scope="col" class="num">변동비/개<small>Variable cost/unit</small></th><th scope="col" class="num">공헌이익/개<small>Contribution/unit</small></th><th scope="col" class="num">총 공헌이익<small>Total contribution</small></th><th scope="col">단위 이익 상태<small>Unit margin</small></th></tr></thead><tbody id="menu-body">@@MENU_ROWS@@</tbody></table></div><p class="note">요약과 채널 비교는 전체 입력 기준입니다. 검색과 필터는 메뉴표에 적용됩니다. 메뉴별 금액과 순위는 추가 채널비·고정비를 배분하기 전입니다.</p></section>
<footer class="footer"><p>금액은 입력한 금액 단위를 사용합니다. 기본 표시는 소수 둘째 자리 반올림이며, 정밀한 계산값 보기에서 반올림 전 계산값을 확인할 수 있습니다.</p><p>매출은 부가세를 제외하고, 플랫폼 수수료는 부가세 포함 판매가를 기준으로 계산합니다. 재료비·포장비·추가 채널비는 부가세 제외 입력값을 사용합니다.</p><p>지정한 비용만 차감합니다. 그 밖의 운영비와 소득세는 계산에 포함되지 않습니다.</p></footer>
</main>
<script id="report-data" type="application/json">@@PAYLOAD@@</script>
<script>
"use strict";
const data = JSON.parse(document.getElementById("report-data").textContent);
const search = document.getElementById("search");
const category = document.getElementById("category");
const margin = document.getElementById("margin");
const sorting = document.getElementById("sort");
const exact = document.getElementById("exact-values");
const body = document.getElementById("menu-body");
const numericFields = ["units", "net_price_per_unit", "platform_fee_per_unit", "variable_cost_per_unit", "contribution_per_unit", "total_contribution"];
const marginLabels = {positive:"양수 / Positive", zero:"0 / Zero", negative:"음수 / Negative"};
const orders = {total_desc:["total_contribution",-1], total_asc:["total_contribution",1], unit_desc:["contribution_per_unit",-1], unit_asc:["contribution_per_unit",1], units_desc:["units",-1]};
function addCell(row, value, options = {}) {
  const cell = document.createElement(options.header ? "th" : "td");
  if (options.header) cell.scope = "row";
  if (options.numeric) cell.className = "num";
  if (options.raw !== undefined) cell.title = options.raw;
  cell.textContent = value;
  row.appendChild(cell);
  return cell;
}
function renderMenus() {
  const query = search.value.trim().toLocaleLowerCase();
  const visible = data.menus.filter(row => (!query || (row.menu + " " + row.category).toLocaleLowerCase().includes(query)) && (!category.value || row.category === category.value) && (!margin.value || row.margin_flag === margin.value));
  const order = orders[sorting.value];
  visible.sort((a,b) => {
    if (order) return (a.sort[order[0]] - b.sort[order[0]]) * order[1] || a.rank - b.rank;
    const field = sorting.value === "category_asc" ? "category" : "menu";
    return a[field].localeCompare(b[field],"ko") || a.rank - b.rank;
  });
  const fragment = document.createDocumentFragment();
  visible.forEach(row => {
    const tr = document.createElement("tr");
    addCell(tr, String(row.rank), {numeric:true});
    addCell(tr, row.menu, {header:true});
    addCell(tr, row.category);
    numericFields.forEach(field => addCell(tr, exact.checked ? row.values[field] : row.display[field], {numeric:true,raw:row.values[field]}));
    const cell = addCell(tr, "");
    const badge = document.createElement("span");
    badge.className = "badge " + row.margin_flag;
    badge.textContent = marginLabels[row.margin_flag];
    cell.appendChild(badge);
    fragment.appendChild(tr);
  });
  if (!visible.length) {
    const tr = document.createElement("tr");
    const cell = addCell(tr, "조건에 맞는 메뉴가 없습니다. / No matching menus");
    cell.colSpan = 10; cell.className = "empty"; fragment.appendChild(tr);
  }
  body.replaceChildren(fragment);
  document.getElementById("menu-count").textContent = "총 " + data.menus.length + "개 중 " + visible.length + "개 메뉴 · 전체 입력 기준 순위 / Original ranks";
}
search.addEventListener("input", renderMenus);
[category, margin, sorting].forEach(control => control.addEventListener("change", renderMenus));
exact.addEventListener("change", () => {
  document.querySelectorAll(".amount").forEach(element => { element.textContent = exact.checked ? element.dataset.exact : element.dataset.rounded; });
  renderMenus();
});
document.getElementById("reset").addEventListener("click", () => { search.value = ""; category.value = ""; margin.value = ""; sorting.value = "total_desc"; renderMenus(); });
document.getElementById("print-button").addEventListener("click", () => window.print());
renderMenus();
</script>
</body>
</html>
'''
