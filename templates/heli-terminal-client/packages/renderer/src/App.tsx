import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AppLayout } from './layout/AppLayout';
import { Dashboard } from './pages/Dashboard/Dashboard';
import { Meeting } from './pages/Meeting/Meeting';
import { Device } from './pages/Device/Device';
import { Network } from './pages/Device/Network';
import { Logs } from './pages/Logs/Logs';

export const App = () => (
  <ConfigProvider locale={zhCN}>
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/meeting" element={<Meeting />} />
          <Route path="/device" element={<Device />}>
            <Route index element={<Network />} />
            <Route path="network" element={<Network />} />
          </Route>
          <Route path="/logs" element={<Logs />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </ConfigProvider>
);