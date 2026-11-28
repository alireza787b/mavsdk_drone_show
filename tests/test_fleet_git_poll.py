import asyncio

import httpx
import pytest

from fleet_git_poll import poll_git_reports


@pytest.mark.asyncio
async def test_reports_are_bounded_identity_checked_and_yield_as_they_arrive():
    release = asyncio.Event()
    first = asyncio.Event()
    active = peak = 0
    reports = {}

    async def serve(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        ident = request.url.host.split("-")[-1]
        try:
            if ident == "0":
                await release.wait()
            if ident == "2":
                raise httpx.ConnectError("no link")
            return httpx.Response(200, json={"hw_id": "other" if ident == "3" else ident, "status": "clean"})
        finally:
            active -= 1

    def publish(hw, started, report):
        reports[hw] = report
        first.set()

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        targets = [{"hw_id": str(i), "ip": f"node-{i}"} for i in range(100)]
        poll = asyncio.create_task(poll_git_reports(client, targets, port=80, timeout=2,
                                                    concurrency=4, publish=publish))
        try:
            await asyncio.wait_for(first.wait(), timeout=2)
            assert "0" not in reports
        finally:
            release.set()
            await poll

    assert 1 < peak <= 4
    assert len(reports) == 100
    assert reports["2"] == reports["3"] == {"status": "unknown"}
    assert reports["0"]["last_check"] > 0
