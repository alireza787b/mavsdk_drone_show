// src/constants/droneConstants.js
import {
    buildGcsUrl,
    buildShowPlotUrl,
    GCS_ROUTE_KEYS,
} from '../services/gcsApiService';
import {
    COMMAND_CATALOG,
    COMMAND_METADATA_BY_VALUE,
    getCommandMetadata,
} from './missionCatalog';

const buildTypeMap = (kind) => Object.freeze(COMMAND_CATALOG.reduce((result, command) => {
    if (command.kind === kind) {
        result[command.key] = command.value;
    }
    return result;
}, {}));

const buildNameMap = (kind) => Object.freeze(COMMAND_CATALOG.reduce((result, command) => {
    if (command.kind === kind) {
        result[command.value] = command.commandLabel;
    }
    return result;
}, {}));

export const DRONE_MISSION_TYPES = buildTypeMap('mission');

// Define mission display order for better UX (Cancel last as requested)
export const DRONE_MISSION_DISPLAY_ORDER = Object.freeze(COMMAND_CATALOG
    .filter((command) => Number.isFinite(command.missionPickerOrder))
    .sort((left, right) => left.missionPickerOrder - right.missionPickerOrder)
    .map((command) => Object.freeze({ key: command.key, value: command.value })));

export const DRONE_ACTION_TYPES = buildTypeMap('action');

export const DRONE_MISSION_IMAGES = {
    [DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV]: buildShowPlotUrl('combined_drone_paths.jpg'),
    [DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW]: buildGcsUrl(GCS_ROUTE_KEYS.customShowImage),
};

export const DRONE_MISSION_NAMES = buildNameMap('mission');

export const DRONE_ACTION_NAMES = buildNameMap('action');

export const getMissionDescription = (missionType) => {
    return getCommandMetadata(missionType)?.description || '';
};

export const getCommandName = (missionType) => {
    return COMMAND_METADATA_BY_VALUE[missionType]?.commandLabel || 'Unknown Command';
};

export const defaultTriggerTimeDelay = 10;
