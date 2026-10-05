# Contributing / 기여 안내

Start with [open issues](https://github.com/qorud02/fnb-margin-kit/issues)
and [pull requests](https://github.com/qorud02/fnb-margin-kit/pulls).
For a new feature, discuss the input, expected output, calculation basis,
and scope before coding. A comment coordinates work; it does not reserve
exclusive ownership.

한국어: 열린 이슈와 PR을 먼저 확인하고, 새 기능은 입력·출력·계산 기준과
작업 범위를 공유해 주세요. 첫 작업으로는 [매장·배달 비교 예제](https://github.com/qorud02/fnb-margin-kit/issues/2)가 있습니다.

## Set up / 개발 환경

Use Python 3.10 or newer. Fork on GitHub, replace YOUR_USERNAME below,
and run the commands from your clone.

```sh
git clone https://github.com/YOUR_USERNAME/fnb-margin-kit.git
cd fnb-margin-kit
git switch -c my-change
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e . -r requirements-test.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m fnb_margin_kit.cli examples/menu.csv --output-dir report-contributor-check
```

macOS / Linux:

```sh
.venv/bin/python -m pip install -e . -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m fnb_margin_kit.cli examples/menu.csv --output-dir report-contributor-check
```

Activation is unnecessary. Tests use the pinned renderer in requirements-test.txt
to check actual Markdown table output. The application has no runtime dependencies;
editable installation uses the build requirements in `pyproject.toml`.

한국어: 가상환경을 활성화하지 않아도 위 명령을 실행할 수 있습니다.
저장소 루트에서 설치·테스트·예제 생성을 진행해 주세요.

## Keep examples reproducible / 예제와 검증

Use small synthetic data, clearly labelled. Do not commit real store
records or identifying information. Follow the README's calculation
basis: platform fees use gross selling price; ingredient and packaging
costs exclude VAT. Any supplied fixed cost must cover the same sales
period and monetary unit. This measures contribution, not net profit.

한국어: 실제 매장 자료 대신 합성 데이터를 사용합니다. 고정비는 매출과
같은 기간·금액 단위를 사용해야 하며, 결과를 순이익으로 표현하지 않습니다.

Add focused regression tests for behavior changes and run the existing
unittest suite. For a bug fix, show the relevant failure before the fix
and success afterward. For documentation/examples, check commands,
links, calculations, and regenerated reports. Commit generated reports
only when the issue requests them.

## Submit / 제출

Push your branch to your fork and open a small linked draft PR.
Explain the concrete change, list commands and results actually obtained,
and identify skipped checks or remaining work. Keep unrelated refactoring
separate; update examples when behavior changes.

한국어: 작은 Draft PR에 관련 이슈, 변경 내용, 실제 실행한 검증 명령·결과,
생략한 검증과 남은 작업을 적어 주세요.
