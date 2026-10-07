# Recipe ingredient costing / 레시피 재료 원가

`fnb-recipe` calculates the ingredient cost of one sold menu unit from purchase
prices, pack quantities, edible yields and recipe quantities. Its exported menu
CSV can be used directly by `fnb-margin`.

The [example inputs](../examples/recipe-costing) describe a synthetic cafe menu:
five ingredients, nine recipe lines and four menu/category combinations.

## Run

Install the package from the repository or versioned wheel, then run:

```console
fnb-recipe examples/recipe-costing/ingredients.csv examples/recipe-costing/recipes.csv --output-dir recipe-report --menu examples/recipe-costing/menu.csv
fnb-margin recipe-report/costed-menu.csv --output-dir recipe-margin-report --html
```

The recipe command writes three files:

- `recipe-costs.json`: purchase quantities, yields, required purchase quantities,
  exact line/menu fractions, decimal displays and export values.
- `recipe-costs.md`: readable menu costs and ingredient quantities.
- `menu-ingredient-costs.csv`: `menu,category,ingredient_cost`, ready for updating
  a menu cost table.

With `--menu`, it also writes `costed-menu.csv` with the existing eight-column
menu schema. Menu row order, selling price, VAT rate, packaging cost, platform
fee rate and sold units are preserved after ordinary input normalization. Only
`ingredient_cost` is replaced. The original menu and recipe files remain intact.
The menu/category identities in both tables must match exactly.

## Ingredient purchases

```csv
ingredient,purchase_quantity,purchase_unit,purchase_price,yield_rate
가상 원두,1,kg,24000,1
가상 우유,1,l,3000,0.95
가상 바나나,1,kg,5000,0.8
가상 시럽,750,ml,6000,1
가상 디저트 반제품,12,each,18000,1
```

`purchase_price` is the total price of the stated purchased quantity. `yield_rate`
is the edible share of that quantity: `0.8` means 80%. The price is applied to
the purchased amount, including the part discarded during preparation.

Use one monetary and tax basis for all purchase prices. To pass the exported
costs into the existing contribution calculator, supply VAT-exclusive ingredient
purchase prices. Recipe costing itself performs no VAT conversion.

## Recipe quantities

```csv
menu,category,ingredient,quantity,unit
가상 라테,매장,가상 원두,18,g
가상 라테,매장,가상 우유,180,ml
가상 바나나 음료,매장,가상 바나나,120,g
가상 바나나 음료,매장,가상 우유,150,ml
가상 바나나 음료,매장,가상 시럽,20,ml
```

`quantity` is the final edible ingredient amount used by one sold menu unit.
For example, 120 g of edible banana at an 80% yield requires purchasing 150 g.
Use the category to distinguish the same menu across store and delivery channels.

Units ignore case and surrounding spaces. Supported conversions are `kg` ↔ `g`
and `l` ↔ `ml`; `each` is a count. Mass, volume and count cannot be converted into
one another. For example, a purchase recorded in kilograms needs a recipe recorded
in grams or kilograms, rather than millilitres.

Both CSVs support UTF-8 BOMs, Korean names, quoted names and reordered columns.
Names are trimmed and matched case-sensitively. Duplicate ingredient names,
duplicate menu/category/ingredient lines, missing ingredients and incompatible
units are rejected. Unused catalog ingredients are permitted. Quantities must
be positive, prices nonnegative and yields greater than zero and at most one.
Numeric inputs use the existing 28-digit, 12-decimal-place and below-`1e25` bounds.

## Calculation and export precision

```text
line cost = purchase price × recipe quantity in base units
            ÷ (purchase quantity in base units × yield rate)
menu ingredient cost = exact sum of its ingredient line costs
```

The example latte uses 18 g of coffee at 24,000 per kg, giving 432. Its 180 ml
of milk at 3,000 per litre and a 95% yield costs `10800/19`. The exact menu cost
is therefore `19008/19`, displayed as approximately 1,000.421052631579.
The banana drink costs `26290/19`; the dessert costs exactly 1,540.

JSON keeps each exact amount as decimal-string `numerator` and `denominator`,
beside a 50-significant-digit `decimal` display. Sums are performed as fractions,
without rounding individual ingredients. The report also retains the input
units, yields and required purchase quantities for checking the calculation.

CSV costs are rounded once from the raw fraction with half-up rounding. The
number of decimal places is `min(12, 28 − integer_digits)`, so the export fits
the existing menu input limits. Trailing decimal zeroes are removed.
A positive cost smaller than the export precision can round to zero; its exact
fraction and decimal display remain in JSON and Markdown. Computed menu costs
at or above `1e25`, or a rounded value beyond the existing numeric bounds, are
rejected before any output is written.

| Menu | Category | Exact ingredient cost | CSV ingredient cost |
| --- | --- | ---: | ---: |
| 가상 라테 | 매장 | 19008/19 | 1000.421052631579 |
| 가상 라테 | 배달 | 19008/19 | 1000.421052631579 |
| 가상 바나나 음료 | 매장 | 26290/19 | 1383.684210526316 |
| 가상 디저트 | 디저트 | 1540/1 | 1540 |

Before writing, the command checks every supplied input against every planned
output path, including existing hard links and symbolic links. Invalid inputs,
identity mismatches and unexportable costs produce no partial report.

## Container

The image retains the existing `fnb-margin` default. Select the recipe command
explicitly and mount the source and output directory as in the main README:

```sh
mkdir -p recipe-container
docker run --rm --platform linux/amd64 --network none --read-only --user "$(id -u):$(id -g)" --entrypoint fnb-recipe --mount "type=bind,source=${PWD},target=/work,readonly" --mount "type=bind,source=${PWD}/recipe-container,target=/output" ghcr.io/qorud02/fnb-margin-kit:0.5.0 /work/examples/recipe-costing/ingredients.csv /work/examples/recipe-costing/recipes.csv --menu /work/examples/recipe-costing/menu.csv --output-dir /output
```

## 한국어 안내

납품가와 포장 단위, 손질 후 수율, 한 메뉴에 들어가는 가식부 사용량을
입력하면 메뉴별 재료 원가를 계산합니다. kg와 g, l와 ml는 자동 환산하고,
개수는 `each`로 입력합니다. 사용량이 가식부 기준이므로 수율을 적용한
구매필요량도 함께 확인할 수 있습니다.

예제 라테의 원두 원가는 432, 우유 원가는 `10800/19`이며 합계는
`19008/19`입니다. 부가세를 제외한 납품가를 입력하면 내보낸 메뉴 CSV를
기존 공헌이익 계산에 바로 사용할 수 있습니다. JSON에는 정확한 분수,
CSV에는 기존 입력 제한에 맞춘 원가가 기록됩니다.
