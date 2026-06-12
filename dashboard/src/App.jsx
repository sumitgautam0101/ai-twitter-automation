import React from 'react';
import { AppProvider, useApp } from './AppContext';
import Sidebar from './components/Sidebar';
import TopBar, { SafetyRibbon } from './components/TopBar';
import Toasts from './components/Toasts';
import Dashboard from './pages/Dashboard';
import Niches from './pages/Niches';
import Queue from './pages/Queue';
import Schedule from './pages/Schedule';
import History from './pages/History';
import Sources from './pages/Sources';
import RawData from './pages/RawData';
import Logs from './pages/Logs';
import Settings from './pages/Settings';

const PAGES = {
  dashboard: Dashboard,
  niches: Niches,
  queue: Queue,
  schedule: Schedule,
  history: History,
  sources: Sources,
  rawdata: RawData,
  logs: Logs,
  settings: Settings,
};

function Shell() {
  const { route } = useApp();
  const Page = PAGES[route] || Dashboard;
  return (
    <div style={{ display: 'flex', height: '100vh', width: '100%', background: '#0a0c0f', color: '#e7eaef', overflow: 'hidden' }}>
      <Sidebar />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <SafetyRibbon />
        <TopBar />
        <main style={{ flex: 1, overflowY: 'auto', background: '#0a0c0f', position: 'relative' }}>
          <div className="os-page" style={{ padding: '22px 24px 60px', maxWidth: 1320, margin: '0 auto' }}>
            <Page />
          </div>
          <Toasts />
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
