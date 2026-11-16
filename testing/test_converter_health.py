"""Converter health endpoint: shape, status code and degraded detection.

The endpoint exists so an operator can tell "the converter is fine" apart from
"the route table advertises 373 conversions but the engines are gone". These
checks pin down both answers without starting the full server.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.files.converters import health, registry, routes_table

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        failures.append(label)
        if detail:
            print(f"      {detail}")


async def main():
    app = web.Application()
    app.router.add_get("/api/files/convert/health", health.health_handler)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/files/convert/health")
        payload = await resp.json()

        check("endpoint answers", resp.status in (200, 503),
              f"unexpected status {resp.status}")
        check("payload is JSON object", isinstance(payload, dict))

        # Liveness is 200 only when nothing important is missing.
        missing = payload.get("missing_engines", [])
        check("status matches engine availability",
              (resp.status == 200) == (not missing),
              f"status={resp.status} missing={missing}")

        check("status field is coherent",
              payload.get("status") in ("ok", "degraded", "disabled"),
              f"status={payload.get('status')}")

        check("route counts add up",
              payload["routes"]["available"] + payload["routes"]["unavailable"]
              == payload["routes"]["total"],
              str(payload["routes"]))

        check("every engine is reported",
              set(payload["engines"]) == set(registry.ENGINES),
              f"got {sorted(payload['engines'])}")

        check("each engine reports availability as a bool",
              all(isinstance(info["available"], bool)
                  for info in payload["engines"].values()))

        check("queue depth is an integer", isinstance(payload["queue"]["depth"], int),
              str(payload["queue"]))

        check("worker count is present", "inline" in payload["workers"])

        check("response is not cacheable",
              resp.headers.get("Cache-Control") == "no-store")

        # Degraded path: with every engine marked unavailable, a liveness probe
        # must fail loudly instead of reporting a healthy converter.
        original_available = registry.EngineSpec.available
        try:
            registry.EngineSpec.available = property(lambda self: False)
            resp2 = await client.get("/api/files/convert/health")
            payload2 = await resp2.json()
            check("all engines missing -> 503", resp2.status == 503,
                  f"got {resp2.status}")
            check("all engines missing -> status degraded",
                  payload2.get("status") == "degraded", str(payload2.get("status")))
            check("all engines listed as missing",
                  len(payload2["missing_engines"]) == len(registry.ENGINES))
        finally:
            registry.EngineSpec.available = original_available

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED")
        return 1
    print("CONVERTER HEALTH CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
