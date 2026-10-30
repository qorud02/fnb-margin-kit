"""A self-contained Korean purchasing report using the exact procurement result."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from html import escape


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _amount(value: dict, unit: str = "") -> str:
    """Round only the displayed number; retain its exact fraction in the title."""
    numerator = int(value["numerator"])
    denominator = int(value["denominator"])
    with localcontext() as context:
        context.prec = max(80, len(str(abs(numerator))) + len(str(denominator)) + 12)
        displayed = (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
    approximate = Fraction(displayed) != Fraction(numerator, denominator)
    number = format(displayed, ",f").rstrip("0").rstrip(".")
    if not number or number == "-0":
        number = "0"
    title = f"정확값: {numerator}/{denominator}; 소수 표시: {value['decimal']}"
    suffix = f" {_text(unit)}" if unit else ""
    return (f'<span class="amount" title="{_text(title)}">'
            f'{"≈" if approximate else ""}{number}{suffix}</span>')


def render_procurement_html(report: dict) -> str:
    """Render a plan, not an order or measured business result; never recalculate it."""
    summary = report["summary"]
    purchase_rows = []
    demand_rows = []
    for row in report["ingredients"]:
        name = _text(row["ingredient"])
        unit = row["base_unit"]
        packs = _text(row["purchase_packs"])
        status = "구매 필요" if row["purchase_packs"] else "추가 구매 없음"
        purchase_rows.append(
            f'<tr><th scope="row">{name}<small>{status}</small></th>'
            f'<td>{_text(row["purchase_quantity"])} {_text(row["purchase_unit"])}'
            f'<small>포장당 가격 {_text(row["purchase_price"])}</small></td>'
            f'<td class="num">{packs}</td>'
            f'<td class="num">{_amount(row["purchased_quantity_base"], unit)}</td>'
            f'<td class="num">{_amount(row["purchase_spend"])}</td>'
            f'<td class="num">{_amount(row["remaining_stock_base"], unit)}</td></tr>'
        )
        demand_rows.append(
            f'<tr><th scope="row">{name}</th>'
            f'<td class="num">{_amount(row["edible_required_base"], unit)}</td>'
            f'<td class="num">{_amount(row["gross_required_base"], unit)}</td>'
            f'<td class="num">{_amount(row["stock_base"], unit)}</td>'
            f'<td class="num">{_amount(row["shortage_base"], unit)}</td></tr>'
        )
    plan_rows = "".join(
        f'<tr><th scope="row">{_text(row["menu"])}</th>'
        f'<td>{_text(row["category"])}</td><td class="num">{_text(row["units"])}</td></tr>'
        for row in report["plan"]
    )
    return """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>재료 구매계획 | F&amp;B Margin Kit</title>
<style>
:root{color-scheme:light;font-family:system-ui,-apple-system,"Malgun Gothic",sans-serif;color:#183245;background:#edf2f5}
*{box-sizing:border-box}body{margin:0;padding:32px 20px}main{max-width:1160px;margin:auto;background:white;padding:36px;border-radius:16px;box-shadow:0 10px 36px #18324512}
.eyebrow{font-size:13px;letter-spacing:.06em;color:#526a78}h1{font-size:32px;margin:10px 0 14px}h2{font-size:21px;margin:32px 0 10px}p{line-height:1.7}.lead{max-width:850px;color:#425c6b}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:25px 0}.card{background:#f0f6f8;padding:18px;border:1px solid #d9e5ea;border-radius:9px}.card .label{display:block;font-size:13px;margin-bottom:10px}.card strong{font-size:23px;overflow-wrap:anywhere}.card small{margin-top:5px}
.table-wrap{overflow-x:auto;border:1px solid #cfdae0;border-radius:8px}table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.6}th,td{padding:12px 10px;border-bottom:1px solid #dfe7eb;text-align:left;vertical-align:top}thead th{background:#edf3f6;font-weight:700;white-space:nowrap}tbody th{font-weight:600;min-width:120px}.num{text-align:right;font-variant-numeric:tabular-nums}.amount{overflow-wrap:anywhere}small{display:block;font-size:12px;color:#526a78;font-weight:400}tr:last-child>*{border-bottom:0}.note{font-size:13px;color:#526a78}.basis{border-top:1px solid #d3dfe5;margin-top:30px;padding-top:16px}.basis li{line-height:1.7;margin:6px 0}footer{margin-top:26px;color:#526a78;font-size:12px}
@media(max-width:700px){body{padding:10px}main{padding:20px 14px;border-radius:8px}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.card{padding:12px}.card strong{font-size:20px}h1{font-size:27px}th,td{padding:10px 8px}}
@page{size:A4 landscape;margin:12mm}
@media print{:root,body{background:white}body{padding:0}main{max-width:none;padding:0;border-radius:0;box-shadow:none}.cards{grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.card{padding:10px;break-inside:avoid}.table-wrap{overflow:visible}table{font-size:10px;table-layout:fixed}th,td{padding:7px 5px;overflow-wrap:anywhere}thead{display:table-header-group}thead th{white-space:normal}tbody th{min-width:0}tr{break-inside:avoid}h2{break-after:avoid;font-size:17px}.note,.basis li{font-size:10px}small{font-size:9px}h1{font-size:25px}}
</style></head><body><main>
<div class="eyebrow">F&amp;B MARGIN KIT · PURCHASE PLAN</div>
<h1>재료 구매계획</h1>
<p class="lead">판매계획과 레시피, 보유한 원물 재고를 바탕으로 추가 구매할 포장 수와 예상 지출을 정리했습니다. 구매 후 계획대로 사용했을 때 남는 재고도 함께 확인할 수 있습니다.</p>
<div class="cards">
""" + (
        f'<div class="card"><span class="label">계획 판매 수량</span><strong>{_text(summary["planned_menu_units"])}</strong><small>메뉴 수량의 합계</small></div>'
        f'<div class="card"><span class="label">구매가 필요한 재료</span><strong>{_text(summary["purchase_ingredient_count"])}종</strong><small>전체 {_text(summary["ingredient_count"])}종 중</small></div>'
        f'<div class="card"><span class="label">구매할 포장 수</span><strong>{_text(summary["total_purchase_packs"])}개</strong><small>재료별 완전 포장 수의 합계</small></div>'
        f'<div class="card"><span class="label">예상 구매 지출 · 부가세 제외</span><strong>{_amount(summary["total_purchase_spend"])}</strong><small>입력한 가격의 동일 통화 단위</small></div>'
        '</div><h2>1. 구매할 내역</h2>'
        '<div class="table-wrap"><table aria-label="재료별 구매 내역"><thead><tr>'
        '<th scope="col">재료</th><th scope="col">1포장 구성 · 세전 가격</th><th scope="col">구매 포장 수</th>'
        '<th scope="col">구매 원물량</th><th scope="col">구매 지출</th><th scope="col">사용 후 예상 잔량</th>'
        '</tr></thead><tbody>' + "".join(purchase_rows) + '</tbody></table></div>'
        '<p class="note">추가 구매가 없는 재료도 표시합니다. 품목별 g·ml·each는 서로 다른 단위이며 합산하지 않습니다.</p>'
        '<h2>2. 필요량과 현재 재고</h2><div class="table-wrap"><table aria-label="재료 필요량과 원물 재고">'
        '<thead><tr><th scope="col">재료</th><th scope="col">가식부 필요량</th><th scope="col">준비 손실을 반영한 원물 필요량</th>'
        '<th scope="col">현재 원물 재고</th><th scope="col">부족 원물량</th></tr></thead><tbody>'
        + "".join(demand_rows) + '</tbody></table></div>'
        '<h2>3. 기준 판매계획</h2><div class="table-wrap"><table aria-label="기준 판매계획"><thead><tr>'
        '<th scope="col">메뉴</th><th scope="col">구분</th><th scope="col">판매계획 수량</th>'
        '</tr></thead><tbody>' + plan_rows + '</tbody></table></div>'
    ) + """
<section class="basis"><h2>계산과 사용 기준</h2><ul>
<li>원물 필요량은 레시피의 가식부 수량을 준비 수율로 나눈 값입니다. 여러 메뉴에서 쓰는 재료를 합친 뒤 현재 원물 재고를 한 번 차감합니다.</li>
<li>부족량이 생기면 구매 포장 단위로 올림합니다. 예상 잔량 = 현재 재고 + 구매 원물량 − 원물 필요량입니다.</li>
<li>포장 가격은 부가세를 제외한 동일 통화 기준입니다. 부가세·배송비·최소 주문금액은 추가 계산하지 않습니다.</li>
<li>화면의 수량과 금액은 소수점 4자리까지 반올림합니다. ≈는 표시를 줄인 값입니다. 각 수치의 도움말과 procurement.json에 정확한 분자·분모를 보관하며, 표시 반올림은 구매 수량 계산에 영향을 주지 않습니다.</li>
<li>유통기한·예약 재고·거래처 납기·최소 주문량은 입력에 포함되지 않습니다. 실제 발주 전 재고와 거래조건을 확인해 주세요.</li>
</ul><p class="note">이 파일은 입력한 계획의 계산 보고서입니다. 거래처에 전송된 발주서나 실제 매출·재고 실적이 아닙니다. 인쇄는 브라우저의 인쇄 메뉴에서 가로 방향을 사용하세요.</p></section>
<footer>외부 글꼴·스크립트·서버 연결 없이 열리는 독립 HTML 보고서입니다. 재료·원가 정보가 포함되므로 열람 권한이 있는 사람에게 공유해 주세요.</footer>
</main></body></html>
"""
