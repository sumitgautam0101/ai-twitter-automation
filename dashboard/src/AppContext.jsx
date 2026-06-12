import React, { createContext, useContext, useState, useCallback, useEffect, useMemo } from 'react';
import { api, usePoll } from './api';
import { setNiches } from './data';

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [route, setRoute] = useState('dashboard');
  const [niche, setNiche] = useState('all');

  // ---- service status (dry-run, app mode, caps) — polled ------------------
  const { data: status, reload: reloadStatus } = usePoll('/api/status', 5000);
  const dryRun = status ? status.dry_run : true;
  const autopilot = status ? status.app_mode === 'auto' : false;

  const toggleDry = useCallback(() => {
    api.patch('/api/settings', { dry_run: !dryRun }).then(reloadStatus).catch(() => {});
  }, [dryRun, reloadStatus]);
  const toggleAutopilot = useCallback(() => {
    api
      .patch('/api/settings', { app_mode: autopilot ? 'manual' : 'auto' })
      .then(reloadStatus)
      .catch(() => {});
  }, [autopilot, reloadStatus]);

  // ---- live niche registry --------------------------------------------------
  const { data: nichesData } = usePoll('/api/niches', 60000);
  const [nichesVersion, setNichesVersion] = useState(0);
  useEffect(() => {
    if (nichesData) {
      setNiches(nichesData);
      setNichesVersion((v) => v + 1);
    }
  }, [nichesData]);

  // ---- real command queue: enqueue via API, poll until done/failed ---------
  const [commands, setCommands] = useState([]);
  const runCommand = useCallback((type, payload) => {
    const tempId = 'tmp_' + Math.random().toString(36).slice(2, 8);
    setCommands((cs) => [
      { id: tempId, type, payload: payload || {}, status: 'pending', result: null },
      ...cs,
    ].slice(0, 40));
    api
      .post('/api/commands', { type, payload: payload || {} })
      .then((row) =>
        setCommands((cs) => cs.map((c) => (c.id === tempId ? { ...c, id: row.id, status: row.status } : c)))
      )
      .catch((e) =>
        setCommands((cs) =>
          cs.map((c) => (c.id === tempId ? { ...c, status: 'failed', result: { error: e.message } } : c))
        )
      );
  }, []);

  useEffect(() => {
    const t = setInterval(() => {
      setCommands((cs) => {
        const open = cs.filter((c) => typeof c.id === 'number' && (c.status === 'pending' || c.status === 'running'));
        if (open.length) {
          api
            .get(`/api/commands?ids=${open.map((c) => c.id).join(',')}`)
            .then((rows) =>
              setCommands((cur) =>
                cur.map((c) => {
                  const row = rows.find((r) => r.id === c.id);
                  return row ? { ...c, status: row.status, result: row.result } : c;
                })
              )
            )
            .catch(() => {});
        }
        return cs;
      });
    }, 1500);
    return () => clearInterval(t);
  }, []);

  // ---- settings navigation (deep-link into the niche editor) ----------------
  const [settingsTab, setSettingsTab] = useState('general');
  const [settingsNiche, setSettingsNiche] = useState(null); // open niche on the Niches page
  const [nicheTab, setNicheTab] = useState('general');

  // Niche config now lives on the Niches page; deep-link selects it there.
  const editNiche = useCallback((n) => {
    setRoute('niches');
    setSettingsNiche(n);
    setNicheTab('general');
  }, []);

  const value = useMemo(
    () => ({
      route, setRoute,
      niche, setNiche,
      status, reloadStatus,
      dryRun, toggleDry,
      autopilot, toggleAutopilot,
      commands, runCommand,
      nichesVersion,
      settingsTab, setSettingsTab, settingsNiche, setSettingsNiche, nicheTab, setNicheTab,
      editNiche,
    }),
    [route, niche, status, reloadStatus, dryRun, toggleDry, autopilot, toggleAutopilot,
     commands, runCommand, nichesVersion, settingsTab, settingsNiche, nicheTab, editNiche]
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  return useContext(AppContext);
}
