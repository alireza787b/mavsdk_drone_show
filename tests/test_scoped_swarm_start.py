import time
from threading import Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from command_tracker import CommandTracker, CommandCallbackAuthenticationError
from api_routes.swarm_runtime import create_swarm_runtime_router
from smart_swarm_service import resolve_start_scope, start_cluster
from src.smart_swarm_contract import normalize_topology, topology_revision, SmartSwarmSession, SwarmStartRequest, SwarmRuntimeReport


def topology():
    return normalize_topology([{'hw_id':1,'follow':0}, {'hw_id':2,'follow':1}, {'hw_id':3,'follow':2}])


def test_explicit_subset_is_not_inferred_from_availability_and_never_reparents():
    members=topology()
    cluster={'cluster_id':'1','members':members}
    request=SwarmStartRequest(cluster_id='1',revision=topology_revision(members),target_hw_ids=['3'],idempotency_key='one')
    assert resolve_start_scope(cluster,request)==(['3'],['1','2'],[])
    assert [m['follow'] for m in members]==['0','1','2']
    for ids in [['3','3'],['9'],['1','9']]:
        with pytest.raises(ValueError):resolve_start_scope(cluster,request.model_copy(update={'target_hw_ids':ids}))


@pytest.mark.asyncio
async def test_targeted_start_only_dispatches_selected_aircraft(monkeypatch):
    members=topology()
    deps=SimpleNamespace(load_swarm=lambda:members,telemetry_lock=Lock(),telemetry_data_all_drones={},
                         get_command_tracker=lambda:CommandTracker())
    submit=AsyncMock(return_value='accepted')
    monkeypatch.setattr('command_submission.submit_tracked_command',submit)
    request=SwarmStartRequest(cluster_id='1',revision=topology_revision(members),target_hw_ids=['3'],idempotency_key='one')
    assert await start_cluster(deps,request)=='accepted'
    command=submit.call_args.args[1]
    assert command.target_drone_ids==['3']
    assert command.smart_swarm.reference_hw_ids==['1','2']
    assert command.smart_swarm.expected_hw_ids==['3']


@pytest.mark.asyncio
async def test_start_barrier_revalidates_sources_then_stops_depending_on_gcs():
    members=topology()
    snapshot=SmartSwarmSession(assignments=members,revision=topology_revision(members),
                               expected_hw_ids=['3'],reference_hw_ids=['1','2'])
    tracker=CommandTracker()
    cid=await tracker.create_command(2,['3'],{'smart_swarm':snapshot.model_dump()},timeout_ms=45000)
    await tracker.mark_submitted(cid)
    capability=(await tracker.get_callback_capabilities(cid))['3']
    report=SwarmRuntimeReport(command_id=cid,hw_id='3',sequence=1,role='follower',follow='2',revision=snapshot.revision,phase='ready')
    with pytest.raises(CommandCallbackAuthenticationError):await tracker.pending_swarm_references(report,'wrong')
    assert await tracker.pending_swarm_references(report,capability)==['1','2']
    assert (await tracker.record_swarm_runtime(report,capability))['engage'] is False
    report=report.model_copy(update={'sequence':2})
    assert (await tracker.record_swarm_runtime(report,capability,reference_valid_until=time.monotonic()-1))['engage'] is False
    report=report.model_copy(update={'sequence':3})
    assert (await tracker.record_swarm_runtime(report,capability,reference_valid_until=time.monotonic()+1))['engage'] is True
    assert await tracker.pending_swarm_references(report,capability)==[]
    report=report.model_copy(update={'sequence':4,'phase':'active'})
    assert (await tracker.record_swarm_runtime(report,capability))['engage'] is True


@pytest.mark.asyncio
async def test_preview_reads_targets_and_references_in_distinct_read_only_roles():
    members=topology()
    rpc=SimpleNamespace(review_swarm_start=AsyncMock(return_value={'3':{'hw_id':'3','status':'ready','valid_for_ms':5000,'scoped_start_supported':True}}),
                        review_swarm_references=AsyncMock(return_value={hw:{'hw_id':hw,'status':'ready','valid_for_ms':5000} for hw in ['1','2']}))
    tracker=CommandTracker()
    deps=SimpleNamespace(load_swarm=lambda:members,load_config=lambda:[{'hw_id':hw,'ip':f'192.0.2.{hw}'} for hw in ['1','2','3']],
        telemetry_lock=Lock(),telemetry_data_all_drones={},get_command_tracker=lambda:tracker,get_fleet_rpc_service=lambda:rpc)
    app=FastAPI();app.include_router(create_swarm_runtime_router(deps))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/api/v1/swarm/runtime/preview',params={'cluster_id':'1','check_start':'true','target_hw_ids':'3'})
    assert response.status_code==200,response.text
    assert response.json()['reference_hw_ids']==['1','2']
    assert [d['hw_id'] for d in rpc.review_swarm_start.call_args.args[0]]==['3']
    assert [d['hw_id'] for d in rpc.review_swarm_references.call_args.args[0]]==['1','2']
    assert not tracker._commands
