# Stock-aware ingredient purchasing / 재고를 반영한 재료 구매

`fnb-procure` calculates the complete ingredient packs needed for a supplied
menu sales plan. Shared ingredients are combined across menu/category rows
before opening stock is subtracted. Preparation yields determine raw ingredient
demand; whole-pack purchasing determines the spend and remaining stock.

## Run

Install the package from the repository or the versioned wheel, then run:

```console
fnb-procure examples/procurement/ingredients.csv examples/procurement/recipes.csv examples/procurement/plan.csv --stock examples/procurement/stock.csv --output-dir procurement-report
```

The command writes three files:

- `procurement.json`: the sales plan, supplied raw stock, recipe requirements,
  per-ingredient quantities, whole-pack counts and purchase-spend totals.
- `procurement.md`: a readable purchase list with demand, stock, shortages,
  complete packs, remaining raw stock and spend.
- `ingredient-procurement.csv`: one row per catalog ingredient, with decimal
  quantities and exact numerator/denominator audit columns.

Omit `--stock` to plan from zero opening stock. A missing ingredient in the
stock table also means zero opening stock. Catalog ingredients unused by the
plan remain in the report with zero demand and their supplied stock.

## Input tables

The ingredient and recipe tables use the same schemas as
[`fnb-recipe`](recipe-costing.md):

```csv
ingredient,purchase_quantity,purchase_unit,purchase_price,yield_rate
가상 우유,1,l,3000,0.95
```

```csv
menu,category,ingredient,quantity,unit
가상 라테,매장,가상 우유,180,ml
가상 라테,배달,가상 우유,180,ml
```

`purchase_quantity` and `purchase_unit` describe **one complete pack**.
`purchase_price` is that pack's total price, excluding VAT. Use one currency or
monetary unit throughout. `quantity` in the recipe is the edible amount in one
sold menu unit; `yield_rate` is the edible share of the raw purchased ingredient.

The plan has exactly three columns:

```csv
menu,category,units
가상 라테,매장,40
가상 라테,배달,20
```

`units` is a nonnegative integer, including zero. Menu and category together
select the recipe. The same menu can appear in different categories, but a
menu/category pair can appear only once in the plan. Every plan pair must have
a recipe, including a pair with zero planned units. Recipes outside the plan
are permitted and validated.

The optional stock table also has exactly three columns:

```csv
ingredient,quantity,unit
가상 우유,1.5,l
```

Enter **raw purchased stock before preparation loss**. A 1 kg purchase at an
80% edible yield is 1 kg of raw stock, not 800 g. For prepared edible stock,
convert it to the equivalent raw quantity using the same yield before entering
it. Use stock available for this plan after reservations have been deducted.
Each ingredient may appear only once in the stock table; unknown ingredients
are rejected, including unused stock rows. Stock quantities may be zero.

Supported units are `g`, `kg`, `ml`, `l` and `each`, ignoring unit case. Mass,
volume and count remain separate dimensions. Purchase, recipe and stock units
for an ingredient must belong to the same dimension. All tables accept UTF-8
BOMs, reordered columns and quoted Korean names. Names are trimmed and matched
case-sensitively. Numeric input limits are 28 significant digits, at most 12
decimal places and magnitude below `1e25`, matching the recipe inputs.

## Calculation

```text
edible demand = sum(recipe edible quantity × planned menu units)
gross raw demand = sum(recipe edible quantity × planned menu units ÷ yield)
shortage = max(0, gross raw demand − opening raw stock)
packs to buy = ceiling(shortage ÷ complete purchase pack quantity)
purchase spend = packs to buy × one pack price
remaining raw stock = opening raw stock + packs bought × pack quantity − gross raw demand
```

All quantities are first converted to `g`, `ml` or `each`. Opening stock is
subtracted once per ingredient after demand is combined across menus and
categories. Pack ceilings use exact fractions, so a shortage just above a pack
boundary still purchases the additional pack. JSON and CSV retain exact
`numerator`/`denominator` values alongside 50-significant-digit decimal displays.
Totals sum exact amounts; no VAT conversion or monetary rounding is applied.

## Worked cafe plan

The [example inputs](../examples/procurement) are a synthetic plan for 40 store
lattes, 20 delivery lattes, 10 banana drinks and 8 desserts: 78 menu units.
They include raw opening stock and an unused ginger ingredient.

| Ingredient | Gross raw demand | Opening raw stock | Complete packs to buy | Purchase spend | Remaining raw stock |
| --- | ---: | ---: | ---: | ---: | ---: |
| Coffee | 1,080 g | 500 g | 1 × 1 kg | 24,000 | 420 g |
| Milk | 246000/19 ml | 1,500 ml | 12 × 1 l | 36,000 | 10500/19 ml |
| Banana | 1,500 g | 200 g | 2 × 1 kg | 10,000 | 700 g |
| Syrup | 240 ml | 100 ml | 1 × 750 ml | 6,000 | 610 ml |
| Dessert pieces | 8 each | 5 each | 1 × 12 each | 18,000 | 9 each |
| Ginger | 0 g | 100 g | 0 | 0 | 100 g |

The plan buys **17 packs for 94,000 excluding VAT**. Milk demand is
`(60 × 180 + 10 × 150) / 0.95 = 246000/19` ml. After subtracting 1,500 ml of raw
stock, the shortage is `217500/19` ml. Twelve 1 l packs cover it and leave
`10500/19` ml of raw milk. With no opening stock, the same plan buys 19 packs
for 121,000.

The plan uses the quantities supplied for one planning period. Expiry dates,
supplier lead times, delivery fees, minimum order sizes and safety stock are
outside these input tables; adjust the plan or available stock before running.

## File protection

All input and calculation validation finishes before output files are written.
Every output is checked against every input, including hard links and symbolic
links. Existing output files that alias one another are also rejected. Invalid
inputs leave an existing report directory unchanged. A successful run replaces
the three named reports and preserves other files in that directory.

## Container

Use the main README's input/output mount permissions and select the purchase
console explicitly:

```sh
mkdir -p procurement-container
docker run --rm --platform linux/amd64 --network none --read-only --user "$(id -u):$(id -g)" --entrypoint fnb-procure --mount "type=bind,source=${PWD},target=/work,readonly" --mount "type=bind,source=${PWD}/procurement-container,target=/output" ghcr.io/qorud02/fnb-margin-kit:0.6.0 /work/examples/procurement/ingredients.csv /work/examples/procurement/recipes.csv /work/examples/procurement/plan.csv --stock /work/examples/procurement/stock.csv --output-dir /output
```

## 한국어 안내

메뉴별 판매 계획과 레시피, 손질 전 재고를 넣으면 재료별 구매 수량을
계산합니다. 매장과 배달에서 함께 쓰는 재료를 먼저 합산하고 재고를 한 번
차감합니다. 부족량은 납품 포장 단위로 올림해 구매비와 남는 재고를 보여줍니다.

재고는 손질 전 수량, 레시피는 손질 후 먹을 수 있는 사용량으로 입력합니다.
손질 후 재고를 보유한 경우 같은 수율로 손질 전 환산량을 계산해 넣으세요.
예제는 가정한 판매·재고 수치이며, 78개 메뉴 판매를 위해 17포장과 부가세
제외 구매비 94,000이 필요합니다. JSON과 CSV에서 정확한 분수도 확인할 수
있습니다.
