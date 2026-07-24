import { Card, Table, Tag, Button, Input, Space, Alert, Tabs } from 'antd';
import { useState } from 'react';
import { useDeviceQuery } from '../../hooks/useDeviceApi';

export const Network = () => {
  const info = useDeviceQuery(() => window.heli.device.getNetworkInfo(), { intervalMs: 0 });
  const [ip, setIp] = useState('8.8.8.8');
  const [diagResult, setDiagResult] = useState<string>('');
  const [diagLoading, setDiagLoading] = useState(false);

  const runDiag = async (action: 'ping' | 'traceroute') => {
    setDiagLoading(true);
    try {
      const r = await window.heli.device.networkDiagnostics(action, ip);
      setDiagResult(r.result);
    } catch (err: any) {
      setDiagResult(`错误：${err?.message ?? String(err)}`);
    } finally {
      setDiagLoading(false);
    }
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Alert
        type="info"
        showIcon
        message="设备 API 不支持修改网络配置（写入）"
        description="当前仅展示读取与诊断。如需修改 IP/网关/DNS，请联系管理员通过设备本地 UI 或厂商确认其他接口。"
      />

      <Card title="网络信息" size="small">
        {info.error && <Alert type="error" message={info.error.message} />}
        <Table
          rowKey={(r) => `${r['port-type']}-${r.mode}`}
          dataSource={info.data?.['network-list'] ?? []}
          loading={info.loading}
          pagination={false}
          size="small"
          columns={[
            { title: '获取方式', dataIndex: 'type', render: (v) => v === 0 ? <Tag>DHCP</Tag> : <Tag color="blue">Static</Tag> },
            { title: '端口', dataIndex: 'port-type', render: (v) => ['有线1','有线2','无线','AP'][v] ?? v },
            { title: 'IP', dataIndex: 'ip' },
            { title: '掩码', dataIndex: 'mask' },
            { title: '网关', dataIndex: 'gateway' },
            { title: '主 DNS', dataIndex: 'primary-dns' },
            { title: '备 DNS', dataIndex: 'second-dns' },
          ]}
        />
      </Card>

      <Card title="网络诊断" size="small">
        <Space style={{ marginBottom: 12 }}>
          <Input value={ip} onChange={(e) => setIp(e.target.value)} style={{ width: 200 }} placeholder="目标 IP / 域名" />
        </Space>
        <Tabs
          items={[
            {
              key: 'ping',
              label: 'Ping',
              children: (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button onClick={() => runDiag('ping')} loading={diagLoading}>开始 Ping</Button>
                  <pre style={{ background: '#f5f5f5', padding: 12, minHeight: 120 }}>{diagResult || '点击开始 Ping'}</pre>
                </Space>
              ),
            },
            {
              key: 'traceroute',
              label: 'Traceroute',
              children: (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button onClick={() => runDiag('traceroute')} loading={diagLoading}>开始 Traceroute</Button>
                  <pre style={{ background: '#f5f5f5', padding: 12, minHeight: 120 }}>{diagResult || '点击开始 Traceroute'}</pre>
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  );
};