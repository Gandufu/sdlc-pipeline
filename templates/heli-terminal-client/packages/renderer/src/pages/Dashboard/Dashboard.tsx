import { Card, Col, Row, Statistic, Spin, Alert, Space, Tag } from 'antd';
import { useDeviceQuery } from '../../hooks/useDeviceApi';

const fmtUptime = (u?: { days: number; hours: number; minutes: number }) => {
  if (!u) return '-';
  return `${u.days}d ${u.hours}h ${u.minutes}m`;
};

const StatusTag = ({ status }: { status?: string | undefined }) => {
  if (!status) return <Tag>未知</Tag>;
  const map: Record<string, string> = {
    'wake-up': 'success',
    sleeping: 'default',
    idle: 'success',
    incoming: 'warning',
    incall: 'processing',
  };
  return <Tag color={map[status] ?? 'default'}>{status}</Tag>;
};

export const Dashboard = () => {
  const version = useDeviceQuery(() => window.heli.device.getSystemVersion(), { intervalMs: 0 });
  const status = useDeviceQuery(() => window.heli.device.getSystemStatus(), { intervalMs: 5000 });
  const uptime = useDeviceQuery(() => window.heli.device.getUptime(), { intervalMs: 5000 });
  const cpu = useDeviceQuery(() => window.heli.device.getCpuInfo(), { intervalMs: 5000 });
  const memory = useDeviceQuery(() => window.heli.device.getMemoryInfo(), { intervalMs: 5000 });
  const call = useDeviceQuery(() => window.heli.device.getCallState(), { intervalMs: 5000 });

  if (version.error) {
    return <Alert type="error" message={`读取设备信息失败：${version.error.message}`} />;
  }

  return (
    <Spin spinning={version.loading}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Card title="设备信息" size="small">
          <Row gutter={16}>
            <Col span={6}><Statistic title="型号" value={version.data?.model ?? '-'} /></Col>
            <Col span={6}><Statistic title="固件" value={version.data?.firmware ?? '-'} /></Col>
            <Col span={6}><Statistic title="硬件" value={version.data?.hardware ?? '-'} /></Col>
            <Col span={6}><Statistic title="序列号" value={version.data?.serialnumber ?? '-'} /></Col>
          </Row>
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={8}><Statistic title="MAC" value={version.data?.macaddress ?? '-'} /></Col>
            <Col span={8}><Statistic title="中控版本" value={version.data?.['cc-version'] ?? '-'} /></Col>
            <Col span={8}><Statistic title="运行时间" value={fmtUptime(uptime.data)} /></Col>
          </Row>
        </Card>

        <Card title="实时状态" size="small">
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="设备状态" value={status.data?.status ?? '-'} prefix={<StatusTag status={status.data?.status} />} />
            </Col>
            <Col span={6}>
              <Statistic title="CPU 使用率" value={cpu.data?.['cpu-usage'] ?? '-'} suffix="%" />
            </Col>
            <Col span={6}>
              <Statistic title="内存使用" value={memory.data?.usage ?? '-'} suffix="%" />
            </Col>
            <Col span={6}>
              <Statistic title="通话状态" value={call.data?.['call-state'] ?? '-'} prefix={<StatusTag status={call.data?.['call-state']} />} />
            </Col>
          </Row>
        </Card>
      </Space>
    </Spin>
  );
};