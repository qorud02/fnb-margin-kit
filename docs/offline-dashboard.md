# Offline contribution dashboard

Add `--html` to create a dashboard beside the JSON and Markdown reports:

```console
fnb-margin examples/store-versus-delivery.csv --channel-costs examples/channel-costs.csv --fixed-cost 300000 --html --output-dir report-dashboard
```

Open `report-dashboard/report.html` in a browser. It contains its own styles,
script and report data; an internet connection or web server is unnecessary.
The supplied CSVs cover one sales period and monetary unit, as described in the
[channel-cost example](channel-costs.md). That example uses synthetic data.

The Korean-default screen includes English field labels, whole-report summary
cards, category contribution comparison and the complete menu table. Search by
menu or category, filter by category or unit-margin sign, and sort by total
contribution, unit contribution, units or names. Menu ranks retain the original
whole-report ranks. Search and filters affect the menu table; the summary cards
and category comparison continue to show the complete input.

The summary distinguishes contribution before additional channel and fixed
costs, after additional channel costs, and after a supplied fixed cost. Category
totals are before fixed cost allocation. Menu unit margins and rankings are
before the additional category costs, which are deducted once per category.
The dashboard uses the calculation's values and the input monetary unit.

Displayed amounts initially round to two decimal places. **정밀한 계산값 보기 /
Exact decimals** switches cards and tables to the original Decimal strings on
desktop and mobile. The JSON also retains calculation precision. Numeric sort
keys are generated with Python Decimal comparisons; the browser sorts bounded
ranks rather than converting financial amounts to floating-point numbers.

Use **인쇄 / Print** for a landscape print layout. Printing uses the currently
filtered menu table and the whole-report summary and category comparison. The
complete static tables remain readable when JavaScript is disabled; interactive
search, filters, sorting and precision switching require JavaScript.

The HTML file contains menu names and financial inputs from the report. Share it
with the people who may access those records. All CSV text is escaped in the
document and embedded JSON, and filtering inserts text with DOM textContent.
The document has no external fonts, scripts, network requests or dependencies.

Without `--html`, the original report files and behavior are unchanged. With
the option, `report.html` is also protected from overwriting either input CSV,
including existing hard links and symbolic links.
