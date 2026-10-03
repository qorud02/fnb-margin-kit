# F&B Menu Margin Kit

Turn an F&B menu and sales mix into a ranked contribution report. This small,
dependency-free Python tool is for F&B operators, including cafes and quick-service businesses, who want to see which products
contribute most after ingredients, packaging, and platform fees.

It produces a readable Markdown table and a JSON report with decimal strings.
Korean menu names and UTF-8 CSV exports with a BOM are supported.

## Install and run

Python 3.10 or later is required.

```console
git clone https://github.com/qorud02/fnb-margin-kit.git
cd fnb-margin-kit
python -m pip install .
fnb-margin examples/menu.csv --output-dir report
fnb-margin examples/menu.csv --output-dir report-with-cost --fixed-cost 300000
```

The command writes `report.md` and `report.json`. Output paths must not alias the input CSV, including existing hard links. The supplied fixed cost must
cover the same period as the CSV sales and use the same monetary unit.

Run the [매장·배달 비교 / store-versus-delivery example](docs/store-versus-delivery.md) to compare the same menu with different packaging and platform fees.

## Input

```csv
menu,category,price_gross,vat_rate,ingredient_cost,packaging_cost,platform_fee_rate,units
아메리카노,커피,4400,0.10,700,100,0.03,100
카페라테,커피,5500,0.10,1200,150,0.03,60
배달 디저트,디저트,3300,0.10,2200,500,0.15,20
행사 음료,프로모션,1100,0.10,900,100,0,10
```

Use one currency or monetary unit throughout. Enter ingredient and packaging
costs **per unit, excluding VAT**. `price_gross` includes VAT. Rates are fractions:
`0.10` means 10%. VAT and platform fee rates must be between 0 and 1. `units` is a
nonnegative integer. Blank values, negative values, NaN, infinity, duplicate
menu/category rows, and malformed columns are rejected.

Numbers may contain at most 28 significant digits and 12 decimal places, with
magnitude below `1e25`. These bounds protect calculation precision and prevent
unreasonable exponents. The eight columns may appear in any order.

## Calculation basis

```text
net selling price = price_gross / (1 + vat_rate)
platform fee = price_gross * platform_fee_rate
unit contribution = net selling price - ingredient_cost - packaging_cost - platform fee
total contribution = unit contribution * units
```

Platform fees explicitly use **gross selling price**, including VAT. If a
contract charges fees on another basis, convert those costs before using the
tool or adapt the calculation. The tool does not infer your contract or tax
treatment.

The sample above gives 190 units, 770,000.00 in VAT-exclusive sales, and
512,000.00 in contribution before fixed costs:

| Rank | Menu | Contribution/unit | Total contribution | Margin |
| ---: | --- | ---: | ---: | --- |
| 1 | 아메리카노 | 3,068.00 | 306,800.00 | positive |
| 2 | 카페라테 | 3,485.00 | 209,100.00 | positive |
| 3 | 행사 음료 | 0.00 | 0.00 | zero |
| 4 | 배달 디저트 | -195.00 | -3,900.00 | negative |

The values are illustrative inputs, not measured operating results. Rankings use
total contribution, while the margin flag describes contribution **per unit**.
An item with zero sales can still have a negative unit margin.

## Limits

This is contribution analysis, not net profit. Labor, rent, other fixed costs,
and income tax are excluded. `--fixed-cost` subtracts only the amount you supply;
it does not turn the report into a full profit-and-loss statement.

Calculation uses a 50-digit Decimal context. Markdown amounts round to two
decimal places with half-up rounding; JSON amounts retain calculation precision
as strings. Repeating divisions remain decimal approximations. The tool does
not forecast demand or validate your ingredient cost records.

## Test

```console
python -m unittest discover -s tests -v
```

Run tests after installing the package, or set `PYTHONPATH=src` during local
development. The suite covers decimal arithmetic, VAT and fee bases, invalid
inputs, UTF-8 BOM, Korean names, rank ties, zero sales, negative margins,
fixed-cost scenarios, and CLI reports.

GitHub Actions runs package tests and the example workflow on Linux with
Python 3.10, 3.12, and 3.14. See the [workflow](.github/workflows/ci.yml).

## 한국어 안내

F&B 메뉴별 판매 수량과 원가를 CSV로 넣으면 고정비 차감 전 공헌이익을
계산하고 순위를 보여줍니다. 재료비와 포장비는 부가세를 제외한 단가,
판매가는 부가세를 포함한 금액으로 입력합니다. 플랫폼 수수료는 판매가
전체를 기준으로 계산합니다. 인건비·임대료·소득세를 포함한 순이익 계산은
아닙니다. 샘플 CSV를 실제 메뉴 값으로 바꿔 사용하세요.

## Development

Calculation rules and validation behavior are
documented and checked with executable tests. Contributions that improve real
operator workflows are welcome; include the calculation basis and regression
tests with changes.

For setup and review guidance, see [기여 안내 / contributor guide](CONTRIBUTING.md).

Licensed under MIT.

## Container and wheel

Run the example commands below from the cloned `fnb-margin-kit` directory. The [installation steps](#install-and-run) fetch the CSV examples.

The Linux amd64 image runs the same CSV calculator and writes `report.json` and `report.md`. Keep the input mount read-only and give the selected output directory write access.

On Linux, run as your host user so the reports keep your file ownership:

```sh
mkdir -p report-container
docker run --rm --platform linux/amd64 --network none --read-only --user "$(id -u):$(id -g)" --mount "type=bind,source=${PWD},target=/work,readonly" --mount "type=bind,source=${PWD}/report-container,target=/output" ghcr.io/qorud02/fnb-margin-kit:0.1.0 /work/examples/store-versus-delivery.csv --output-dir /output --fixed-cost 300000
```

With Docker Desktop configured for Linux containers, PowerShell uses:

```powershell
New-Item -ItemType Directory -Force report-container | Out-Null
docker run --rm --platform linux/amd64 --network none --read-only --mount "type=bind,source=${PWD},target=/work,readonly" --mount "type=bind,source=${PWD}/report-container,target=/output" ghcr.io/qorud02/fnb-margin-kit:0.1.0 /work/examples/store-versus-delivery.csv --output-dir /output --fixed-cost 300000
```

The image defaults to UID 10001. Mounted inputs must be readable and the output directory writable by the user running the container. For this fixture, `report-container/report.json` contains contribution of 477,000 and contribution of 177,000 after the supplied fixed cost. Replace the CSV path and fixed cost with your own inputs for the same period and monetary unit.

Download `fnb_margin_kit-0.1.0-py3-none-any.whl` and `SHA256SUMS` from the [release](https://github.com/qorud02/fnb-margin-kit/releases/tag/v0.1.0), then install the wheel offline:

```sh
python -m pip install --no-index --no-deps ./fnb_margin_kit-0.1.0-py3-none-any.whl
fnb-margin --help
fnb-margin examples/store-versus-delivery.csv --output-dir report-wheel
```

The wheel supports Python 3.10 or newer and has no runtime dependencies. The [package workflow](.github/workflows/package.yml) checks source bytes, license metadata, report calculations, protected inputs, a fresh wheel installation, and the non-root container before publishing its versioned image.
