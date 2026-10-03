# Store-versus-delivery example / 매장·배달 비교

This synthetic fixture compares 카페라테 in two supplied categories: 매장 and 배달. Amounts use KRW for one sales period. The category labels come from the CSV; each row supplies its own price, packaging cost, fee rate, and sold units.

아래 예제는 카페라테의 매장·배달 판매를 비교하는 예시 숫자입니다. 금액은 원 단위이며 판매 수량은 같은 기간으로 설정했습니다. 매장과 배달은 CSV의 `category`에 작성한 분류명입니다.

## Run / 실행

From the repository root:

```sh
python -m pip install .
fnb-margin examples/store-versus-delivery.csv --output-dir report-store-versus-delivery
fnb-margin examples/store-versus-delivery.csv --output-dir report-store-versus-delivery-fixed-cost --fixed-cost 300000
```

Each command creates `report.json` and `report.md` in its separate output directory. Compare them with the included [JSON](../examples/store-versus-delivery/report.json) and [Markdown](../examples/store-versus-delivery/report.md) reports, or the [fixed-cost JSON](../examples/store-versus-delivery-fixed-cost/report.json) and [fixed-cost Markdown](../examples/store-versus-delivery-fixed-cost/report.md).

저장소 루트에서 위 명령을 실행합니다. 기본 비교와 고정비 차감 결과를 서로 다른 폴더에 저장하므로 기존 예제 보고서를 덮어쓰지 않습니다.

## Inputs / 입력값

The [two-row CSV](../examples/store-versus-delivery.csv) uses the existing eight columns. Ingredient and packaging costs are VAT-exclusive per-unit amounts; selling prices include VAT. Rates are fractions.

| Input / 입력 | 매장 | 배달 |
| --- | ---: | ---: |
| `price_gross` | 5,500 | 5,500 |
| `vat_rate` | 0.10 | 0.10 |
| `ingredient_cost` | 1,200 | 1,200 |
| `packaging_cost` | 100 | 300 |
| `platform_fee_rate` | 0 | 0.15 |
| `units` | 100 | 40 |

같은 메뉴명을 서로 다른 분류에 넣을 수 있습니다. 재료비·포장비는 부가세를 제외한 단가, 판매가는 부가세를 포함한 금액입니다. `0.10`은 10%, `0.15`는 15%입니다.

## Calculation / 계산

Both rows have a VAT-exclusive unit selling price of `5500 / 1.10 = 5000`. The CLI charges platform fees on the gross price: the delivery row uses `5500 × 0.15 = 825` per unit.

| Calculation / 계산 | 매장 | 배달 |
| --- | ---: | ---: |
| Net selling price/unit / 부가세 제외 판매가 | 5,000 | 5,000 |
| Platform fee/unit / 플랫폼 수수료 | 0 | 825 |
| Contribution/unit / 개당 공헌이익 | 3,700 | 2,675 |
| Total contribution / 총공헌이익 | 370,000 | 107,000 |

Store contribution is `(5000 - 1200 - 100) × 100 = 370000`. Delivery contribution is `(5000 - 1200 - 300 - 825) × 40 = 107000`. Its extra packaging cost of 200 and fee of 825 reduce unit contribution by 1,025 with these inputs.

두 분류 모두 부가세 제외 판매가는 `5500 / 1.10 = 5000`입니다. 매장은 `(5000 - 1200 - 100) × 100 = 370000`, 배달은 `(5000 - 1200 - 300 - 825) × 40 = 107000`으로 계산합니다. 배달 행은 포장비 200과 수수료 825가 추가되어 개당 공헌이익이 1,025 낮습니다.

Combined, the fixture gives 140 units, gross sales of 770,000, VAT-exclusive sales of 700,000, platform fees of 33,000, and contribution of 477,000. The optional same-period fixed cost of 300,000 leaves contribution of 177,000 after that specified cost. Keep other costs in your separate profit-and-loss statement.

합계는 140개, 부가세 포함 매출 770,000원, 부가세 제외 매출 700,000원, 플랫폼 수수료 33,000원, 공헌이익 477,000원입니다. 같은 기간의 고정비 300,000원을 지정하면 그 금액을 차감한 공헌이익 177,000원을 보여줍니다. 전체 손익을 계산하려면 다른 비용도 별도로 반영해야 합니다.

## Fee basis and zero sales / 수수료 기준과 판매 수량 0

This example follows the CLI's gross-price fee basis. For an agreement that charges fees on a different amount, adapt the calculation explicitly before using it for that agreement. Enter the applicable VAT and fee rates yourself. The [calculation basis](../README.md#calculation-basis) describes the inputs and exclusions.

이 예제의 수수료는 부가세를 포함한 판매가를 기준으로 계산합니다. 계약이 다른 금액을 기준으로 수수료를 정한다면 해당 기준에 맞게 계산을 조정해야 합니다. 적용할 부가세율과 수수료율은 직접 입력합니다.

With zero sold units, total contribution is zero while `margin_flag` still describes the unit contribution. A row can therefore have a negative flag and zero total contribution. The existing [`test_zero_and_negative_margins_with_zero_units`](../tests/test_analysis.py) covers this case.

판매 수량이 0이면 총공헌이익은 0입니다. `margin_flag`는 개당 공헌이익을 기준으로 하므로 총공헌이익이 0이어도 `negative`로 표시될 수 있습니다.
