import json

import pytest

from functions.trajectory_formation import read_formation, save_formation


def _formation():
    return [dict(hw_id=1, follow=0), dict(hw_id=2, follow=1, offset_x=6)]


def test_snapshot_is_independent_of_live_formation(tmp_path):
    live = _formation()
    initial = read_formation(tmp_path, lambda: live)
    assert initial['saved'] is False
    assert not (tmp_path / 'formation.json').exists()
    saved = save_formation(initial['assignments'], initial['revision'], tmp_path, lambda: live)
    live[1]['follow'] = 0
    assert read_formation(tmp_path, lambda: live) == saved
    assert saved['assignments'][1]['follow'] == '1'


def test_concurrent_edit_rejects_stale_revision(tmp_path):
    live = _formation()
    original = read_formation(tmp_path, lambda: live)
    changed = _formation()
    changed[1]['offset_x'] = 9
    saved = save_formation(changed, original['revision'], tmp_path, lambda: live)
    with pytest.raises(ValueError, match='changed'):
        save_formation(live, original['revision'], tmp_path, lambda: live)
    assert read_formation(tmp_path) == saved


@pytest.mark.parametrize('invalid', [[], [dict(hw_id=1, follow=2)],
                                    [dict(hw_id=1, follow=1)], [dict(hw_id=1, offset_x=float('nan'))]])
def test_invalid_snapshot_does_not_overwrite(tmp_path, invalid):
    initial = read_formation(tmp_path, _formation)
    with pytest.raises(ValueError):
        save_formation(invalid, initial['revision'], tmp_path, _formation)
    assert not (tmp_path / 'formation.json').exists()


def test_corrupt_snapshot_is_not_replaced_with_live_roles(tmp_path):
    (tmp_path / 'formation.json').write_text(json.dumps({'assignments': _formation(), 'revision': 'bad'}))
    with pytest.raises(ValueError, match='invalid'):
        read_formation(tmp_path, _formation)
