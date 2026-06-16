import React, { useState } from 'react';
import { Check, ChevronsUpDown, Plus, Settings as Cog } from 'lucide-react';
import { useApp } from '../AppContext';

const inputStyle = {
  colorScheme: 'dark', background: '#0d1116', border: '1px solid #1c212a', borderRadius: 8,
  color: '#e7eaef', fontFamily: "'JetBrains Mono', monospace", fontSize: 12, padding: '9px 11px',
};

// Modal: name a new workspace, then drop into its fresh dashboard.
function CreateWorkspaceModal({ onClose }) {
  const { createWorkspace } = useApp();
  const [name, setName] = useState('');
  const [cap, setCap] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const armed = name.trim().length > 0 && !busy;

  const create = async () => {
    if (!armed) return;
    setBusy(true);
    setError(null);
    try {
      await createWorkspace(name, cap);
      onClose();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 120, background: 'rgba(5,7,10,.66)', display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(2px)' }}>
      <div onClick={(e) => e.stopPropagation()} className="lane-open" style={{ width: 420, maxWidth: '92vw', background: '#111419', border: '1px solid #232932', borderRadius: 14, padding: '22px 24px', boxShadow: '0 24px 70px rgba(0,0,0,.6)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
          <span style={{ display: 'inline-flex', width: 34, height: 34, borderRadius: 9, alignItems: 'center', justifyContent: 'center', background: 'rgba(122,162,247,.12)', color: '#7aa2f7', flexShrink: 0 }}>
            <Plus size={18} />
          </span>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700 }}>New workspace</div>
            <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 2 }}>its own niches, schedule, AI &amp; publishing — sources stay shared</div>
          </div>
        </div>

        <div style={{ marginTop: 18 }}>
          <div className="os-mono" style={{ fontSize: 10, color: '#7a828f', marginBottom: 7 }}>workspace name</div>
          <input
            autoFocus value={name} onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') create(); if (e.key === 'Escape') onClose(); }}
            placeholder="e.g. Tech account, Crypto brand…"
            style={{ ...inputStyle, width: '100%' }}
          />
        </div>

        <div style={{ marginTop: 14 }}>
          <div className="os-mono" style={{ fontSize: 10, color: '#7a828f', marginBottom: 7 }}>daily post cap <span style={{ color: '#4b5563' }}>· optional, blank = unlimited</span></div>
          <input
            type="number" min="0" value={cap} onChange={(e) => setCap(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') create(); }}
            placeholder="∞"
            style={{ ...inputStyle, width: 120, textAlign: 'center' }}
          />
        </div>

        <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 14, lineHeight: 1.5 }}>
          You can enroll this workspace's X credentials later in Settings → Credentials. Until then it stays in dry-run (no live posts).
        </div>

        {error && <div className="os-mono" style={{ fontSize: 10.5, color: '#f5455c', marginTop: 12 }}>{error}</div>}

        <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
          <button onClick={onClose} className="hover-border-text" style={{ flex: 1, border: '1px solid #232932', background: 'transparent', color: '#9aa3af', cursor: 'pointer', fontSize: 12.5, fontWeight: 600, padding: '10px', borderRadius: 9 }}>Cancel</button>
          <button onClick={create} disabled={!armed} style={{ flex: 1.4, border: 'none', cursor: armed ? 'pointer' : 'default', fontSize: 12.5, fontWeight: 700, padding: '10px', borderRadius: 9, background: armed ? '#3ecf8e' : '#1c222b', color: armed ? '#0a0c0f' : '#7a828f' }}>
            {busy ? 'Creating…' : 'Create workspace'}
          </button>
        </div>
      </div>
    </div>
  );
}

// Bottom-of-sidebar workspace switcher: shows the current workspace, opens a
// popover to pick another or create a new one.
export default function WorkspaceMenu() {
  const { accounts, account, setAccount, currentWorkspace, setRoute, setSettingsTab } = useApp();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  const startCreate = () => { setOpen(false); setCreating(true); };
  const manage = () => { setOpen(false); setSettingsTab && setSettingsTab('workspaces'); setRoute('settings'); };
  const pick = (id) => { setAccount(id); setOpen(false); };

  const hasNone = !accounts || accounts.length === 0;
  const label = currentWorkspace ? currentWorkspace.label : (hasNone ? 'No workspace' : 'Select workspace');

  return (
    <div style={{ position: 'relative', padding: '10px 12px', borderTop: '1px solid #1a1f27' }}>
      <div className="os-mono" style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: '.5px', color: '#4b5563', padding: '0 2px 6px' }}>WORKSPACE</div>

      {hasNone ? (
        <button
          onClick={startCreate}
          className="hover-bright"
          style={{
            display: 'flex', alignItems: 'center', gap: 8, width: '100%', cursor: 'pointer',
            fontSize: 12, fontWeight: 700, padding: '9px 11px', borderRadius: 9,
            border: '1px solid rgba(62,207,142,.4)', background: 'rgba(62,207,142,.12)', color: '#3ecf8e',
          }}
        >
          <Plus size={14} /> Create workspace
        </button>
      ) : (
        <button
          onClick={() => setOpen((v) => !v)}
          className="hover-border-text"
          title="Switch workspace"
          style={{
            display: 'flex', alignItems: 'center', gap: 9, width: '100%', cursor: 'pointer',
            fontSize: 12.5, fontWeight: 600, padding: '9px 11px', borderRadius: 9,
            border: `1px solid ${open ? '#2f3947' : '#1c222b'}`, background: open ? '#141922' : '#0d1116', color: '#e7eaef',
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, background: '#7aa2f7' }} />
          <span style={{ flex: 1, textAlign: 'left', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>@{label}</span>
          <ChevronsUpDown size={13} style={{ flexShrink: 0, color: '#7a828f' }} />
        </button>
      )}

      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 60 }} />
          <div
            className="lane-open"
            style={{
              position: 'absolute', left: 12, right: 12, bottom: 'calc(100% - 2px)', zIndex: 61,
              background: '#111419', border: '1px solid #232932', borderRadius: 12, padding: 6,
              boxShadow: '0 -18px 50px rgba(0,0,0,.55)', maxHeight: 320, overflowY: 'auto',
            }}
          >
            {accounts.map((a) => {
              const isCurrent = a.id === account;
              return (
                <button
                  key={a.id}
                  onClick={() => pick(a.id)}
                  className="hover-tab"
                  style={{
                    display: 'flex', alignItems: 'center', gap: 9, width: '100%', textAlign: 'left',
                    border: 'none', background: isCurrent ? 'rgba(122,162,247,.1)' : 'transparent',
                    cursor: 'pointer', padding: '9px 10px', borderRadius: 8,
                  }}
                >
                  <span style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, background: isCurrent ? '#7aa2f7' : '#3b414b' }} />
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: '#e7eaef', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>@{a.label}</span>
                    <span className="os-mono" style={{ display: 'block', fontSize: 9, color: '#5b6470', marginTop: 1 }}>
                      {a.niche_count} niche{a.niche_count === 1 ? '' : 's'} · {a.published_today} today
                    </span>
                  </span>
                  {isCurrent && <Check size={13} strokeWidth={3} style={{ flexShrink: 0, color: '#7aa2f7' }} />}
                </button>
              );
            })}

            <div style={{ height: 1, background: '#1a1f27', margin: '5px 4px' }} />

            <button
              onClick={startCreate}
              className="hover-tab"
              style={{ display: 'flex', alignItems: 'center', gap: 9, width: '100%', textAlign: 'left', border: 'none', background: 'transparent', cursor: 'pointer', padding: '9px 10px', borderRadius: 8, color: '#3ecf8e', fontWeight: 600, fontSize: 12.5 }}
            >
              <Plus size={14} style={{ flexShrink: 0 }} /> Create workspace
            </button>
            <button
              onClick={manage}
              className="hover-tab"
              style={{ display: 'flex', alignItems: 'center', gap: 9, width: '100%', textAlign: 'left', border: 'none', background: 'transparent', cursor: 'pointer', padding: '9px 10px', borderRadius: 8, color: '#8b93a0', fontWeight: 500, fontSize: 12.5 }}
            >
              <Cog size={13} style={{ flexShrink: 0 }} /> Manage workspaces…
            </button>
          </div>
        </>
      )}

      {creating && <CreateWorkspaceModal onClose={() => setCreating(false)} />}
    </div>
  );
}
