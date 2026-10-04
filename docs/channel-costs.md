# Channel costs for a sales period

Delivery subsidies, merchant-funded promotions, or other variable charges may
be recorded as a channel total rather than a cost per menu unit. Supply those
amounts in a separate CSV when they are absent from the menu's ingredient,
packaging, and platform-fee costs.

Run this synthetic example from the repository root after installing the package:

```console
fnb-margin examples/store-versus-delivery.csv --channel-costs examples/channel-costs.csv --fixed-cost 300000 --output-dir report-channel-costs
```

The additional-cost file contains:

```csv
category,additional_variable_cost
배달,60000
```

`category` matches the menu CSV after surrounding whitespace is removed. Matching
is case-sensitive. Use one row per category; duplicate and unmatched categories
are errors. Categories omitted from this file receive zero additional cost.
Both columns are required, in either order. UTF-8 with a BOM is supported.
Blank categories or amounts, negative amounts, NaN, infinity, malformed rows,
and an empty file are rejected. Amounts use the same numeric bounds as menu costs.

Use the **same sales period and currency** for both files and the specified fixed
cost. Enter additional costs **excluding VAT**. The tool has no period, currency,
or tax conversion fields, so align these inputs before running it. Enter each
cost once: a charge already included in the menu costs must not be repeated here.

In the example, the VAT-inclusive selling price is 5,500 and the VAT-exclusive
price is `5,500 / 1.10 = 5,000`. Store contribution is
`(5,000 - 1,200 - 100) × 100 = 370,000`. Delivery platform fees use the gross
price: `5,500 × 0.15 = 825` per unit. Delivery contribution before the additional
cost is `(5,000 - 1,200 - 300 - 825) × 40 = 107,000`.

| Category | Contribution before additional cost | Additional variable cost | Contribution after additional cost |
| --- | ---: | ---: | ---: |
| 매장 | 370,000 | 0 | 370,000 |
| 배달 | 107,000 | 60,000 | 47,000 |
| Total | 477,000 | 60,000 | 417,000 |

Deducting the specified 300,000 fixed cost then leaves contribution of 117,000.
These numbers come from the included synthetic inputs.

The JSON `totals` and `menus` retain contributions before the additional costs.
`channel_cost_scenario` contains category totals and the adjusted overall
contribution. With both options supplied, `fixed_cost_scenario` deducts the fixed
cost from that adjusted contribution. Menu unit margins and ranks remain based
on the original per-unit costs; the period-level charge is not allocated to menus.
A zero-sales category can still carry an additional cost and have negative
adjusted contribution. Splitting sales across menus in the same category does
not duplicate the charge.

Without `--channel-costs`, the calculation and report formats are unchanged.
Neither input file may alias `report.json` or `report.md`, including existing
hard links and symbolic links.
