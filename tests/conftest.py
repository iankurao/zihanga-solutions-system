"""Shared pytest setup.

Route coverage: set ROUTE_COVERAGE=<file> to record which Flask endpoints the
suite exercised; the file lists every endpoint with its hit count and the
ones never called, so gaps in API testing are visible.
"""
import collections
import os
import sys

from flask import request, request_started

_hits = collections.Counter()


def _record(sender, **extra):
    if request.endpoint:
        _hits[request.endpoint] += 1


if os.getenv("ROUTE_COVERAGE"):
    request_started.connect(_record, weak=False)


def pytest_sessionfinish(session, exitstatus):
    target = os.getenv("ROUTE_COVERAGE")
    entry = sys.modules.get("backend.app")
    if not target or entry is None:
        return
    endpoints = sorted(e for e in entry.app.view_functions if e != "static")
    missed = [e for e in endpoints if not _hits[e]]
    with open(target, "w", encoding="utf-8") as report:
        report.write(f"{len(endpoints) - len(missed)}/{len(endpoints)} endpoints exercised\n\n")
        report.write("Never called:\n")
        report.writelines(f"  {e}\n" for e in missed)
        report.write("\nCalls per endpoint:\n")
        report.writelines(f"  {_hits[e]:5d}  {e}\n" for e in endpoints)
