import { Layout, Menu, Typography } from 'antd';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useAuthStore } from '../store/auth.store';
import { LoginDialog } from '../pages/Auth/LoginDialog';
import { useEffect, useState } from 'react';

const { Header, Sider, Content } = Layout;

const items = [
  { key: '/dashboard', label: <Link to="/dashboard">设备总览</Link> },
  { key: '/meeting', label: <Link to="/meeting">会议</Link> },
  { key: '/device', label: <Link to="/device">设备管理</Link> },
  { key: '/logs', label: <Link to="/logs">日志</Link> },
];

export const AppLayout = () => {
  const authenticated = useAuthStore((s) => s.authenticated);
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);
  const [authChecked, setAuthChecked] = useState(false);
  const location = useLocation();

  // 启动时同步一次主进程鉴权状态
  useEffect(() => {
    if (!window.heli) {
      // preload 未挂载 contextBridge（sandbox/ESM 兼容问题或打包异常）
      console.error('window.heli is undefined — preload contextBridge 未挂载');
      setAuthenticated(false);
      setAuthChecked(true);
      return;
    }
    window.heli.auth
      .getStatus()
      .then((s) => setAuthenticated(s.authenticated))
      .catch(() => setAuthenticated(false))
      .finally(() => setAuthChecked(true));
  }, [setAuthenticated]);

  // preload 未挂载时直接显示明确错误，避免白屏
  if (!window.heli) {
    return (
      <div style={{ padding: 32, fontFamily: 'monospace', color: '#a00' }}>
        <h2>preload 加载失败</h2>
        <p>
          <code>window.heli</code> 未定义。contextBridge 未挂载，请检查：
        </p>
        <ul>
          <li>preload 是否在 sandbox 沙箱下成功加载（sandbox:true 限制 ESM 外部 import）</li>
          <li>主进程是否能正常启动（确认 <code>app.asar</code> 内 <code>dist/preload.js</code> 存在）</li>
        </ul>
      </div>
    );
  }

  // modal 完全由 authenticated 驱动：未登录 → 显示且不可关闭；登录后自动关闭
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', color: 'white' }}>
        <Typography.Title level={4} style={{ color: 'white', margin: 0 }}>
          Heli Conference Terminal
        </Typography.Title>
        <span style={{ marginLeft: 'auto', fontSize: 12 }}>
          {authenticated ? '已连接' : '未连接'}
        </span>
      </Header>
      <Layout>
        <Sider width={200} theme="light">
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            items={items}
            style={{ height: '100%' }}
          />
        </Sider>
        <Content style={{ padding: 24 }}>
          <Outlet />
        </Content>
      </Layout>
      <LoginDialog open={authChecked && !authenticated} closable={false} />
    </Layout>
  );
};