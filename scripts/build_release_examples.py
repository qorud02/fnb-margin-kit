"""Package synthetic inputs and generated reports from the installed release."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)
NAMES = ("ingredients.csv", "recipes.csv", "plan.csv", "stock.csv")
GUIDE = """발주 보고서 사용 안내

이 파일은 가상 판매 계획과 재고를 사용한 실행 예제입니다.
reports/procurement.html을 브라우저에서 열어 보고 인쇄할 수 있습니다.
외부 사이트로 입력 자료를 보내지 않습니다.

직접 계산하려면 Python 3.10 이상에서 같은 릴리스의 wheel을 설치하세요.
python -m pip install --no-index --no-deps fnb_margin_kit-0.7.0-py3-none-any.whl
fnb-procure inputs/ingredients.csv inputs/recipes.csv inputs/plan.csv --stock inputs/stock.csv --html --output-dir my-report

예제 결과: 판매 계획 78개, 구매 17포장, 구매비 94,000 (부가세 제외).
금액 단위는 입력 파일 기준입니다. 실제 사업 자료로 교체해 실행하세요.
손질 전 재고를 넣고, 구매 포장 규격과 수율을 확인하세요.
정확한 수량의 분자·분모는 JSON과 CSV에서 확인할 수 있습니다.
"""
with tempfile.TemporaryDirectory(prefix="fnb-release-example-") as directory:
    work = Path(directory)
    output = work / "reports"
    inputs = ROOT / "examples" / "procurement"
    subprocess.run([sys.executable, "-m", "fnb_margin_kit.procurement_cli",
                    str(inputs / NAMES[0]), str(inputs / NAMES[1]),
                    str(inputs / NAMES[2]), "--stock", str(inputs / NAMES[3]),
                    "--html", "--output-dir", str(output)], check=True)
    expected = {"procurement.html", "procurement.json", "procurement.md", "ingredient-procurement.csv"}
    if {path.name for path in output.iterdir()} != expected:
        raise SystemExit("Generated example report set differs")
    archive = DIST / "procurement-example.zip"
    files = {"inputs/" + name: (inputs / name).read_bytes() for name in NAMES}
    files.update({"reports/" + name: (output / name).read_bytes() for name in sorted(expected)})
    files["사용안내.txt"] = GUIDE.encode("utf-8-sig")
    with ZipFile(archive, "w") as bundle:
        for name, content in sorted(files.items()):
            info = ZipInfo(name, date_time=(2026, 10, 30, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, content)
    with ZipFile(archive) as bundle:
        if set(bundle.namelist()) != set(files) or any(bundle.read(name) != data for name, data in files.items()):
            raise SystemExit("Example ZIP differs from generated source files")
    checksum = DIST / "SHA256SUMS"
    entries = checksum.read_text(encoding="utf-8") if checksum.exists() else ""
    checksum.write_text(entries + hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n", encoding="utf-8", newline="\n")
    print("Verified synthetic example ZIP with " + str(len(files)) + " files")
