import React, { useEffect, useState } from 'react';
import { useApp } from '../AppContext';
import { NICHE_COLOR, nicheLabel, TYPE_COLORS } from '../data';
import { api } from '../api';
import { Card, Toggle, TypeBadge } from './common';

const TABS = [
  ['general', 'General'], ['priority', 'Prioritization'], ['content', 'Content'],
  ['nsources', 'Sources'],
];

const POST_TYPES = ['news', 'spotlight', 'insight', 'take', 'tip', 'question', 'meme'];
// Short blurb per tone — the angle/voice a draft is written in. One enabled tone
// is assigned at random per post (shuffled rotation) so the feed varies.
const TONE_BLURBS = {
  news: 'timely development, why it matters',
  spotlight: 'highlight a tool / repo / product',
  insight: 'a non-obvious observation',
  take: 'a bold, opinionated stance',
  tip: 'one actionable how-to',
  question: 'provoke debate, open question',
  meme: 'witty, relatable one-liner',
};

// Per-niche post text controls (mirrors the dashboard General tab).
const POST_STYLES = [
  ['casual', 'Casual'], ['funny', 'Funny'], ['informative', 'Informative'],
  ['professional', 'Professional'], ['question', 'Question'], ['supportive', 'Supportive'],
];
const POST_LENGTHS = [
  ['very_short', 'Very Short', '2–5 words'], ['short', 'Short', 'A sentence'],
  ['medium', 'Medium', '1–2 lines'], ['long', 'Long', '3–4 lines'],
];

const settingRow = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 0', borderBottom: '1px solid #1a1f27' };
const inputStyle = {
  colorScheme: 'dark', background: '#0d1116', border: '1px solid #1c212a', borderRadius: 8,
  color: '#e7eaef', fontFamily: "'JetBrains Mono', monospace", fontSize: 12, padding: '8px 11px',
};
const numStyle = { ...inputStyle, width: 86, textAlign: 'center', fontWeight: 600 };

const chip = (fg, bg, border) => ({
  fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: fg, background: bg,
  border: border || 'none', padding: '4px 10px', borderRadius: 7,
});

// chips with add/remove backed by a string array in the config
function ChipList({ items, onChange, fg, bg, border, placeholder }) {
  const [adding, setAdding] = useState(false);
  const [value, setValue] = useState('');
  const add = () => {
    const v = value.trim().toLowerCase();
    if (v && !items.includes(v)) onChange([...items, v]);
    setValue('');
    setAdding(false);
  };
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
      {items.map((w) => (
        <span key={w} style={{ ...chip(fg, bg, border), display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          {w}
          <span
            onClick={() => onChange(items.filter((x) => x !== w))}
            style={{ cursor: 'pointer', opacity: 0.7, fontWeight: 700 }}
            title="remove"
          >
            ×
          </span>
        </span>
      ))}
      {adding ? (
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') add(); if (e.key === 'Escape') setAdding(false); }}
          onBlur={add}
          placeholder={placeholder}
          style={{ ...inputStyle, padding: '4px 9px', fontSize: 11, width: 140 }}
        />
      ) : (
        <span onClick={() => setAdding(true)} style={{ ...chip('#5b6470', 'transparent', '1px dashed #2a313c'), cursor: 'pointer' }}>+ add</span>
      )}
    </div>
  );
}

// A grid of single-select option buttons (post style / length).
function SelectGrid({ options, value, onChange, color, cols = 3 }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 9 }}>
      {options.map(([key, label, hint]) => {
        const on = value === key;
        return (
          <button
            key={key}
            onClick={() => onChange(on ? '' : key)}
            style={{
              cursor: 'pointer', textAlign: 'center', padding: '12px 10px', borderRadius: 10,
              background: on ? `color-mix(in oklch, ${color} 14%, transparent)` : '#0d1116',
              border: on ? `1px solid ${color}` : '1px solid #1c212a',
              color: on ? '#e7eaef' : '#9aa3af', transition: 'all .12s',
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600 }}>{label}</div>
            {hint && <div className="os-mono" style={{ fontSize: 9.5, color: on ? '#9aa3af' : '#5b6470', marginTop: 3 }}>{hint}</div>}
          </button>
        );
      })}
    </div>
  );
}

function GeneralTab({ cfg, set, color }) {
  const persona = cfg.persona || {};
  const f = cfg.filters || {};
  const textarea = {
    width: '100%', colorScheme: 'dark', background: '#0d1116', border: '1px solid #1c212a',
    borderRadius: 10, padding: 14, fontSize: 13.5, lineHeight: 1.6, color: '#d5dae1',
    fontFamily: 'inherit', resize: 'vertical',
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 680 }}>
      <div style={settingRow}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>slug</div>
          <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 2 }}>immutable identifier</div>
        </div>
        <span className="os-mono" style={{ ...inputStyle, border: '1px solid #1c212a' }}>{cfg.slug}</span>
      </div>
      <div style={settingRow}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>display_name</div>
        <input
          value={cfg.display_name || ''}
          onChange={(e) => set(['display_name'], e.target.value)}
          style={{ ...inputStyle, minWidth: 200 }}
        />
      </div>
      <div style={{ paddingTop: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Post style</div>
        <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginBottom: 11 }}>the voice every post for this niche is written in</div>
        <SelectGrid options={POST_STYLES} value={persona.style || ''} onChange={(v) => set(['persona', 'style'], v)} color={color} cols={3} />
      </div>
      <div style={{ paddingTop: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Post length</div>
        <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginBottom: 11 }}>how long the generated post should run</div>
        <SelectGrid options={POST_LENGTHS} value={persona.length || ''} onChange={(v) => set(['persona', 'length'], v)} color={color} cols={4} />
      </div>
      <div style={{ paddingTop: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Custom instructions <span className="os-mono" style={{ fontSize: 10, color: '#5b6470', fontWeight: 400 }}>(optional)</span></div>
        <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginBottom: 9 }}>extra guidance appended to every generation prompt for this niche</div>
        <textarea
          value={persona.instructions || ''}
          onChange={(e) => set(['persona', 'instructions'], e.target.value)}
          rows={3}
          placeholder={`e.g. Always include a concrete example for ${nicheLabel(cfg.slug)}…`}
          style={textarea}
        />
      </div>
      <div style={{ ...settingRow, marginTop: 4 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Image source</div>
          <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 2 }}>where this niche's post images come from</div>
        </div>
        <select
          value={cfg.image_source === 'unsplash' || cfg.image_source === 'content' ? cfg.image_source : 'none'}
          onChange={(e) => set(['image_source'], e.target.value)}
          style={{ ...inputStyle, padding: '7px 10px', minWidth: 170 }}
        >
          <option value="none">None</option>
          <option value="unsplash">Unsplash</option>
          <option value="content">Content</option>
        </select>
      </div>

      <div style={{ paddingTop: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 9 }}>Blocklist</div>
        <ChipList
          items={f.blocklist || []}
          onChange={(v) => set(['filters', 'blocklist'], v)}
          fg="#f0a8b0" bg="rgba(245,69,92,.08)" border="1px solid rgba(245,69,92,.2)"
          placeholder="blocked keyword…"
        />
      </div>
      <div style={{ paddingTop: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 9 }}>Relevance keywords</div>
        <ChipList
          items={f.relevance_keywords || []}
          onChange={(v) => set(['filters', 'relevance_keywords'], v)}
          fg="#3ecf8e" bg="rgba(62,207,142,.08)" border="1px solid rgba(62,207,142,.2)"
          placeholder="keyword…"
        />
      </div>
    </div>
  );
}

function PriorityTab({ cfg, set, color }) {
  const p = cfg.prioritization || {};
  const weights = [
    ['recency_weight', 'Recency', p.recency_weight != null ? p.recency_weight : 0.4],
    ['engagement_weight', 'Engagement', p.engagement_weight != null ? p.engagement_weight : 0.3],
    ['relevance_weight', 'Relevance', p.relevance_weight != null ? p.relevance_weight : 0.2],
    ['sentiment_weight', 'Sentiment', p.sentiment_weight != null ? p.sentiment_weight : 0.1],
  ];
  const sum = weights.reduce((s, [, , v]) => s + v, 0) || 1;
  return (
    <div style={{ maxWidth: 560 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Scoring weights</span>
        <span className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>normalized at scoring time</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {weights.map(([key, label, value]) => (
          <div key={key}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 7 }}>
              <span style={{ fontSize: 12.5, color: '#cfd6df' }}>{label}</span>
              <span className="os-mono" style={{ fontSize: 12, fontWeight: 700, color }}>{Math.round((value / sum) * 100)}%</span>
            </div>
            <input
              type="range" min="0" max="100" value={Math.round(value * 100)}
              onChange={(e) => set(['prioritization', key], +e.target.value / 100)}
              style={{ width: '100%', accentColor: '#3ecf8e', cursor: 'pointer' }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function PostTypesTab({ cfg, set }) {
  const pt = cfg.post_types || {};
  const grid = { display: 'grid', gridTemplateColumns: '130px 1fr 70px', gap: 14 };
  return (
    <div style={{ maxWidth: 560 }}>
      <div style={{ ...grid, padding: '0 4px 10px', borderBottom: '1px solid #1a1f27' }}>
        {['TONE', '', 'ENABLED'].map((h, i) => (
          <span key={i} className="os-mono" style={{ fontSize: 9, color: '#5b6470' }}>{h}</span>
        ))}
      </div>
      {POST_TYPES.map((t) => {
        const c = pt[t] || {};
        const enabled = !!pt[t] && c.enabled !== false;
        return (
          <div key={t} style={{ ...grid, alignItems: 'center', padding: '12px 4px', borderBottom: '1px solid #161b22', opacity: enabled ? 1 : 0.55 }}>
            <span style={{ justifySelf: 'start' }}><TypeBadge type={t} /></span>
            <span className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>{TONE_BLURBS[t]}</span>
            <Toggle on={enabled} onClick={() => set(['post_types', t, 'enabled'], !enabled)} size={19} />
          </div>
        );
      })}
    </div>
  );
}

function IndependentTab({ cfg, set }) {
  const ind = cfg.independent_take || {};
  const types = ind.types || [];
  const toggleType = (t) =>
    set(['independent_take', 'types'], types.includes(t) ? types.filter((x) => x !== t) : [...types, t]);
  return (
    <div style={{ maxWidth: 600, display: 'flex', flexDirection: 'column', gap: 2 }}>
      <div style={settingRow}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Independent takes</div>
          <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 2 }}>posts not tied to a source item</div>
        </div>
        <Toggle on={ind.enabled !== false && !!cfg.independent_take} onClick={() => set(['independent_take', 'enabled'], !(ind.enabled !== false && !!cfg.independent_take))} />
      </div>
      <div style={settingRow}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>per_day</span>
        <input
          type="number" min="0" max="6" value={ind.per_day != null ? ind.per_day : 1}
          onChange={(e) => set(['independent_take', 'per_day'], +e.target.value)}
          style={numStyle}
        />
      </div>
      <div style={{ padding: '14px 0', borderBottom: 'none' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 9 }}>eligible types · click to toggle</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {['insight', 'take', 'question', 'tip'].map((t) => {
            const on = types.includes(t);
            return (
              <button
                key={t}
                onClick={() => toggleType(t)}
                style={{
                  ...chip(on ? TYPE_COLORS[t][0] : '#5b6470', on ? TYPE_COLORS[t][1] : 'transparent', on ? 'none' : '1px solid #2a313c'),
                  cursor: 'pointer',
                }}
              >
                {t}
              </button>
            );
          })}
        </div>
        <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginTop: 12 }}>
          images follow the niche's Image source (General tab)
        </div>
      </div>
    </div>
  );
}

function ContentTab({ cfg, set }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 26 }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>Tones</div>
        <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginBottom: 14 }}>angles this niche writes in · one is picked at random per post · images follow the Image source (General tab)</div>
        <PostTypesTab cfg={cfg} set={set} />
      </div>
      <div style={{ borderTop: '1px solid #1a1f27', paddingTop: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>Independent takes</div>
        <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginBottom: 14 }}>original posts not tied to a fetched source item</div>
        <IndependentTab cfg={cfg} set={set} />
      </div>
    </div>
  );
}

function NicheSourcesTab({ cfg, set }) {
  const sources = cfg.sources || {};
  const names = Object.keys(sources);
  return (
    <div>
      <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', marginBottom: 12 }}>
        toggle which sources feed this niche · origins (feeds / subreddits / channels) are managed on the Sources tab
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, alignItems: 'start' }}>
        {names.map((name) => {
          const scfg = sources[name] || {};
          const enabled = scfg.enabled !== false;
          return (
            <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '11px 13px', background: '#0d1116', border: '1px solid #1c212a', borderRadius: 9 }}>
              <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: enabled ? '#3ecf8e' : '#3b414b' }} />
              <span style={{ flex: 1, fontSize: 12.5, fontWeight: 600, color: '#e7eaef' }}>{name}</span>
              <Toggle on={enabled} onClick={() => set(['sources', name, 'enabled'], !enabled)} size={17} />
            </div>
          );
        })}
        {!names.length && (
          <span className="os-mono" style={{ fontSize: 11, color: '#5b6470' }}>no sources configured for this niche</span>
        )}
      </div>
    </div>
  );
}

// immutable deep-set
function deepSet(obj, path, value) {
  if (!path.length) return value;
  const [head, ...rest] = path;
  const base = obj && typeof obj === 'object' ? obj : {};
  return { ...base, [head]: deepSet(base[head], rest, value) };
}

export default function NicheEditor() {
  const { settingsNiche, nicheTab, setNicheTab } = useApp();
  const color = NICHE_COLOR[settingsNiche];
  const [cfg, setCfg] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setCfg(null);
    setDirty(false);
    setError(null);
    api.get(`/api/niches/${settingsNiche}`).then(setCfg).catch((e) => setError(e.message));
  }, [settingsNiche]);

  const set = (path, value) => {
    setCfg((c) => deepSet(c, path, value));
    setDirty(true);
  };

  const save = () => {
    if (!cfg || saving) return;
    setSaving(true);
    api
      .put(`/api/niches/${settingsNiche}`, cfg)
      .then((saved) => { setCfg(saved); setDirty(false); })
      .catch((e) => alert(e.message))
      .finally(() => setSaving(false));
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 13, marginBottom: 14 }}>
        <span style={{ width: 11, height: 11, borderRadius: 3, background: color }} />
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: '-.3px' }}>{nicheLabel(settingsNiche)}</div>
          <div className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>
            editing config/niches/{settingsNiche}.json{dirty ? ' · unsaved changes' : ''}
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button
            onClick={save}
            className="run-btn"
            style={{
              border: 'none', cursor: dirty ? 'pointer' : 'default', fontSize: 12, fontWeight: 700,
              padding: '8px 16px', borderRadius: 8,
              background: dirty ? '#3ecf8e' : '#1c222b', color: dirty ? '#0a0c0f' : '#7a828f',
            }}
          >
            {saving ? 'Saving…' : dirty ? 'Save config' : 'Saved'}
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 4, padding: 4, background: '#10141a', border: '1px solid #1f242d', borderRadius: 10, marginBottom: 16, overflowX: 'auto' }}>
        {TABS.map(([k, label]) => {
          const active = nicheTab === k;
          return (
            <button
              key={k}
              onClick={() => setNicheTab(k)}
              style={{
                border: 'none', cursor: 'pointer', fontSize: 12.5, fontWeight: active ? 600 : 500,
                padding: '8px 13px', borderRadius: 8, whiteSpace: 'nowrap',
                background: active ? '#1c222b' : 'transparent', color: active ? '#e7eaef' : '#7a828f',
              }}
            >
              {label}
            </button>
          );
        })}
      </div>

      <Card style={{ padding: '22px 24px' }}>
        {error && <span className="os-mono" style={{ fontSize: 11, color: '#f5455c' }}>{error}</span>}
        {!cfg && !error && <span className="os-mono" style={{ fontSize: 11, color: '#5b6470' }}>loading config…</span>}
        {cfg && nicheTab === 'priority' && <PriorityTab cfg={cfg} set={set} color={color} />}
        {cfg && nicheTab === 'content' && <ContentTab cfg={cfg} set={set} />}
        {cfg && nicheTab === 'nsources' && <NicheSourcesTab cfg={cfg} set={set} />}
        {cfg && !['priority', 'content', 'nsources'].includes(nicheTab) && <GeneralTab cfg={cfg} set={set} color={color} />}
      </Card>
    </div>
  );
}
