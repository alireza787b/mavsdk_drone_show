from types import SimpleNamespace
from swarm_node_evidence import swarm_node_evidence


def command(cid, created, targets, phase='active', mission=2):
    return SimpleNamespace(command_id=cid,created_at=created,target_drones=targets,mission_type=mission,
        params={'smart_swarm':{'revision':'same'},'_swarm_runtime':{hw:{'phase':phase,'received_at_ms':1000} for hw in targets}})


def test_a_healthy_leaders_old_command_cannot_mask_the_followers_new_retry():
    old=command('old',100,['1','2'],phase='failed')
    old.params['_swarm_runtime']['1']['phase']='active'
    retry=command('retry',200,['2'])
    result=swarm_node_evidence([retry,old],['1','2'],'same',1001)
    assert result['1']['command_id']=='old' and result['1']['report']['phase']=='active'
    assert result['2']['command_id']=='retry' and result['2']['report']['phase']=='active'


def test_new_recovery_or_stale_data_does_not_keep_claiming_old_following():
    old=command('old',100,['1','2'])
    recovery=command('hold',200,['2'],mission=102)
    result=swarm_node_evidence([old,recovery],['1','2'],'same',1001)
    assert result['2']['stale'] and result['2']['report'] is None and result['2']['has_session']
    assert swarm_node_evidence([old],['1'],'same',30000)['1']['stale']
    assert swarm_node_evidence([old],['1'],'changed',1001)['1']['stale']
