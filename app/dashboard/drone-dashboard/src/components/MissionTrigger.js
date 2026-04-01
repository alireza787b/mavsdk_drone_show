//app/dashboard/drone-dashboard/src/components/MissionTrigger.js
import React, { useState, useEffect } from 'react';
import {
  FaBan,
  FaBroadcastTower,
  FaFileAlt,
  FaProjectDiagram,
  FaQuestionCircle,
  FaRoute,
} from 'react-icons/fa';
import { toast } from 'react-toastify';
import MissionCard from './MissionCard';
import MissionDetails from './MissionDetails';
import {
  DRONE_MISSION_TYPES,
  DRONE_MISSION_DISPLAY_ORDER,
  defaultTriggerTimeDelay,
  getMissionDescription,
  getCommandName,
} from '../constants/droneConstants';
import {
  buildCommandSchedule,
  COMMAND_DELAY_PRESETS,
  COMMAND_SCHEDULE_MODES,
  formatDateTimeLocalInput,
} from '../utilities/commandScheduling';
import { getMissionExecutionPolicy } from '../utilities/commandExecutionPolicy';
import '../styles/MissionTrigger.css';

const MISSION_PRESENTATIONS = {
  [DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV]: {
    icon: FaBroadcastTower,
    category: 'Synchronized show',
    summary: 'Launch the active SkyBrush package.',
    note: 'Verify geometry and launch readiness first.',
  },
  [DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW]: {
    icon: FaFileAlt,
    category: 'Custom protocol',
    summary: 'Replay a custom CSV from each launch point.',
    note: 'Use for controlled protocol runs, not the normal show pipeline.',
  },
  [DRONE_MISSION_TYPES.SMART_SWARM]: {
    icon: FaProjectDiagram,
    category: 'Live formation',
    summary: 'Start the published leader-follower topology.',
    note: 'Confirm roles, offsets, and override doctrine first.',
  },
  [DRONE_MISSION_TYPES.SWARM_TRAJECTORY]: {
    icon: FaRoute,
    category: 'Route package',
    summary: 'Dispatch the processed trajectory package.',
    note: 'Use after route processing and launch review.',
  },
  [DRONE_MISSION_TYPES.NONE]: {
    icon: FaBan,
    category: 'Abort / recovery',
    summary: 'Stop the active mission immediately.',
    note: 'Use when the operator must interrupt the current mission flow.',
  },
};

const DEFAULT_MISSION_PRESENTATION = {
  icon: FaQuestionCircle,
  category: 'Mission',
  summary: 'Review mission details before dispatch.',
  note: '',
};

function getMissionPresentation(missionType) {
  return MISSION_PRESENTATIONS[missionType] || DEFAULT_MISSION_PRESENTATION;
}

const MissionTrigger = ({
  missionTypes,
  onSendCommand,
  referenceNowMs = Date.now(),
  clockOffsetLabel = null,
  targetMode = 'all',
  selectedDrones = [],
}) => {
  const [selectedMission, setSelectedMission] = useState('');
  const [timeDelay, setTimeDelay] = useState(defaultTriggerTimeDelay);
  const [scheduleMode, setScheduleMode] = useState(COMMAND_SCHEDULE_MODES.DELAY);
  const [selectedDateTime, setSelectedDateTime] = useState('');
  const [autoGlobalOrigin, setAutoGlobalOrigin] = useState(true); // Default enabled for precision
  const [useGlobalSetpoints, setUseGlobalSetpoints] = useState(true); // Default to GLOBAL mode

  useEffect(() => {
    setSelectedDateTime(formatDateTimeLocalInput(referenceNowMs + 30000));
  }, [referenceNowMs]);

  const handleMissionSelect = (missionType) => {
    setSelectedMission(missionType);
    setTimeDelay(defaultTriggerTimeDelay);
    setScheduleMode(COMMAND_SCHEDULE_MODES.DELAY);

    if (missionType === DRONE_MISSION_TYPES.NONE) {
      // Directly send the command for 'Cancel Mission'
      const commandData = {
        missionType: String(missionType),
        triggerTime: "0", // Immediate action (string for API compatibility)
        uiMeta: {
          triggerSummary: 'Immediate cancel on acceptance',
          details: [
            {
              label: 'Execution',
              value: 'Cancels the current mission immediately after drone acceptance.',
            },
          ],
        },
      };
      onSendCommand(commandData);
    }
  };

  const handleSend = () => {
    const schedule = buildCommandSchedule({
      scheduleMode,
      timeDelay,
      selectedDateTime,
      referenceNowMs,
    });

    if (schedule.error) {
      toast.error(schedule.error);
      return;
    }

    const isCustomCsvMission = selectedMission === DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW;
    const missionExecutionPolicy = getMissionExecutionPolicy(selectedMission, {
      isImmediate: schedule.isImmediate,
    });
    const commandData = {
      missionType: String(selectedMission),
      triggerTime: String(schedule.triggerTimeSec ?? 0),
      auto_global_origin: isCustomCsvMission ? false : autoGlobalOrigin,
      use_global_setpoints: isCustomCsvMission ? false : useGlobalSetpoints,
      uiMeta: {
        triggerSummary: schedule.summary,
        details: [
          {
            label: 'Schedule',
            value: schedule.detail,
          },
          {
            label: 'Clock source',
            value: clockOffsetLabel
              ? `GCS-aligned scheduler (${clockOffsetLabel})`
              : 'GCS-aligned scheduler',
          },
          ...(missionExecutionPolicy
            ? [{
              label: 'Execution policy',
              value: missionExecutionPolicy,
            }]
            : []),
          ...(selectedMission === DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV
            ? [
              {
                label: 'Control mode',
                value: isCustomCsvMission
                  ? 'LOCAL launch-frame only'
                  : (useGlobalSetpoints ? 'GLOBAL setpoints' : 'LOCAL launch-frame replay'),
              },
              ...(useGlobalSetpoints
                ? [{
                  label: 'Launch correction',
                  value: autoGlobalOrigin ? 'Auto Global Launch Corrector enabled' : 'Manual global launch placement',
                }]
                : []),
            ]
            : []),
          ...(selectedMission === DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW
            ? [{
              label: 'Execution mode',
              value: 'LOCAL launch-frame only',
            }]
            : []),
        ],
      },
    };
    onSendCommand(commandData);
  };

  const handleBack = () => {
    setSelectedMission('');
  };

  return (
    <div className="mission-trigger-container">
      {!selectedMission && (
        <div className="mission-cards">
          {DRONE_MISSION_DISPLAY_ORDER.map((mission) => {
            const presentation = getMissionPresentation(mission.value);
            const MissionIcon = presentation.icon;

            return (
              <MissionCard
                key={mission.value}
                missionType={mission.value}
                icon={<MissionIcon aria-hidden="true" />}
                category={presentation.category}
                summary={presentation.summary}
                note={presentation.note}
                label={getCommandName(mission.value)}
                onClick={() => handleMissionSelect(mission.value)}
                isCancel={mission.value === DRONE_MISSION_TYPES.NONE}
              />
            );
          })}
        </div>
      )}

      {selectedMission && selectedMission !== DRONE_MISSION_TYPES.NONE && (
        (() => {
          const presentation = getMissionPresentation(selectedMission);
          const MissionIcon = presentation.icon;

          return (
            <MissionDetails
              missionType={selectedMission}
              icon={<MissionIcon aria-hidden="true" />}
              profile={presentation.category}
              label={getCommandName(selectedMission)}
              description={getMissionDescription(selectedMission)}
              scheduleMode={scheduleMode}
              timeDelay={timeDelay}
              selectedDateTime={selectedDateTime}
              onTimeDelayChange={setTimeDelay}
              onTimePickerChange={setSelectedDateTime}
              onScheduleModeChange={setScheduleMode}
              autoGlobalOrigin={autoGlobalOrigin}
              onAutoGlobalOriginChange={setAutoGlobalOrigin}
              useGlobalSetpoints={useGlobalSetpoints}
              onUseGlobalSetpointsChange={setUseGlobalSetpoints}
              delayPresets={COMMAND_DELAY_PRESETS}
              referenceNowMs={referenceNowMs}
              clockOffsetLabel={clockOffsetLabel}
              targetMode={targetMode}
              selectedDrones={selectedDrones}
              onSend={handleSend}
              onBack={handleBack}
            />
          );
        })()
      )}
    </div>
  );
};

export default MissionTrigger;
