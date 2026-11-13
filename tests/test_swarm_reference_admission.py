from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from swarm_start_readiness import read_reference_admissions, require_reference_admissions, read_start_admissions


@pytest.mark.asyncio
async def test_a_live_reference_with_a_not_yet_applied_role_cannot_form_a_reciprocal_follow():
    rpc=SimpleNamespace(review_swarm_references=AsyncMock(return_value={
        '1':{'hw_id':'1','status':'ready','valid_for_ms':5000,'swarm_active':True,'live_follow':2}}))
    deps=SimpleNamespace(load_config=lambda:[{'hw_id':'1'}],load_swarm=lambda:[{'hw_id':'1','follow':0}],get_fleet_rpc_service=lambda:rpc)
    decisions=await read_reference_admissions(deps,['1'])
    assert decisions['1']['status']=='waiting' and decisions['1']['valid_for_ms']==0
    with pytest.raises(HTTPException) as caught:await require_reference_admissions(deps,['1'])
    assert caught.value.detail['dispatched'] is False


@pytest.mark.asyncio
async def test_older_nodes_are_only_blocked_for_the_new_scope_not_normal_full_start():
    async def decision(_):return {'2':{'hw_id':'2','status':'ready','valid_for_ms':5000}}
    deps=SimpleNamespace(get_fleet_rpc_service=lambda:SimpleNamespace(review_swarm_start=decision))
    assert (await read_start_admissions(deps,[{'hw_id':'2'}]))['2']['status']=='ready'
    assert (await read_start_admissions(deps,[{'hw_id':'2'}],scoped=True))['2']['status']=='blocked'


@pytest.mark.asyncio
async def test_real_preflight_failure_is_not_hidden_by_an_older_node_capability_message():
    async def decision(_):return {'2':{'hw_id':'2','status':'blocked','message':'Aircraft not airborne','valid_for_ms':0}}
    deps=SimpleNamespace(get_fleet_rpc_service=lambda:SimpleNamespace(review_swarm_start=decision))
    assert (await read_start_admissions(deps,[{'hw_id':'2'}],scoped=True))['2']['message']=='Aircraft not airborne'
