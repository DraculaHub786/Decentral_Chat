"""Guards the converter UI contract against the backend it talks to.

These are static checks, but each one corresponds to a failure that is
invisible until a user tries it: an element id the JS reads but the markup
never defines, a target offered in the dropdown that no engine implements,
or a file cap that disagrees with the server and rejects a valid batch.
"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_PATH = ROOT / "frontend" / "app.js"
HTML_PATH = ROOT / "frontend" / "index.html"
BATCH_PATH = ROOT / "backend" / "app" / "files" / "converters" / "batch.py"

failures = []


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        failures.append(label)


def main():
    js = io.open(JS_PATH, encoding="utf-8").read()
    html = io.open(HTML_PATH, encoding="utf-8").read()

    # 1. The client-side fallback list must not advertise routes the registry
    #    deliberately removed (D-02). Scope to the conversion map: `rar` also
    #    appears in the file-icon table, which is legitimate.
    start = js.index("const LOCAL_CONVERSION_MAP")
    end = js.index("function getFileExtension", start)
    conv_map = js[start:end]

    for dead_target in ("gz:", "'7z':", "rar:"):
        check(f"conversion map offers no {dead_target.rstrip(':')}",
              dead_target not in conv_map)
    check("conversion map: zip -> tar only",
          re.search(r"zip:\s*\['tar'\]", conv_map) is not None)
    check("conversion map: tar -> zip only",
          re.search(r"tar:\s*\['zip'\]", conv_map) is not None)

    # 2. Every element the batch flow touches must exist in the markup.
    for element_id in ("convertAllBtn", "convertAllBtnText",
                       "convertAllBtnSpinner", "convertFileBtn",
                       "targetFormatSelect", "conversionProgress",
                       "progressFill", "progressText", "filePreviewItems"):
        check(f"#{element_id} defined in index.html",
              f'id="{element_id}"' in html)

    # 3. The handler must be defined once and reachable from the button.
    check("convertAllSelectedFiles defined exactly once",
          len(re.findall(r"function\s+convertAllSelectedFiles\s*\(", js)) == 1)
    check("convertAllSelectedFiles wired to the button",
          'onclick="convertAllSelectedFiles()"' in html)

    # 4. Endpoints must match the routes the server registers.
    check("batch create endpoint used", "/files/batch" in js)
    check("batch status endpoint polled", "/files/batch/${batchId}" in js)
    check("batch result endpoint used",
          "/result?token=${encodeURIComponent(batch.result_token)}" in js)

    # 5. The ZIP must stay a normal File, or it bypasses E2EE on send (D-07).
    check("batch result wrapped in a File",
          re.search(r"new File\(\[zipBlob\]", js) is not None)

    # 6. The client cap must agree with the server's, or a valid batch is
    #    rejected before it is ever sent.
    if BATCH_PATH.exists():
        backend = io.open(BATCH_PATH, encoding="utf-8").read()
        server_cap = re.search(r"MAX_BATCH_FILES\s*=\s*(\d+)", backend)
        client_cap = re.search(r"BATCH_MAX_FILES\s*=\s*(\d+)", js)
        if server_cap and client_cap:
            check(f"batch cap matches server ({client_cap.group(1)})",
                  server_cap.group(1) == client_cap.group(1))
        else:
            check("batch cap constant found in both files", False)
    else:
        print("SKIP  batch.py not present")

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED")
        return 1
    print("FRONTEND BATCH UI CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
