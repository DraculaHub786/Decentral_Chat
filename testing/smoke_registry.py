"""Smoke test for the converter v2 registry, routes and engine wiring."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.files.converters import routes_table, verify, workspace, fidelity

HERE = Path(__file__).resolve().parent

caps = routes_table.capabilities()
print("total routes:", len(caps["routes"]))
print("engine availability:")
for name, info in caps["engines"].items():
    print(f"  {name:12s} available={info['available']}")

print("\ndocx->pdf     :", routes_table.lookup("docx", "pdf"))
print("png->webp     :", routes_table.lookup("png", "webp"))
print("mp3->flac     :", routes_table.lookup("mp3", "flac"))
print("pdf->docx     :", routes_table.lookup("pdf", "docx"))
print("zip->tar      :", routes_table.lookup("zip", "tar"), "(must be None)")

print("\ntargets from docx:", routes_table.supported_targets("docx"))
print("targets from mp4 :", routes_table.supported_targets("mp4"))

route = routes_table.lookup("pdf", "docx")
if route:
    print("\npdf->docx tier:", route.tier, "chain:", route.engines)
    print("capability limits:", route.as_capability()["limits"])

# Warning generation must flag the reconstructive tier.
report = fidelity.build_warnings("pdf", "docx", "C")
print("\npdf->docx warnings:", report.warnings)

# Workspace lifecycle.
ws = workspace.create("smoke-job")
(ws.input_dir / "a.txt").write_text("hello")
print("\nworkspace outputs before conversion:", [p.name for p in ws.list_outputs()])
ws.cleanup()
print("workspace cleaned:", not ws.root.exists())

# The verifier must reject a non-PDF. Written beside this file so the test does
# not depend on the working directory it is launched from.
bogus = HERE / "_bogus.pdf"
bogus.write_bytes(b"not a pdf at all, just text pretending to be one")
try:
    verify.verify_output(bogus, "pdf")
    raise SystemExit("FAIL: verifier accepted a bogus PDF")
except verify.VerifyError as err:
    print("\nverifier rejected bogus pdf:", str(err)[:60])
finally:
    bogus.unlink(missing_ok=True)

# A truncated file with a valid magic header must also be rejected.
truncated = HERE / "_truncated.docx"
truncated.write_bytes(b"PK\x03\x04" + b"\x00" * 40)
try:
    verify.verify_output(truncated, "docx")
    raise SystemExit("FAIL: verifier accepted a truncated DOCX")
except verify.VerifyError as err:
    print("verifier rejected truncated docx:", str(err)[:60])
finally:
    truncated.unlink(missing_ok=True)

print("\nSMOKE OK")
