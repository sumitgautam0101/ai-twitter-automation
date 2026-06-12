import React from 'react';
import { STATUS_COLORS, TYPE_COLORS, NICHE_COLOR, nicheLabel } from '../data';

export function Card({ style, className = '', children, ...rest }) {
  return (
    <div className={`os-card ${className}`} style={style} {...rest}>
      {children}
    </div>
  );
}

export function Badge({ map, value }) {
  const c = map[value] || ['#9aa3af', 'rgba(154,163,175,.13)'];
  return (
    <span
      className="os-mono"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10, fontWeight: 600,
        padding: '2px 8px', borderRadius: 999, letterSpacing: '.2px', color: c[0], background: c[1],
      }}
    >
      {value.replace('_', ' ')}
    </span>
  );
}

export const StatusBadge = ({ status }) => <Badge map={STATUS_COLORS} value={status} />;
export const TypeBadge = ({ type }) => <Badge map={TYPE_COLORS} value={type} />;

export function Toggle({ on, onClick, size = 22, onColor = '#3ecf8e', title, disabled = false }) {
  const w = Math.round(size * 1.82);
  const knob = size - 6;
  return (
    <button
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      title={title}
      style={{
        position: 'relative', width: w, height: size, borderRadius: 999, border: 'none',
        cursor: disabled ? 'not-allowed' : 'pointer', flexShrink: 0, transition: 'background .15s',
        background: on ? onColor : '#262c36', opacity: disabled ? 0.4 : 1,
      }}
    >
      <span
        style={{
          position: 'absolute', top: 3, left: on ? w - knob - 3 : 3, width: knob, height: knob,
          borderRadius: '50%', background: '#0a0c0f', transition: 'left .15s',
        }}
      />
    </button>
  );
}

export function NicheDot({ niche, size = 7, radius = 2 }) {
  return (
    <span style={{ width: size, height: size, borderRadius: radius, flexShrink: 0, background: NICHE_COLOR[niche] }} />
  );
}

export function NicheTag({ niche }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#cfd6df' }}>
      <NicheDot niche={niche} />
      <span>{nicheLabel(niche)}</span>
    </span>
  );
}

export function MediaThumb({ size = 84, url }) {
  return (
    <div
      style={{
        width: size, height: size, flexShrink: 0, borderRadius: 9, border: '1px solid #232932',
        background: 'repeating-linear-gradient(45deg,#14181e,#14181e 6px,#171c23 6px,#171c23 12px)',
        display: 'flex', alignItems: 'flex-end', justifyContent: 'center', paddingBottom: 6,
        overflow: 'hidden', position: 'relative',
      }}
    >
      {url && (
        <img
          src={url}
          alt=""
          loading="lazy"
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
          onError={(e) => { e.target.style.display = 'none'; }}
        />
      )}
      {!url && <span className="os-mono" style={{ fontSize: 8, color: '#4b5563' }}>media_url</span>}
    </div>
  );
}

export function SectionLabel({ children, style }) {
  return (
    <div className="os-mono" style={{ fontSize: 10, color: '#5b6470', letterSpacing: '.5px', ...style }}>
      {children}
    </div>
  );
}

export function EmptyState({ title, sub }) {
  return (
    <div style={{ textAlign: 'center', padding: '60px 20px', border: '1px dashed #232932', borderRadius: 12 }}>
      <div style={{ fontSize: 14, color: '#9aa3af', fontWeight: 600 }}>{title}</div>
      <div className="os-mono" style={{ fontSize: 11, color: '#5b6470', marginTop: 6 }}>{sub}</div>
    </div>
  );
}

export function PulseDot({ color = '#3ecf8e', size = 7, duration = '2s' }) {
  return (
    <span
      style={{
        width: size, height: size, borderRadius: '50%', background: color,
        animation: `os-pulse ${duration} infinite`, flexShrink: 0, display: 'inline-block',
      }}
    />
  );
}
