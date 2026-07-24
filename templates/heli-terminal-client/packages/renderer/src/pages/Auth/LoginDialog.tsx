import { useState } from 'react';
import { Modal, Input, Form, Button, message } from 'antd';
import { useAuthStore } from '../../store/auth.store';

interface Props {
  open: boolean;
  closable?: boolean;
}

export const LoginDialog = ({ open, closable = false }: Props) => {
  const [loading, setLoading] = useState(false);
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);

  const handleOk = async (values: { password: string }) => {
    setLoading(true);
    try {
      const r: any = await window.heli.auth.login(values.password);
      // main 进程在 safeHandle 包装下，错误时返回 {code, message} 而非 throw
      if (r && r.authenticated) {
        setAuthenticated(true);
        message.success('登录成功');
      } else if (r && r.code) {
        const map: Record<string, string> = {
          '10007': '密码错误',
          '10009': '鉴权失败',
          '10010': '请求过于频繁',
        };
        message.error(`登录失败：${map[r.code] ?? r.message ?? '未知错误'} (${r.code})`);
      } else {
        message.error('登录失败：未知错误');
      }
    } catch (err: any) {
      message.error(`登录失败：${err?.message ?? '未知错误'}`);
    } finally {
      setLoading(false);
    }
  };

  // closable=false 时不传 onCancel — Modal 内部对 closable=false 的默认行为
  // 是不渲染右上角 X 与不响应 ESC，不调用 onCancel。
  const extraProps = closable ? {} : { keyboard: false };

  return (
    <Modal
      title="设备登录"
      open={open}
      footer={null}
      maskClosable={false}
      closable={closable}
      {...extraProps}
    >
      <Form layout="vertical" onFinish={handleOk}>
        <Form.Item
          label="设备 admin 密码"
          name="password"
          rules={[{ required: true, message: '请输入密码' }]}
        >
          <Input.Password autoFocus />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading} block>
            登录
          </Button>
        </Form.Item>
      </Form>
    </Modal>
  );
};
