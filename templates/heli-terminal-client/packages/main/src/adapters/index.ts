import { DeviceAdapter } from './DeviceAdapter';
import { MeetingEyeAdapter } from './MeetingEyeAdapter';
import { CapabilitySet, CapabilityMatrix, DeviceModel } from '../device/CapabilityMatrix';
import { HttpClient } from '../device/HttpClient';

/**
 * Adapter 工厂：根据 probe 探测到的 model 返回对应 Adapter。
 * 未知型号返回保守能力集 + 仍以 MeetingEye Adapter 实现（待后续阶段补其他机型 Adapter）。
 */
export const createAdapterFor = (
  model: DeviceModel,
  http: HttpClient
): DeviceAdapter => {
  const capabilities: CapabilitySet = CapabilityMatrix.for(model);

  switch (model) {
    case DeviceModel.MEETING_EYE_500:
    case DeviceModel.MEETING_EYE_900:
    case DeviceModel.MEETING_BOARD:
    case DeviceModel.MEETING_BOARD_PRO:
    case DeviceModel.MEETING_BOARD_C:
    case DeviceModel.MEETING_DISPLAY:
    case DeviceModel.MEETING_BAR_A10:
    case DeviceModel.MEETING_BAR_A40:
    case DeviceModel.MEETING_BAR_A50:
      // 阶段 1 只实现了 ME500 Adapter；其他机型共用同一 Adapter（能力集按 CapabilityMatrix 区分）
      return new MeetingEyeAdapter(http, capabilities);
    case DeviceModel.UNKNOWN:
    default:
      return new MeetingEyeAdapter(http, capabilities);
  }
};
