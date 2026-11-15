from copy import deepcopy
import threading
from types import SimpleNamespace

import pytest
from fleet_telemetry_snapshot import fleet_telemetry_snapshot


def fixture():
    return SimpleNamespace(telemetry_lock=threading.Lock(), telemetry_data_all_drones={'1': {
        'hw_id':'1','update_time':1000,'timestamp':1000,'telemetry_available':False,
        'is_armed':True,'readiness_status':'unknown','heartbeat_last_seen':500,
    }}, get_all_heartbeats=lambda:{'1':{'received_at_gcs_ms':1700000000000,'timestamp':9999999999999,
        'network_info':{'wifi':{'ssid':'Demo','signal_strength_percent':80}}}})


def test_accepted_heartbeat_advances_during_failed_telemetry_without_fabricating_fc_state():
    deps=fixture(); original=deepcopy(deps.telemetry_data_all_drones)
    snapshot=fleet_telemetry_snapshot(deps)
    assert snapshot['1']['heartbeat_last_seen']==1700000000000
    for key in ('update_time','timestamp','telemetry_available','is_armed','readiness_status'):
        assert snapshot['1'][key]==original['1'][key]
    assert deps.telemetry_data_all_drones==original
    snapshot['1']['heartbeat_network_info']['wifi']['ssid']='Changed'
    assert deps.get_all_heartbeats()['1']['network_info']['wifi']['ssid']=='Demo'


@pytest.mark.parametrize('receipt',[None,0,-1,'bad'])
def test_explicit_invalid_canonical_receipt_never_becomes_the_newer_node_clock(receipt):
    deps=fixture(); deps.get_all_heartbeats=lambda:{'1':{'received_at_gcs_ms':receipt,'timestamp':9999999999999}}
    deps.telemetry_data_all_drones['1']['presence']={'configured':True,'heartbeat_received_at_gcs_ms':123}
    snapshot=fleet_telemetry_snapshot(deps)['1']
    assert snapshot['heartbeat_last_seen']==receipt
    assert snapshot['presence']['heartbeat_received_at_gcs_ms'] is None
    assert snapshot['presence']['heartbeat_recent'] is False


def test_no_heartbeat_does_not_erase_cached_metadata_or_add_a_heartbeat_only_aircraft():
    deps=fixture();deps.get_all_heartbeats=lambda:{'2':{'received_at_gcs_ms':1700000000000}}
    assert fleet_telemetry_snapshot(deps)==deps.telemetry_data_all_drones


def test_snapshot_releases_telemetry_lock_before_loading_heartbeat_and_legacy_timestamp_is_supported():
    deps=fixture()
    def heartbeats():
        assert deps.telemetry_lock.acquire(blocking=False)
        deps.telemetry_lock.release()
        return {'1':{'timestamp':1700000000000}}
    deps.get_all_heartbeats=heartbeats
    assert fleet_telemetry_snapshot(deps)['1']['heartbeat_last_seen']==1700000000000
