import React, { useState } from 'react';
import { Check, X } from 'lucide-react';
import { usePoll } from '../api';
import { useApp } from '../AppContext';
import { hms } from '../utils';
import { Card, NicheTag, EmptyState } from '../components/common';

const GRID = { display: 'grid', gridTemplateColumns: '110px 1.1fr 0.9fr 1.1fr 0.8fr 0.6fr 1.7fr', gap: 16 };
const headStyle = { fontSize: 9, color: '#5b6470', letterSpacing: '.4px' };
const statusColor = (s) => (s === 'success' ? '#3ecf8e' : s === 'failed' ? '#f5455c' : '#e7eaef');

const RANGES = [['today', 1], ['7d', 7], ['30d', 30]];
const FILTERS = ['all status', 'success', 'failed', 'with link'];

function Pill({ active, label, onClick }) {
  return (
    <span
      onClick={onClick}
      style={{
        padding: '5px 11px', borderRadius: 7, cursor: 'pointer',
        background: active ? '#1c222b' : 'transparent',
        color: active ? '#e7eaef' : '#7a828f',
        border: `1px solid ${active ? '#2a313c' : '#1c212a'}`,
      }}
    >
      {label}
    </span>
  );
}

export default function History() {
  const { withAccount } = useApp();
  const [days, setDays] = useState(1);
  const [filter, setFilter] = useState('all status');
  const { data } = usePoll(withAccount(`/api/history?days=${days}`), 5000);

  const rows = (data || []).filter((h) => {
    if (filter === 'success') return h.status === 'success';
    if (filter === 'failed') return h.status === 'failed';
    if (filter === 'with link') return h.link;
    return true;
  });

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <div className="os-mono" style={{ display: 'flex', gap: 6, fontSize: 11 }}>
          {RANGES.map(([label, d]) => (
            <Pill key={label} label={label} active={days === d} onClick={() => setDays(d)} />
          ))}
        </div>
        <div className="os-mono" style={{ display: 'flex', gap: 6, fontSize: 11, marginLeft: 4 }}>
          {FILTERS.map((f) => (
            <Pill key={f} label={f} active={filter === f} onClick={() => setFilter(f)} />
          ))}
        </div>
        <span className="os-mono" style={{ marginLeft: 'auto', fontSize: 11, color: '#5b6470' }}>
          {rows.length} rows · post_history
        </span>
      </div>

      {data && !rows.length && (
        <EmptyState title="No publish attempts in this range" sub="published and dry-run posts will appear here" />
      )}

      {rows.length > 0 && (
        <Card style={{ overflow: 'hidden' }}>
          <div style={{ ...GRID, padding: '13px 20px', borderBottom: '1px solid #1c212a', background: '#0d1116' }}>
            {['TIME', 'NICHE', 'TYPE', 'STATUS', 'COST', 'LINK', 'POST URL'].map((h) => (
              <span key={h} className="os-mono" style={headStyle}>{h}</span>
            ))}
          </div>
          {rows.map((h) => (
            <div
              key={h.id}
              style={{
                ...GRID, padding: '13px 20px', borderBottom: '1px solid #161b22', alignItems: 'center',
                background: h.dry ? 'rgba(245,165,36,.04)' : 'transparent',
              }}
            >
              <span className="os-mono" style={{ fontSize: 11, color: '#9aa3af' }}>{hms(h.ts)}</span>
              <NicheTag niche={h.niche} />
              <span className="os-mono" style={{ fontSize: 12, fontWeight: 600, color: '#e7eaef' }}>{h.type}</span>
              <span className="os-mono" style={{ fontSize: 12, fontWeight: 600, color: statusColor(h.status) }}>
                {h.status}{h.dry ? ' · dry' : ''}
              </span>
              <span className="os-mono" style={{ fontSize: 12, fontWeight: 600, color: h.cost > 0 ? '#e7eaef' : '#5b6470' }}>
                {h.cost === 0 ? '—' : `$${h.cost.toFixed(3)}`}
              </span>
              <span style={{ display: 'inline-flex', color: h.link ? '#3ecf8e' : '#5b6470' }}>{h.link ? <Check size={14} strokeWidth={3} /> : <X size={14} strokeWidth={3} />}</span>
              <span
                className="os-mono"
                style={{
                  fontSize: 11, color: h.dry ? '#9aa3af' : h.url ? '#cfd6df' : '#5b6470',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}
              >
                {h.url ? (
                  <a href={h.url} target="_blank" rel="noreferrer" style={{ color: '#7aa2f7', textDecoration: 'none' }}>{h.url}</a>
                ) : h.dry ? 'DRY-RUN' : '—'}
                {h.error && <> · <span style={{ color: '#f5455c' }}>{h.error}</span></>}
              </span>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
