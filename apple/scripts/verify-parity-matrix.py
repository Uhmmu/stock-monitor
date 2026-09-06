#!/usr/bin/env python3
"""Fail when the review matrix and the native route catalog drift apart."""

import json
import re
from pathlib import Path


APPLE_ROOT = Path(__file__).resolve().parents[1]
matrix = json.loads((APPLE_ROOT / "Tests/Parity/web-mac-parity-v1.json").read_text())
source = (APPLE_ROOT / "Packages/StockMonitorFeatures/Sources/StockMonitorFeatures/GoalM6.swift").read_text()

catalog_routes = re.findall(r"\.init\(\.([A-Za-z0-9]+), webSurface:", source)
matrix_routes = [entry["mac_route"] for entry in matrix["entries"]]

assert matrix["schema_version"] == 1
assert matrix["status_values"] == ["verified", "runtime_pending", "exception"]
assert len(catalog_routes) == len(set(catalog_routes)), "duplicate native route in Swift parity catalog"
assert len(matrix_routes) == len(set(matrix_routes)), "duplicate native route in parity matrix"
assert set(catalog_routes) == set(matrix_routes), "Swift catalog and parity matrix routes differ"
assert all(entry["status"] in matrix["status_values"] for entry in matrix["entries"])
assert all(entry["web_surface"] and entry["evidence"] for entry in matrix["entries"])
assert not [entry for entry in matrix["entries"] if entry["status"] == "exception" and not entry.get("accepted_by_user")]

print(f"parity_matrix_routes={len(matrix_routes)}")
print("parity_matrix_contract=valid")
