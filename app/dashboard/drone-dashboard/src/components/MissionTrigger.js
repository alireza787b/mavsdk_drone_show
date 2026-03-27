//app/dashboard/drone-dashboard/src/components/MissionTrigger.js
import React, { useState, useEffect } from 'react';
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
import '../styles/MissionTrigger.css';

const MissionTrigger = ({
  missionTypes,
  onSendCommand,
  referenceNowMs = Date.now(),
  clockOffsetLabel = null,
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
          {DRONE_MISSION_DISPLAY_ORDER.map((mission) => (
            <MissionCard
              key={mission.value}
              missionType={mission.value}
              icon={
                mission.value === DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV
                  ? '🛸'
                  : mission.value === DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW
                  ? '🎯'
                  : mission.value === DRONE_MISSION_TYPES.SMART_SWARM
                  ? '🐝🐝🐝'
                  : mission.value === DRONE_MISSION_TYPES.SWARM_TRAJECTORY
                  ? '🚀🛸🚀'
                  : '🚫'
              }
              label={getCommandName(mission.value)}
              onClick={() => handleMissionSelect(mission.value)}
              isCancel={mission.value === DRONE_MISSION_TYPES.NONE}
            />
          ))}
        </div>
      )}

      {selectedMission && selectedMission !== DRONE_MISSION_TYPES.NONE && (
        <MissionDetails
          missionType={selectedMission}
          icon={
            selectedMission === DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV
              ? '🛸'
              : selectedMission === DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW
              ? '🎯'
              : selectedMission === DRONE_MISSION_TYPES.SMART_SWARM
              ? '🐝🐝🐝'
              : selectedMission === DRONE_MISSION_TYPES.SWARM_TRAJECTORY
              ? '🚀🛸🚀'
              : '❓'
          }
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
          onSend={handleSend}
          onBack={handleBack}
        />
      )}
    </div>
  );
};

export default MissionTrigger;
