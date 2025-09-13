"""
Swarm Trajectory Session Management
Handles change detection, session tracking, and smart processing decisions
"""

import os
import json
import hashlib
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict

from functions.swarm_analyzer import fetch_swarm_data
from functions.swarm_trajectory_utils import get_swarm_trajectory_folders

logger = logging.getLogger(__name__)

@dataclass
class ProcessingSession:
    """Represents a trajectory processing session"""
    session_id: str
    timestamp: str
    swarm_fingerprint: str
    processed_leaders: List[int]
    total_drones: int
    parameters_hash: str

class SwarmSessionManager:
    """Manages swarm trajectory processing sessions and change detection"""

    def __init__(self):
        self.folders = get_swarm_trajectory_folders()
        self.session_file = os.path.join(self.folders['base'], '.trajectory_session.json')

    def generate_swarm_fingerprint(self) -> str:
        """Generate fingerprint of current swarm configuration"""
        try:
            swarm_data = fetch_swarm_data()
            # Sort by hw_id for consistent fingerprinting
            sorted_data = sorted(swarm_data, key=lambda x: x.get('hw_id', 0))

            # Include critical fields that affect trajectory processing
            fingerprint_data = []
            for drone in sorted_data:
                fingerprint_data.append({
                    'hw_id': drone.get('hw_id'),
                    'follow': drone.get('follow'),
                    'offset_n': drone.get('offset_n'),
                    'offset_e': drone.get('offset_e'),
                    'offset_alt': drone.get('offset_alt'),
                    'body_coord': drone.get('body_coord')
                })

            fingerprint_str = json.dumps(fingerprint_data, sort_keys=True)
            return hashlib.md5(fingerprint_str.encode()).hexdigest()

        except Exception as e:
            logger.error(f"Failed to generate swarm fingerprint: {e}")
            return "unknown"

    def generate_parameters_hash(self) -> str:
        """Generate hash of processing parameters that affect output"""
        try:
            from src.params import Params

            # Include parameters that affect trajectory processing
            param_data = {
                'swarm_leader_led_color': getattr(Params, 'swarm_leader_led_color', None),
                'swarm_follower_led_color': getattr(Params, 'swarm_follower_led_color', None),
                'swarm_smoothing_factor': getattr(Params, 'swarm_smoothing_factor', None),
                'swarm_formation_spacing': getattr(Params, 'swarm_formation_spacing', None),
                'sim_mode': getattr(Params, 'sim_mode', False)
            }

            param_str = json.dumps(param_data, sort_keys=True)
            return hashlib.md5(param_str.encode()).hexdigest()

        except Exception as e:
            logger.error(f"Failed to generate parameters hash: {e}")
            return "unknown"

    def get_current_session(self) -> Optional[ProcessingSession]:
        """Get the current processing session if it exists"""
        try:
            if not os.path.exists(self.session_file):
                return None

            with open(self.session_file, 'r') as f:
                session_data = json.load(f)
                return ProcessingSession(**session_data)

        except Exception as e:
            logger.error(f"Failed to load session: {e}")
            return None

    def save_session(self, session: ProcessingSession):
        """Save processing session to file"""
        try:
            os.makedirs(os.path.dirname(self.session_file), exist_ok=True)
            with open(self.session_file, 'w') as f:
                json.dump(asdict(session), f, indent=2)
            logger.info(f"Saved processing session {session.session_id}")

        except Exception as e:
            logger.error(f"Failed to save session: {e}")

    def get_uploaded_leaders(self) -> List[int]:
        """Get list of leaders that have uploaded trajectory files"""
        try:
            uploaded = []
            raw_dir = self.folders['raw']

            if not os.path.exists(raw_dir):
                return uploaded

            for filename in os.listdir(raw_dir):
                if filename.endswith('.csv') and filename.startswith('Drone '):
                    try:
                        drone_id = int(filename.replace('Drone ', '').replace('.csv', ''))
                        uploaded.append(drone_id)
                    except ValueError:
                        continue

            return sorted(uploaded)

        except Exception as e:
            logger.error(f"Failed to get uploaded leaders: {e}")
            return []

    def detect_changes(self) -> Dict[str, Any]:
        """Detect what has changed since last processing session"""
        current_session = self.get_current_session()
        current_fingerprint = self.generate_swarm_fingerprint()
        current_params = self.generate_parameters_hash()
        uploaded_leaders = self.get_uploaded_leaders()

        changes = {
            'has_previous_session': current_session is not None,
            'swarm_structure_changed': False,
            'parameters_changed': False,
            'new_uploads': [],
            'missing_uploads': [],
            'leader_structure_changed': False,
            'requires_full_reprocess': False,
            'safe_to_incremental': True
        }

        if current_session is None:
            changes['requires_full_reprocess'] = True
            changes['safe_to_incremental'] = False
            logger.info("No previous session found - full processing required")
            return changes

        # Check swarm structure changes
        if current_fingerprint != current_session.swarm_fingerprint:
            changes['swarm_structure_changed'] = True
            changes['requires_full_reprocess'] = True
            changes['safe_to_incremental'] = False
            logger.warning("Swarm structure changed - full reprocess required")

        # Check parameter changes
        if current_params != current_session.parameters_hash:
            changes['parameters_changed'] = True
            changes['requires_full_reprocess'] = True
            changes['safe_to_incremental'] = False
            logger.warning("Processing parameters changed - full reprocess required")

        # Check upload changes
        previous_leaders = set(current_session.processed_leaders)
        current_leaders = set(uploaded_leaders)

        changes['new_uploads'] = list(current_leaders - previous_leaders)
        changes['missing_uploads'] = list(previous_leaders - current_leaders)

        # Check if leader structure changed (critical edge case)
        if changes['missing_uploads'] or (changes['new_uploads'] and changes['swarm_structure_changed']):
            changes['leader_structure_changed'] = True
            changes['requires_full_reprocess'] = True
            changes['safe_to_incremental'] = False
            logger.warning("Leader structure changed - full reprocess required")

        return changes

    def create_processing_session(self, processed_leaders: List[int], total_drones: int) -> ProcessingSession:
        """Create a new processing session"""
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        timestamp = datetime.now().isoformat()

        session = ProcessingSession(
            session_id=session_id,
            timestamp=timestamp,
            swarm_fingerprint=self.generate_swarm_fingerprint(),
            processed_leaders=processed_leaders,
            total_drones=total_drones,
            parameters_hash=self.generate_parameters_hash()
        )

        self.save_session(session)
        return session

    def clear_session(self):
        """Clear current processing session"""
        try:
            if os.path.exists(self.session_file):
                os.remove(self.session_file)
                logger.info("Cleared processing session")
        except Exception as e:
            logger.error(f"Failed to clear session: {e}")

    def get_processing_recommendation(self) -> Dict[str, Any]:
        """Get smart recommendation for processing approach"""
        changes = self.detect_changes()
        uploaded_leaders = self.get_uploaded_leaders()

        recommendation = {
            'action': 'unknown',
            'message': '',
            'details': [],
            'requires_confirmation': False,
            'uploaded_count': len(uploaded_leaders),
            'changes': changes
        }

        if not uploaded_leaders:
            recommendation.update({
                'action': 'no_uploads',
                'message': 'No trajectory files uploaded',
                'details': ['Please upload at least one leader trajectory before processing']
            })
            return recommendation

        if changes['requires_full_reprocess']:
            if changes['swarm_structure_changed']:
                recommendation.update({
                    'action': 'mandatory_full_reprocess',
                    'message': 'Configuration changed - full reprocess required',
                    'details': [
                        'Swarm structure has been modified',
                        'Existing trajectories are incompatible',
                        'All data will be cleared and reprocessed'
                    ],
                    'requires_confirmation': True
                })
            elif changes['parameters_changed']:
                recommendation.update({
                    'action': 'mandatory_full_reprocess',
                    'message': 'Parameters changed - full reprocess required',
                    'details': [
                        'Processing parameters have been modified',
                        'Existing trajectories may be inconsistent',
                        'All data will be cleared and reprocessed'
                    ],
                    'requires_confirmation': True
                })
            elif changes['leader_structure_changed']:
                recommendation.update({
                    'action': 'mandatory_full_reprocess',
                    'message': 'Leader structure changed - full reprocess required',
                    'details': [
                        'Top leaders have been modified',
                        'Formation structure is now incompatible',
                        'All data will be cleared and reprocessed'
                    ],
                    'requires_confirmation': True
                })
            else:
                recommendation.update({
                    'action': 'recommended_full_reprocess',
                    'message': 'Full reprocess recommended for consistency',
                    'details': [
                        f'{len(uploaded_leaders)} trajectory files ready',
                        'Starting fresh ensures all data is consistent',
                        'Previous processed data will be cleared'
                    ],
                    'requires_confirmation': True
                })

        elif changes['new_uploads']:
            recommendation.update({
                'action': 'incremental_with_option',
                'message': f'New uploads detected - choose processing method',
                'details': [
                    f'{len(changes["new_uploads"])} new trajectory files uploaded',
                    'You can add to existing data or start fresh',
                    'Fresh processing recommended for consistency'
                ],
                'requires_confirmation': True
            })

        else:
            recommendation.update({
                'action': 'safe_incremental',
                'message': 'Ready to process trajectories',
                'details': [
                    f'{len(uploaded_leaders)} trajectory files ready',
                    'No conflicts detected with existing data'
                ]
            })

        return recommendation