# 가격·원가·판매량 변경안 비교 / Price, cost and quantity scenarios

Prepare the current menu CSV and a proposed menu CSV with the same eight columns.
Change the proposed prices, costs, rates and quantities explicitly. Both files
must contain exactly the same `(menu, category)` pairs; their row and column order
can differ. Quantities cover the same period and represent the values you supply.

```console
fnb-margin examples/price-cost-scenarios/baseline.csv --compare-menu examples/price-cost-scenarios/proposed.csv --channel-costs examples/price-cost-scenarios/baseline-channel-costs.csv --compare-channel-costs examples/price-cost-scenarios/proposed-channel-costs.csv --fixed-cost 300000 --html --output-dir report-scenarios
```

The command writes the original baseline `report.json`, `report.md` and optional
`report.html` with the same contents as a run without comparison. It also writes
`comparison.json` and `comparison.md`. Each comparison includes both complete
contribution reports, changed menu inputs, each side's original ranking, sales
and contribution differences, and categories after their own channel costs.
Differences always mean **proposed minus baseline**.

Each side uses only its own channel-cost CSV. If `--compare-channel-costs` is
omitted, the proposed side has zero additional channel costs, even when the
baseline has `--channel-costs`. Supply the same CSV to both flags to hold those
costs constant. `--compare-channel-costs` requires `--compare-menu`.
The same `--fixed-cost` amount applies to both plans for the same period; it is
deducted at the overall level and is not allocated to categories or menus.

## Worked synthetic inputs

The example files contain four fictional menu/channel records. The proposed
store latte price rises from 5,500 to 6,050, ingredient cost from 1,200 to 1,350,
and supplied quantity changes from 100 to 90. Its unit contribution changes from
3,700 to 4,050, while total contribution changes from 370,000 to 364,500.

| Overall measure | Baseline | Proposed | Difference |
| --- | ---: | ---: | ---: |
| Menu contribution | 450,100 | 458,568 | 8,468 |
| Additional channel costs | 13,000 | 18,000 | 5,000 |
| Contribution after channel costs | 437,100 | 440,568 | 3,468 |
| Contribution after the same 300,000 fixed cost | 137,100 | 140,568 | 3,468 |

The delivery latte changes from 2,100 to 2,411 in contribution per unit and from
40 to 38 supplied units. VAT-exclusive sales use `price_gross / (1 + vat_rate)`;
the platform fee still uses the gross price, so its proposed fee is
`6050 × 0.18 = 1089` per unit.

## Quantity needed to retain a menu contribution

For a menu with positive baseline total contribution and positive proposed unit
contribution, the report provides the minimum whole number of proposed units:

```text
minimum units = ceil(baseline unit contribution × baseline units
                     / proposed unit contribution)
```

This quantity uses exact rational arithmetic on the **original CSV values**, so
the ceiling cannot round down at an integer boundary. Monetary reports keep the
existing 50-digit per-menu Decimal arithmetic and exact aggregation; repeating
VAT divisions can therefore display approximate decimal amounts while the
quantity threshold follows the exact input formula. An unchanged plan with
repeating VAT division retains its original quantity.

In this example, the store latte needs **92 units** to retain 370,000; at the
supplied 90 units it is two units short. The delivery latte needs **35 units** to
retain 84,000; its supplied 38 units exceed that threshold. These menu thresholds
precede period-level channel costs and fixed costs. Those costs remain at their
own category or overall level.

`min_units` is `null` when baseline contribution is nonpositive, or proposed unit
contribution is zero or negative. The JSON status distinguishes
`baseline_nonpositive`, `proposed_unit_zero` and `proposed_unit_negative`.
For a positive threshold, `within_input_unit_limit` says whether the quantity
fits the CSV integer limit of `10**25 - 1`; larger mathematical thresholds are
marked as exceeding the input limit. `additional_units_required` compares the
threshold with the proposed quantity already supplied.

The input validation, VAT and fee bases, monetary units and period requirements
match the baseline calculator. All supplied CSV files are protected from every
planned report output, including direct paths, hard links and symbolic links.

## 한국어 사용 안내

현재 메뉴 CSV와 변경안 CSV에 같은 메뉴·채널을 넣고 가격, 단가, 수수료율,
판매 수량을 각각 입력합니다. 보고서는 변경 전후 금액, 차이, 기존 공헌이익을
유지하는 최소 수량을 함께 보여줍니다. 판매 수량은 사용자가 넣은 계획값입니다.
채널비는 각 안에 별도로 넣고, 지정 고정비는 양쪽에 같은 금액을 적용합니다.
