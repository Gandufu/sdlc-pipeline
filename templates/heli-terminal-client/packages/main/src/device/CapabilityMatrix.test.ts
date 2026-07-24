import { describe, it, expect } from 'vitest';
import { CapabilityMatrix, DeviceModel } from './CapabilityMatrix';

describe('CapabilityMatrix', () => {
  it('MeetingEye 500 支持 button 与 camera/active', () => {
    const caps = CapabilityMatrix.for(DeviceModel.MEETING_EYE_500);
    expect(caps.supportsButton).toBe(true);
    expect(caps.supportsCameraActive).toBe(true);
    expect(caps.supportsScreenBrightness).toBe(false);
  });

  it('MeetingBoard 支持 screen/brightness 但不支持 button', () => {
    const caps = CapabilityMatrix.for(DeviceModel.MEETING_BOARD);
    expect(caps.supportsButton).toBe(false);
    expect(caps.supportsCameraActive).toBe(true);
    expect(caps.supportsScreenBrightness).toBe(true);
  });

  it('MeetingBar A40 不支持 camera-layout', () => {
    const caps = CapabilityMatrix.for(DeviceModel.MEETING_BAR_A40);
    expect(caps.supportsCameraLayout).toBe(false);
    expect(caps.supportsCameraActive).toBe(false);
  });

  it('未知型号返回保守能力集', () => {
    const caps = CapabilityMatrix.for('Unknown-XYZ');
    expect(caps.supportsButton).toBe(false);
    expect(caps.supportsScreenBrightness).toBe(false);
  });
});
