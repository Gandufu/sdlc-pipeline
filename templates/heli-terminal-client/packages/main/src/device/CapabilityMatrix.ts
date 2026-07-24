export enum DeviceModel {
  MEETING_EYE_500 = 'MeetingEye 500',
  MEETING_EYE_900 = 'MeetingEye 900',
  MEETING_BOARD = 'MeetingBoard',
  MEETING_BOARD_PRO = 'MeetingBoard Pro',
  MEETING_BOARD_C = 'MeetingBoard C',
  MEETING_DISPLAY = 'MeetingDisplay',
  MEETING_BAR_A10 = 'MeetingBar A10',
  MEETING_BAR_A40 = 'MeetingBar A40',
  MEETING_BAR_A50 = 'MeetingBar A50',
  UNKNOWN = 'Unknown',
}

export interface CapabilitySet {
  supportsButton: boolean;
  supportsCameraActive: boolean;
  supportsCameraLayout: boolean;
  supportsScreenBrightness: boolean;
  supportsInputSource: boolean;
}

const ALL_FALSE: CapabilitySet = {
  supportsButton: false,
  supportsCameraActive: false,
  supportsCameraLayout: false,
  supportsScreenBrightness: false,
  supportsInputSource: false,
};

/** 仅 MeetingEye 500 支持 button 模拟 */
const ME500: CapabilitySet = {
  ...ALL_FALSE,
  supportsButton: true,
  supportsCameraActive: true,
};

const ME900: CapabilitySet = {
  ...ALL_FALSE,
  supportsCameraActive: true,
};

const BOARD_FAMILY: CapabilitySet = {
  ...ALL_FALSE,
  supportsCameraActive: true,
  supportsScreenBrightness: true,
  supportsInputSource: true,
};

const DISPLAY: CapabilitySet = {
  ...BOARD_FAMILY,
};

const MBA_FAMILY: CapabilitySet = {
  ...ALL_FALSE,
};

const TABLE: Record<DeviceModel, CapabilitySet> = {
  [DeviceModel.MEETING_EYE_500]: ME500,
  [DeviceModel.MEETING_EYE_900]: ME900,
  [DeviceModel.MEETING_BOARD]: BOARD_FAMILY,
  [DeviceModel.MEETING_BOARD_PRO]: BOARD_FAMILY,
  [DeviceModel.MEETING_BOARD_C]: BOARD_FAMILY,
  [DeviceModel.MEETING_DISPLAY]: DISPLAY,
  [DeviceModel.MEETING_BAR_A10]: MBA_FAMILY,
  [DeviceModel.MEETING_BAR_A40]: MBA_FAMILY,
  [DeviceModel.MEETING_BAR_A50]: MBA_FAMILY,
  [DeviceModel.UNKNOWN]: ALL_FALSE,
};

export const CapabilityMatrix = {
  for(model: string): CapabilitySet {
    const key = (Object.values(DeviceModel) as string[]).find((m) => m === model);
    if (!key) {
      return TABLE[DeviceModel.UNKNOWN];
    }
    return TABLE[key as DeviceModel];
  },
};
