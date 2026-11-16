"""Confirm the full server module imports and registers the v2 routes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.server import DecentralChatServer
from app.files.converters import routes_table, service

server = DecentralChatServer()
server.setup_routes()

wanted = {
    "/api/files/capabilities",
    "/api/files/formats",
    "/api/files/jobs",
    "/api/files/jobs/{job_id}",
    "/api/files/jobs/{job_id}/result",
    "/api/files/conversion-formats",
    "/api/files/batch",
    "/api/files/batch/{batch_id}",
    "/api/files/batch/{batch_id}/result",
}

seen = set()
for route in server.app.router.routes():
    seen.add(route.resource.canonical)

missing = wanted - seen
print("registered v2 routes:", sorted(wanted & seen))
if missing:
    print("MISSING:", sorted(missing))
    sys.exit(1)

# D-01: the legacy shim must follow the registry, not its old hand-written map.
docx_targets = service.get_supported_conversions("docx")
zip_targets = service.get_supported_conversions("zip")
print("legacy docx targets:", docx_targets)
print("legacy zip targets :", zip_targets)

# D-02 said archives were advertised without an implementation. They are back
# (Phase 6), so the guard changes shape rather than disappearing: every
# advertised target must be backed by a route whose engine is really installed.
assert "zip" in docx_targets, "docx -> zip should be advertised now"
assert zip_targets == ["tar"], "zip should only re-pack to tar, got %r" % (zip_targets,)

for ext in ("docx", "png", "pdf", "zip"):
    for target in service.get_supported_conversions(ext):
        route = routes_table.lookup(ext, target)
        assert route is not None, "advertised %s->%s has no usable route" % (ext, target)
        assert route.available_engine(), "advertised %s->%s has no engine" % (ext, target)

print("\nSERVER IMPORT OK")
