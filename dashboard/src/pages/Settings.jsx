import React, { useState } from 'react';
import { AlertTriangle, Check, Database, Download, Play, Sparkles, Trash2 } from 'lucide-react';
import { useApp } from '../AppContext';
import { QUICK_ACTIONS } from '../data';
import { api, usePoll } from '../api';
import { Card, Toggle } from '../components/common';

const SETTINGS_TABS = [
  ['general', 'General'],
  ['actions', 'Actions'],
  ['ai', 'AI providers'],
  ['credentials', 'Credentials'],
  ['danger', 'Danger zone'],
];

const inputStyle = {
  colorScheme: 'dark', background: '#0d1116', border: '1px solid #1c212a', borderRadius: 8,
  color: '#e7eaef', fontFamily: "'JetBrains Mono', monospace", fontSize: 12, padding: '8px 11px',
};

const numStyle = { ...inputStyle, width: 90, textAlign: 'center', fontWeight: 600 };

const ACTION_ICON = { fetch_sources: Download, generate_posts: Sparkles, run_slots: Play };

// ---------------------------------------------------------------------------
// AI providers
// ---------------------------------------------------------------------------

const TEXT_PROVIDERS = [
  ['claude', 'Claude'],
  ['chatgpt', 'ChatGPT'],
  ['local', 'Local'],
  ['template', 'Template (offline)'],
];
// which credential a text provider authenticates with (null = keyless)
const TEXT_KEY_ENV = { claude: 'ANTHROPIC_API_KEY', chatgpt: 'OPENAI_API_KEY' };
// sensible default model + endpoint per provider — applied when the provider is
// switched, and shown as the placeholder.
const PROVIDER_DEFAULTS = {
  claude: { model: 'anthropic/claude-sonnet-4-6', endpoint: '' },
  chatgpt: { model: 'gpt-4o-mini', endpoint: '' },
  local: { model: 'ollama/gemma3:4b', endpoint: 'http://localhost:11434' },
  template: { model: '', endpoint: '' },
};
const MODEL_PLACEHOLDER = {
  claude: PROVIDER_DEFAULTS.claude.model,
  chatgpt: PROVIDER_DEFAULTS.chatgpt.model,
  local: PROVIDER_DEFAULTS.local.model,
};

function kv(label, node, hint) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
      <span style={{ minWidth: 0 }}>
        <span className="os-mono" style={{ fontSize: 11, color: '#7a828f' }}>{label}</span>
        {hint && <span className="os-mono" style={{ fontSize: 9, color: '#f5a524', marginLeft: 7 }}>{hint}</span>}
      </span>
      {node}
    </div>
  );
}

// Compact inline secret field — writes to /api/credentials, never reads back.
function AiKeyField({ env, set, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const save = () => {
    if (!value.trim() || busy) return;
    setBusy(true);
    api.post('/api/credentials', { key: env, value: value.trim() })
      .then(() => { setValue(''); setEditing(false); onSaved && onSaved(); })
      .catch((e) => alert(e.message)).finally(() => setBusy(false));
  };
  return kv('api key', editing ? (
    <span style={{ display: 'flex', gap: 6, flex: 1, marginLeft: 16 }}>
      <input
        autoFocus type="password" value={value} onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false); }}
        placeholder={`${env} · write-only`} style={{ ...inputStyle, flex: 1 }}
      />
      <button onClick={save} style={{ border: 'none', background: '#3ecf8e', color: '#0a0c0f', cursor: 'pointer', fontSize: 11, fontWeight: 700, padding: '0 12px', borderRadius: 7 }}>
        {busy ? '…' : 'save'}
      </button>
      <button onClick={() => setEditing(false)} style={{ border: '1px solid #232932', background: 'transparent', color: '#9aa3af', cursor: 'pointer', fontSize: 11, padding: '0 10px', borderRadius: 7 }}>✕</button>
    </span>
  ) : (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
      <span className="os-mono" style={{ fontSize: 10.5, fontWeight: 600, color: set ? '#3ecf8e' : '#f5a524' }}>
        {set ? 'key set ✓' : 'not set'}
      </span>
      <button
        onClick={() => setEditing(true)}
        className="hover-bright"
        style={{
          cursor: 'pointer', fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fontWeight: 600,
          padding: '5px 11px', borderRadius: 6,
          border: `1px solid ${set ? '#232932' : 'rgba(62,207,142,.35)'}`,
          background: set ? 'transparent' : 'rgba(62,207,142,.1)', color: set ? '#9aa3af' : '#3ecf8e',
        }}
      >
        {set ? 'replace' : 'set key'}
      </button>
    </span>
  ));
}

function AiProvidersTab() {
  const { data, reload } = usePoll('/api/ai', 0);
  const [cfg, setCfg] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  React.useEffect(() => { if (data) { setCfg(data); setDirty(false); } }, [data]);

  const set = (section, key, value) => {
    setCfg((c) => ({ ...c, [section]: { ...c[section], [key]: value } }));
    setDirty(true);
  };

  // Switching provider applies that provider's default model + endpoint so the
  // fields are sensible out of the box (overwrite-able afterwards).
  const changeProvider = (provider) => {
    const d = PROVIDER_DEFAULTS[provider] || { model: '', endpoint: '' };
    setCfg((c) => ({ ...c, text: { ...c.text, provider, model: d.model, endpoint: d.endpoint } }));
    setDirty(true);
  };

  const text = (cfg && cfg.text) || {};
  const keyStatus = (cfg && cfg.key_status) || {};

  const textKeyEnv = TEXT_KEY_ENV[text.provider];
  const localMissingEndpoint = text.provider === 'local' && !((text.endpoint || '').trim());
  const blocked = localMissingEndpoint;

  const save = () => {
    if (!cfg || saving || !dirty || blocked) return;
    setSaving(true);
    api.put('/api/ai', { text: cfg.text })
      .then((saved) => { setCfg(saved); setDirty(false); reload(); })
      .catch((e) => alert(e.message)).finally(() => setSaving(false));
  };

  return (
    <Card style={{ padding: '16px 18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>AI providers</span>
        <span className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>global · applies to every niche</span>
        <button
          onClick={save}
          className="run-btn"
          style={{
            marginLeft: 'auto', border: 'none', cursor: dirty && !blocked ? 'pointer' : 'default', fontSize: 12, fontWeight: 700,
            padding: '7px 14px', borderRadius: 8,
            background: dirty && !blocked ? '#3ecf8e' : '#1c222b', color: dirty && !blocked ? '#0a0c0f' : '#7a828f',
          }}
        >
          {saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}
        </button>
      </div>

      {!cfg ? (
        <span className="os-mono" style={{ fontSize: 11, color: '#5b6470' }}>loading…</span>
      ) : (
        <div style={{ maxWidth: 460 }}>
          {/* ---- text ---- */}
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 12 }}>Text generation</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
              {kv('provider', (
                <select value={text.provider || 'local'} onChange={(e) => changeProvider(e.target.value)} style={{ ...inputStyle, padding: '6px 9px', width: 200 }}>
                  {TEXT_PROVIDERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              ))}
              {text.provider !== 'template' && (
                <>
                  {kv('model', (
                    <input value={text.model || ''} onChange={(e) => set('text', 'model', e.target.value)} placeholder={MODEL_PLACEHOLDER[text.provider] || 'model id'} style={{ ...inputStyle, width: 200 }} />
                  ))}
                  {kv('endpoint', (
                    <input value={text.endpoint || ''} onChange={(e) => set('text', 'endpoint', e.target.value)} placeholder={text.provider === 'local' ? 'http://localhost:11434' : 'optional · custom gateway'} style={{ ...inputStyle, width: 200, borderColor: localMissingEndpoint ? 'rgba(245,69,92,.5)' : '#1c212a' }} />
                  ), text.provider === 'local' ? 'required' : null)}
                  {textKeyEnv && (
                    <AiKeyField env={textKeyEnv} set={!!keyStatus[textKeyEnv]} onSaved={reload} />
                  )}
                  {kv('temperature', (
                    <input type="number" min="0" max="2" step="0.05" value={text.temperature != null ? text.temperature : 0.7} onChange={(e) => set('text', 'temperature', +e.target.value)} style={numStyle} />
                  ))}
                </>
              )}
            </div>
            {text.provider === 'local' && (
              <div className="os-mono" style={{ fontSize: 9.5, color: '#5b6470', marginTop: 11, lineHeight: 1.5 }}>
                point at an Ollama or any OpenAI-compatible server — no key needed.
              </div>
            )}
            {text.provider === 'template' && (
              <div className="os-mono" style={{ fontSize: 9.5, color: '#5b6470', marginTop: 11, lineHeight: 1.5 }}>
                deterministic offline writer — no model, no key, no network.
              </div>
            )}
            <div className="os-mono" style={{ fontSize: 9.5, color: '#5b6470', marginTop: 16, lineHeight: 1.5 }}>
              images are set per-niche (General tab → Image source: Unsplash, Content, or None).
            </div>
          </div>
        </div>
      )}

      {localMissingEndpoint && (
        <div className="os-mono" style={{ fontSize: 10.5, color: '#f5455c', marginTop: 14 }}>
          the local provider needs an endpoint URL before it can be saved.
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Reset modal + Danger zone
// ---------------------------------------------------------------------------

function ResetModal({ onClose, onDone }) {
  const [clearCreds, setClearCreds] = useState(false);
  const [phrase, setPhrase] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const armed = phrase.trim().toUpperCase() === 'RESET';

  const run = async () => {
    if (!armed || busy) return;
    setBusy(true);
    try {
      const r = await api.post('/api/reset', { confirm: true, clear_credentials: clearCreds });
      const total = Object.values(r.deleted || {}).reduce((a, b) => a + b, 0);
      setDone(total);
      setTimeout(onDone, 1400);
    } catch (e) {
      alert(e.message);
      setBusy(false);
    }
  };

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(5,7,10,.66)', display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(2px)' }}>
      <div onClick={(e) => e.stopPropagation()} className="lane-open" style={{ width: 440, maxWidth: '92vw', background: '#111419', border: '1px solid #3a232b', borderRadius: 14, padding: '22px 24px', boxShadow: '0 24px 70px rgba(0,0,0,.6)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
          <span style={{ display: 'inline-flex', width: 34, height: 34, borderRadius: 9, alignItems: 'center', justifyContent: 'center', background: 'rgba(245,69,92,.12)', color: '#f5455c', flexShrink: 0 }}>
            <AlertTriangle size={18} />
          </span>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700 }}>Reset database</div>
            <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 2 }}>clears all content, drafts, history &amp; logs</div>
          </div>
        </div>

        {done == null ? (
          <>
            <div style={{ marginTop: 18, fontSize: 12.5, color: '#aeb6c0', lineHeight: 1.6 }}>
              This wipes every fetched item, generated post, publish record, log line and source
              fetch status. Your <strong style={{ color: '#cfd6df' }}>niche config files are kept</strong>. This cannot be undone.
            </div>

            <label
              onClick={() => setClearCreds((v) => !v)}
              style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 16, padding: '11px 13px', background: '#0d1116', border: `1px solid ${clearCreds ? 'rgba(245,69,92,.4)' : '#1c212a'}`, borderRadius: 10, cursor: 'pointer' }}
            >
              <span style={{ display: 'inline-flex', width: 18, height: 18, borderRadius: 5, alignItems: 'center', justifyContent: 'center', flexShrink: 0, border: `1.5px solid ${clearCreds ? '#f5455c' : '#3b414b'}`, background: clearCreds ? '#f5455c' : 'transparent', color: '#0a0c0f' }}>
                {clearCreds && <Check size={13} strokeWidth={3} />}
              </span>
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 600, color: '#e7eaef' }}>Also clear credentials</div>
                <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 2 }}>API keys &amp; X account</div>
              </div>
            </label>

            <div style={{ marginTop: 16 }}>
              <div className="os-mono" style={{ fontSize: 10, color: '#7a828f', marginBottom: 7 }}>
                type <span style={{ color: '#f5455c', fontWeight: 700 }}>RESET</span> to confirm
              </div>
              <input
                autoFocus value={phrase} onChange={(e) => setPhrase(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') run(); }}
                placeholder="RESET"
                style={{ ...inputStyle, width: '100%' }}
              />
            </div>

            <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
              <button onClick={onClose} className="hover-border-text" style={{ flex: 1, border: '1px solid #232932', background: 'transparent', color: '#9aa3af', cursor: 'pointer', fontSize: 12.5, fontWeight: 600, padding: '10px', borderRadius: 9 }}>Cancel</button>
              <button onClick={run} disabled={!armed || busy} style={{ flex: 1.4, border: 'none', cursor: armed && !busy ? 'pointer' : 'default', fontSize: 12.5, fontWeight: 700, padding: '10px', borderRadius: 9, background: armed && !busy ? '#f5455c' : '#2a1c20', color: armed && !busy ? '#fff' : '#7a5560' }}>
                {busy ? 'Resetting…' : clearCreds ? 'Reset everything' : 'Reset database'}
              </button>
            </div>
          </>
        ) : (
          <div style={{ marginTop: 20, display: 'flex', alignItems: 'center', gap: 10, color: '#3ecf8e' }}>
            <Check size={18} strokeWidth={3} />
            <span style={{ fontSize: 13, fontWeight: 600 }}>Cleared {done} row{done === 1 ? '' : 's'}. Reloading…</span>
          </div>
        )}
      </div>
    </div>
  );
}

function DangerTab() {
  const [resetting, setResetting] = useState(false);
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 11 }}>
        <span style={{ fontWeight: 600, fontSize: 13, color: '#f5455c' }}>Danger zone</span>
        <span className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>irreversible · niche config files are preserved</span>
      </div>
      <Card style={{ padding: '16px 18px', border: '1px solid #2a1c20', display: 'flex', alignItems: 'center', gap: 14 }}>
        <span style={{ display: 'inline-flex', width: 36, height: 36, borderRadius: 9, alignItems: 'center', justifyContent: 'center', background: 'rgba(245,69,92,.1)', color: '#f5455c', flexShrink: 0 }}>
          <Database size={18} />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Reset database</div>
          <div className="os-mono" style={{ fontSize: 10.5, color: '#5b6470', marginTop: 3, lineHeight: 1.4 }}>
            wipe all content, drafts, history &amp; logs — optionally clear stored credentials too
          </div>
        </div>
        <button
          onClick={() => setResetting(true)}
          className="hover-danger"
          style={{ flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 7, border: '1px solid rgba(245,69,92,.4)', background: 'rgba(245,69,92,.08)', color: '#f5455c', cursor: 'pointer', fontSize: 12, fontWeight: 700, padding: '9px 15px', borderRadius: 8 }}
        >
          <Trash2 size={14} /> Reset…
        </button>
      </Card>
      {resetting && <ResetModal onClose={() => setResetting(false)} onDone={() => window.location.reload()} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// General (service controls + daily cap)
// ---------------------------------------------------------------------------

function DailyCapCard() {
  const { status, reloadStatus } = useApp();
  const current = status ? status.global_daily_cap : null;
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  React.useEffect(() => { if (current != null) setValue(String(current)); }, [current]);

  const n = parseInt(value, 10);
  const dirty = current != null && Number.isFinite(n) && n >= 0 && n !== current;

  const save = () => {
    if (!dirty || busy) return;
    setBusy(true);
    api.patch('/api/settings', { global_daily_cap: n })
      .then(() => reloadStatus()).catch((e) => alert(e.message)).finally(() => setBusy(false));
  };

  return (
    <Card style={{ padding: '16px 18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>Posting limit</span>
        <span className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>GLOBAL_DAILY_CAP · hard ceiling across every niche</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Max posts per day</div>
          <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 2 }}>
            published today: <span style={{ color: '#3ecf8e' }}>{status ? status.published_today : '—'}</span> / {current ?? '—'}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <input
            type="number" min="0" value={value} onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') save(); }}
            style={numStyle}
          />
          <button
            onClick={save}
            style={{
              border: 'none', cursor: dirty && !busy ? 'pointer' : 'default', fontSize: 12, fontWeight: 700,
              padding: '8px 16px', borderRadius: 8,
              background: dirty && !busy ? '#3ecf8e' : '#1c222b', color: dirty && !busy ? '#0a0c0f' : '#7a828f',
            }}
          >
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Card>
  );
}

function FetchCadenceCard() {
  const { status, reloadStatus } = useApp();
  const current = status ? status.autopilot_fetch_minutes : null;
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  React.useEffect(() => { if (current != null) setValue(String(current)); }, [current]);

  const n = parseInt(value, 10);
  const dirty = current != null && Number.isFinite(n) && n >= 0 && n !== current;

  const save = () => {
    if (!dirty || busy) return;
    setBusy(true);
    api.patch('/api/settings', { autopilot_fetch_minutes: n })
      .then(() => reloadStatus()).catch((e) => alert(e.message)).finally(() => setBusy(false));
  };

  return (
    <Card style={{ padding: '16px 18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>Autopilot fetch cadence</span>
        <span className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>AUTOPILOT_FETCH_MINUTES · refresh the draft queue inside the posting window</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Refresh every (minutes)</div>
          <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 2 }}>
            fetch → generate from a warm-up before the first slot to this long before the last · 0 disables
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <input
            type="number" min="0" value={value} onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') save(); }}
            style={numStyle}
          />
          <button
            onClick={save}
            style={{
              border: 'none', cursor: dirty && !busy ? 'pointer' : 'default', fontSize: 12, fontWeight: 700,
              padding: '8px 16px', borderRadius: 8,
              background: dirty && !busy ? '#3ecf8e' : '#1c222b', color: dirty && !busy ? '#0a0c0f' : '#7a828f',
            }}
          >
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Card>
  );
}

function GeneralTab() {
  const { dryRun, toggleDry, autopilot, toggleAutopilot } = useApp();
  const row = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '13px 0', borderBottom: '1px solid #1a1f27' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Card style={{ padding: '16px 18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Service controls</span>
          <span className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>app-level · saved to the service, applies without restart</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div style={row}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>Dry-run</div>
              <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 2 }}>simulate publishing — no live posts to X</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
              <span className="os-mono" style={{ fontSize: 11, fontWeight: 600, color: dryRun ? '#f5a524' : '#3ecf8e' }}>
                {dryRun ? 'ON · simulated' : 'OFF · live'}
              </span>
              <Toggle on={dryRun} onClick={toggleDry} onColor="#f5a524" />
            </div>
          </div>
          <div style={{ ...row, borderBottom: 'none', paddingBottom: 4 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>Autopilot</div>
              <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 2 }}>unattended: timed fetch+generate, then publish due slots (app_mode=auto)</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
              <span className="os-mono" style={{ fontSize: 11, fontWeight: 600, color: autopilot ? '#3ecf8e' : '#9aa3af' }}>
                {autopilot ? 'ON · unattended' : 'OFF · manual'}
              </span>
              <Toggle on={autopilot} onClick={toggleAutopilot} />
            </div>
          </div>
        </div>
      </Card>

      <FetchCadenceCard />
      <DailyCapCard />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function ActionsTab() {
  const { runCommand, commands } = useApp();
  const last = commands[0];
  return (
    <Card style={{ padding: '16px 18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>Service actions</span>
        <span className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>dispatched to the background worker · watch progress in the toast / logs</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {QUICK_ACTIONS.map(([type, label, desc], i) => {
          const Icon = ACTION_ICON[type] || Play;
          return (
            <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 13, padding: '13px 0', borderBottom: i < QUICK_ACTIONS.length - 1 ? '1px solid #1a1f27' : 'none' }}>
              <span style={{ display: 'inline-flex', width: 34, height: 34, borderRadius: 9, flexShrink: 0, alignItems: 'center', justifyContent: 'center', background: 'rgba(62,207,142,.1)', color: '#3ecf8e' }}>
                <Icon size={16} />
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{label}</div>
                <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 2 }}>{desc}</div>
              </div>
              <button
                onClick={() => runCommand(type)}
                className="run-btn"
                style={{
                  flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 7, border: 'none', background: '#3ecf8e',
                  color: '#0a0c0f', cursor: 'pointer', fontSize: 12, fontWeight: 700, padding: '8px 15px', borderRadius: 8,
                }}
              >
                <Icon size={13} /> Run
              </button>
            </div>
          );
        })}
      </div>
      {last && (
        <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 13 }}>
          last dispatched: <span style={{ color: '#9aa3af' }}>{last.type}</span> · {last.status}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Credentials
// ---------------------------------------------------------------------------

function EnvKeyRow({ name, set, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const save = () => {
    if (!value.trim() || busy) return;
    setBusy(true);
    api
      .post('/api/credentials', { key: name, value: value.trim() })
      .then(() => { setValue(''); setEditing(false); onSaved(); })
      .catch((e) => alert(e.message))
      .finally(() => setBusy(false));
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '8px 11px', background: '#0d1116', border: '1px solid #1c212a', borderRadius: 8 }}>
      <span className="os-mono" style={{ fontSize: 12, color: '#cfd6df', minWidth: 190 }}>{name}</span>
      {!editing ? (
        <>
          <span className="os-mono" style={{ fontSize: 12, color: set ? '#9aa3af' : '#5b6470', letterSpacing: 1 }}>
            {set ? '••••••••••••' : 'not set'}
          </span>
          <button
            onClick={() => setEditing(true)}
            className="hover-bright"
            style={{
              marginLeft: 'auto', cursor: 'pointer', fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10, fontWeight: 600, padding: '5px 11px', borderRadius: 6,
              border: `1px solid ${set ? '#232932' : 'rgba(62,207,142,.35)'}`,
              background: set ? 'transparent' : 'rgba(62,207,142,.1)', color: set ? '#9aa3af' : '#3ecf8e',
            }}
          >
            {set ? 'replace' : 'set'}
          </button>
        </>
      ) : (
        <>
          <input
            autoFocus type="password" value={value} onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false); }}
            placeholder="paste secret · write-only"
            style={{ ...inputStyle, flex: 1 }}
          />
          <button
            onClick={save}
            style={{ border: 'none', background: '#3ecf8e', color: '#0a0c0f', cursor: 'pointer', fontSize: 11, fontWeight: 700, padding: '7px 13px', borderRadius: 7 }}
          >
            {busy ? 'saving…' : 'save'}
          </button>
          <button
            onClick={() => setEditing(false)}
            style={{ border: '1px solid #232932', background: 'transparent', color: '#9aa3af', cursor: 'pointer', fontSize: 11, padding: '7px 11px', borderRadius: 7 }}
          >
            cancel
          </button>
        </>
      )}
    </div>
  );
}

const X_FIELDS = ['api_key', 'api_secret', 'access_token', 'access_token_secret'];

function XAccountCard({ group, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ label: 'default', api_key: '', api_secret: '', access_token: '', access_token_secret: '' });
  const [busy, setBusy] = useState(false);
  const configured = group.accounts && group.accounts.length > 0;

  const save = () => {
    if (busy || X_FIELDS.some((f) => !form[f].trim())) return;
    setBusy(true);
    api
      .post('/api/credentials/x', form)
      .then(() => { setEditing(false); setForm({ ...form, api_key: '', api_secret: '', access_token: '', access_token_secret: '' }); onSaved(); })
      .catch((e) => alert(e.message))
      .finally(() => setBusy(false));
  };

  return (
    <Card style={{ padding: '14px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 11 }}>
        <span style={{ width: 9, height: 9, borderRadius: 2, flexShrink: 0, background: '#7aa2f7' }} />
        <span style={{ fontSize: 13, fontWeight: 700, color: '#e7eaef' }}>Twitter / X</span>
        {configured && (
          <span className="os-mono" style={{ fontSize: 10, color: '#9aa3af' }}>
            {group.accounts.join(' · ')}
          </span>
        )}
        <span className="os-mono" style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 600, color: configured ? '#3ecf8e' : '#f5a524' }}>
          {configured ? 'configured · encrypted' : 'not enrolled'}
        </span>
      </div>
      {!editing ? (
        <button
          onClick={() => setEditing(true)}
          className="hover-bright"
          style={{
            cursor: 'pointer', fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fontWeight: 600,
            padding: '6px 12px', borderRadius: 6,
            border: `1px solid ${configured ? '#232932' : 'rgba(62,207,142,.35)'}`,
            background: configured ? 'transparent' : 'rgba(62,207,142,.1)', color: configured ? '#9aa3af' : '#3ecf8e',
          }}
        >
          {configured ? 'replace credentials' : 'enroll account'}
        </button>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
            <span className="os-mono" style={{ fontSize: 11, color: '#7a828f', minWidth: 190 }}>account label</span>
            <input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} style={{ ...inputStyle, flex: 1 }} />
          </div>
          {X_FIELDS.map((f) => (
            <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
              <span className="os-mono" style={{ fontSize: 11, color: '#7a828f', minWidth: 190 }}>{f}</span>
              <input
                type="password" value={form[f]} onChange={(e) => setForm({ ...form, [f]: e.target.value })}
                placeholder="write-only" style={{ ...inputStyle, flex: 1 }}
              />
            </div>
          ))}
          <div style={{ display: 'flex', gap: 7, marginTop: 4 }}>
            <button
              onClick={save}
              style={{ border: 'none', background: '#3ecf8e', color: '#0a0c0f', cursor: 'pointer', fontSize: 11, fontWeight: 700, padding: '8px 16px', borderRadius: 7 }}
            >
              {busy ? 'saving…' : 'save encrypted'}
            </button>
            <button
              onClick={() => setEditing(false)}
              style={{ border: '1px solid #232932', background: 'transparent', color: '#9aa3af', cursor: 'pointer', fontSize: 11, padding: '8px 13px', borderRadius: 7 }}
            >
              cancel
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}

function CredentialsTab() {
  const { data: groups, reload } = usePoll('/api/credentials', 15000);
  const xGroup = (groups || []).find((g) => g.type === 'x_account');
  const envGroups = (groups || []).filter((g) => g.type === 'env');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>API keys &amp; secrets</span>
        <span className="os-mono" style={{ fontSize: 10, color: '#3ecf8e' }}>encrypted at rest ✓</span>
        <span className="os-mono" style={{ marginLeft: 'auto', fontSize: 10, color: '#5b6470' }}>write-only · secrets never displayed</span>
      </div>
      {xGroup && <XAccountCard group={xGroup} onSaved={reload} />}
      {envGroups.map((g) => {
        const allSet = g.keys.every((k) => k.set);
        return (
          <Card key={g.platform} style={{ padding: '14px 16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 11 }}>
              <span style={{ width: 9, height: 9, borderRadius: 2, flexShrink: 0, background: allSet ? '#3ecf8e' : '#f5a524' }} />
              <span style={{ fontSize: 13, fontWeight: 700, color: '#e7eaef' }}>{g.platform}</span>
              <span className="os-mono" style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 600, color: allSet ? '#3ecf8e' : '#f5a524' }}>
                {allSet ? 'configured' : 'incomplete'}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              {g.keys.map((k) => (
                <EnvKeyRow key={k.name} name={k.name} set={k.set} onSaved={reload} />
              ))}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

export default function Settings() {
  const { settingsTab, setSettingsTab } = useApp();
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '194px 1fr', gap: 20, alignItems: 'start' }}>
        {/* left tab rail */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, background: '#0c0f13', border: '1px solid #1a1f27', borderRadius: 12, padding: 8 }}>
          {SETTINGS_TABS.map(([k, label]) => {
            const active = settingsTab === k;
            const danger = k === 'danger';
            return (
              <button
                key={k}
                onClick={() => setSettingsTab(k)}
                className={`hover-tab${active ? ' active' : ''}`}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10, width: '100%', textAlign: 'left', border: 'none',
                  cursor: 'pointer', fontSize: 13, fontWeight: active ? 600 : 500, padding: '9px 12px', borderRadius: 8,
                  background: active ? (danger ? '#211519' : '#15201b') : 'transparent',
                  color: active ? (danger ? '#f5455c' : '#3ecf8e') : (danger ? '#8a6a70' : '#8b93a0'),
                }}
              >
                <span style={{ width: 5, height: 5, borderRadius: '50%', flexShrink: 0, background: active ? (danger ? '#f5455c' : '#3ecf8e') : '#3b414b' }} />
                {label}
              </button>
            );
          })}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {settingsTab === 'general' && <GeneralTab />}
          {settingsTab === 'actions' && <ActionsTab />}
          {settingsTab === 'ai' && <AiProvidersTab />}
          {settingsTab === 'credentials' && <CredentialsTab />}
          {settingsTab === 'danger' && <DangerTab />}
        </div>
      </div>
    </div>
  );
}
