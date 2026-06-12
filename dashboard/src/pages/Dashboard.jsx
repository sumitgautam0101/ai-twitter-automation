import React from 'react';
import { AlertTriangle, ArrowRight, Check, Share2, Star } from 'lucide-react';
import { useApp } from '../AppContext';
import { NICHE_COLOR, nicheLabel, LEVEL_COLORS } from '../data';
import { usePoll } from '../api';
import { isoToMinutes, nowMinutes, fmtTime, relTime, hms } from '../utils';
import { Card, NicheDot } from '../components/common';

function KpiRow({ ov }) {
  const kpis = ov
    ? [
        { label: 'Published today', value: String(ov.published_today), unit: `/ ${ov.global_daily_cap} cap`, sub: `${ov.published_with_link} with link`, color: '#3ecf8e', accent: '#3ecf8e' },
        { label: 'Yet to publish', value: String(ov.pending_total), unit: '', sub: 'drafts ready', color: '#e7eaef', accent: '#f5a524' },
        { label: 'Sources active', value: String(ov.sources_active), unit: `/ ${ov.sources_total}`, sub: `${ov.sources_total - ov.sources_active} disabled`, color: '#e7eaef', accent: '#7aa2f7' },
        { label: "Today's spend", value: `$${ov.spend_today.toFixed(2)}`, unit: '', sub: 'estimated · post_history', color: '#e7eaef', accent: '#9aa3af' },
      ]
    : [
        { label: 'Published today', value: '—', unit: '', sub: '', color: '#3ecf8e', accent: '#3ecf8e' },
        { label: 'Yet to publish', value: '—', unit: '', sub: '', color: '#e7eaef', accent: '#f5a524' },
        { label: 'Sources active', value: '—', unit: '', sub: '', color: '#e7eaef', accent: '#7aa2f7' },
        { label: "Today's spend", value: '—', unit: '', sub: '', color: '#e7eaef', accent: '#9aa3af' },
      ];
  return (
    <div className="os-grid-kpi" style={{ marginBottom: 16 }}>
      {kpis.map((k) => (
        <Card key={k.label} className="hover-card" style={{ padding: '13px 15px', transition: 'border-color .12s' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: k.accent, flexShrink: 0 }} />
            <div className="os-mono" style={{ fontSize: 9.5, color: '#6b7280', letterSpacing: '.5px', textTransform: 'uppercase' }}>{k.label}</div>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 7 }}>
            <span style={{ fontSize: 25, fontWeight: 700, letterSpacing: '-.5px', color: k.color, lineHeight: 1 }}>{k.value}</span>
            <span className="os-mono" style={{ fontSize: 11, color: '#5b6470' }}>{k.unit}</span>
          </div>
          <div className="os-mono" style={{ fontSize: 10, color: '#566', marginTop: 5 }}>{k.sub}</div>
        </Card>
      ))}
    </div>
  );
}

const trackGrid = { display: 'grid', gridTemplateColumns: '130px 1fr 46px 46px 40px', gap: 12, alignItems: 'center' };
const colHead = { fontSize: 9, color: '#5b6470', letterSpacing: '.4px' };

// per-category ingestion funnel: found → candidates → published (today, live)
function CategoryTracking({ ov }) {
  const { editNiche } = useApp();
  const rows = (ov ? ov.funnel : [])
    .map((f) => ({
      slug: f.slug,
      label: f.display_name || nicheLabel(f.slug),
      color: NICHE_COLOR[f.slug],
      enabled: f.enabled,
      found: f.found,
      candidates: f.candidates,
      published: f.published,
      candPct: f.found ? Math.round((f.candidates / f.found) * 100) : 0,
      pubPct: f.found ? Math.round((f.published / f.found) * 100) : 0,
    }))
    .filter((r) => r.found > 0 || r.candidates > 0 || r.published > 0)
    .sort((a, b) => b.found - a.found);
  const totals = rows.reduce(
    (t, r) => ({ found: t.found + r.found, candidates: t.candidates + r.candidates, published: t.published + r.published }),
    { found: 0, candidates: 0, published: 0 }
  );

  return (
    <Card style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 13, flexWrap: 'wrap' }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>Category tracking</div>
        <span className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>ingestion funnel · today</span>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 16 }}>
          {[['found', totals.found, '#e7eaef'], ['cand', totals.candidates, '#9ee9c5'], ['pub', totals.published, '#3ecf8e']].map(([lbl, v, c]) => (
            <div key={lbl} style={{ textAlign: 'right' }}>
              <span className="os-mono" style={{ fontSize: 15, fontWeight: 700, color: c }}>{v}</span>
              <span className="os-mono" style={{ fontSize: 9, color: '#5b6470', marginLeft: 4 }}>{lbl}</span>
            </div>
          ))}
        </div>
      </div>
      <div style={{ ...trackGrid, padding: '0 2px 8px', borderBottom: '1px solid #1c212a' }}>
        <span className="os-mono" style={colHead}>CATEGORY</span>
        <span className="os-mono" style={colHead}>FUNNEL</span>
        <span className="os-mono" style={{ ...colHead, textAlign: 'right' }}>FND</span>
        <span className="os-mono" style={{ ...colHead, textAlign: 'right' }}>CND</span>
        <span className="os-mono" style={{ ...colHead, textAlign: 'right' }}>PUB</span>
      </div>
      <div>
        {rows.map((c) => (
          <div
            key={c.slug}
            onClick={() => editNiche(c.slug)}
            className="hover-row"
            style={{ ...trackGrid, padding: '9px 2px', borderBottom: '1px solid #161b22', cursor: 'pointer', opacity: c.enabled ? 1 : 0.45 }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, flexShrink: 0, background: c.color }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: '#cfd6df', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.label}</span>
            </div>
            <div style={{ height: 9, width: '100%', background: '#1c222b', borderRadius: 4, position: 'relative', overflow: 'hidden' }}>
              <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, borderRadius: 4, width: `${c.candPct}%`, background: 'rgba(62,207,142,.25)' }} />
              <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, borderRadius: 4, width: `${c.pubPct}%`, background: '#3ecf8e' }} />
            </div>
            <span className="os-mono" style={{ fontSize: 12, fontWeight: 600, color: '#9aa3af', textAlign: 'right' }}>{c.found}</span>
            <span className="os-mono" style={{ fontSize: 12, fontWeight: 600, color: '#9ee9c5', textAlign: 'right' }}>{c.candidates}</span>
            <span className="os-mono" style={{ fontSize: 12, fontWeight: 700, color: '#3ecf8e', textAlign: 'right' }}>{c.published}</span>
          </div>
        ))}
        {!rows.length && (
          <div className="os-mono" style={{ padding: '18px 2px', fontSize: 11, color: '#5b6470' }}>
            waiting for service…
          </div>
        )}
      </div>
    </Card>
  );
}

// upcoming slots across all enabled categories, now → end of day (server-resolved)
function NextSlots({ sched }) {
  const nowMin = nowMinutes();
  const up = [];
  (sched ? sched.niches : []).forEach((n) => {
    if (!n.enabled) return;
    n.slots.forEach((iso) => {
      const m = isoToMinutes(iso);
      if (m > nowMin) up.push({ niche: n.slug, m });
    });
  });
  up.sort((a, b) => a.m - b.m);

  return (
    <Card style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 13 }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>Next posting slots</div>
        <span className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>till EOD · {up.length} posts</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9, maxHeight: 300, overflowY: 'auto' }}>
        {up.map((s, i) => (
          <div key={`${s.niche}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <NicheDot niche={s.niche} />
            <span style={{ fontSize: 12, color: '#cfd6df', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{nicheLabel(s.niche)}</span>
            <span className="os-mono" style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 600, color: '#e7eaef', flexShrink: 0 }}>{fmtTime(s.m)}</span>
            <span className="os-mono" style={{ fontSize: 10, color: '#5b6470', width: 58, textAlign: 'right', flexShrink: 0 }}>{relTime(Math.round(s.m - nowMin))}</span>
          </div>
        ))}
        {!up.length && (
          <span className="os-mono" style={{ fontSize: 11, color: '#5b6470' }}>no more slots today</span>
        )}
      </div>
    </Card>
  );
}

function ActivityFeed({ ov }) {
  const rows = ov ? ov.activity : [];
  return (
    <Card style={{ padding: '16px 18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 13 }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>Activity</div>
        <span className="os-mono" style={{ fontSize: 10, color: '#5b6470' }}>live · 5s poll</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {rows.map((e) => {
          const [fg, bg] = LEVEL_COLORS[e.level] || LEVEL_COLORS.info;
          return (
            <div key={e.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid #161b22' }}>
              <span className="os-mono" style={{ fontSize: 10, color: '#5b6470', width: 62, flexShrink: 0 }}>{hms(e.ts)}</span>
              <span
                className="os-mono"
                style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 5, width: 42, textAlign: 'center', color: fg, background: bg }}
              >
                {e.level}
              </span>
              <span style={{ fontSize: 12.5, color: '#aeb6c0', flex: 1, minWidth: 0 }}>{e.msg}</span>
              {e.niche && <span style={{ fontSize: 11, textTransform: 'capitalize', color: NICHE_COLOR[e.niche] }}>{e.niche}</span>}
            </div>
          );
        })}
        {!rows.length && (
          <span className="os-mono" style={{ fontSize: 11, color: '#5b6470', padding: '10px 0' }}>
            no activity yet — run a fetch to get started
          </span>
        )}
      </div>
    </Card>
  );
}

// First-run onboarding — replaces the whole dashboard until the user has both
// enabled a source and selected a niche, then tells them exactly what to do.
function SetupGuide({ setup }) {
  const { setRoute } = useApp();
  const steps = [
    {
      done: setup.enabled_sources > 0,
      icon: Share2,
      title: 'Enable a content source',
      desc: 'Sources are what OpenX fetches posts from (RSS, Hacker News, Reddit…). Turn at least one on.',
      route: 'sources',
      cta: 'Go to Sources',
    },
    {
      done: setup.selected_niches > 0,
      icon: Star,
      title: 'Select a niche',
      desc: 'Niches define your topics and voice. Select the ones you post in — only selected niches are fetched and drafted for.',
      route: 'niches',
      cta: 'Go to Niches',
    },
  ];
  const nextStep = steps.find((s) => !s.done);

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      {/* top note */}
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 12, padding: '13px 16px', marginBottom: 18,
          background: 'rgba(245,165,36,.09)', border: '1px solid rgba(245,165,36,.28)', borderRadius: 11,
        }}
      >
        <span style={{ display: 'inline-flex', color: '#f5a524', flexShrink: 0 }}><AlertTriangle size={18} /></span>
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: '#f5d8a4' }}>Finish setup to get started</div>
          <div className="os-mono" style={{ fontSize: 11, color: '#b89a6a', marginTop: 2 }}>
            OpenX needs at least one enabled source and one selected niche before it can do anything.
          </div>
        </div>
      </div>

      <Card style={{ padding: '8px 0' }}>
        {steps.map((s, i) => {
          const Icon = s.icon;
          const isNext = s === nextStep;
          return (
            <div
              key={s.route}
              style={{
                display: 'flex', alignItems: 'center', gap: 14, padding: '16px 20px',
                borderTop: i ? '1px solid #161b22' : 'none',
              }}
            >
              <span
                style={{
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 38, height: 38,
                  borderRadius: 10, flexShrink: 0,
                  background: s.done ? 'rgba(62,207,142,.12)' : 'rgba(122,162,247,.1)',
                  color: s.done ? '#3ecf8e' : '#7aa2f7',
                }}
              >
                {s.done ? <Check size={18} strokeWidth={3} /> : <Icon size={17} />}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                  <span style={{ fontSize: 13.5, fontWeight: 600, color: s.done ? '#7a828f' : '#e7eaef' }}>
                    {s.title}
                  </span>
                  {s.done && (
                    <span className="os-mono" style={{ fontSize: 9, fontWeight: 700, padding: '1px 7px', borderRadius: 999, color: '#3ecf8e', background: 'rgba(62,207,142,.13)' }}>
                      done
                    </span>
                  )}
                </div>
                <div className="os-mono" style={{ fontSize: 10.5, color: '#5b6470', marginTop: 3, lineHeight: 1.5 }}>
                  {s.desc}
                </div>
              </div>
              <button
                onClick={() => setRoute(s.route)}
                className="run-btn"
                style={{
                  flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 7, border: 'none',
                  cursor: 'pointer', fontSize: 12, fontWeight: 700, padding: '8px 14px', borderRadius: 8,
                  background: isNext ? '#3ecf8e' : '#1c222b', color: isNext ? '#0a0c0f' : '#9aa3af',
                }}
              >
                {s.cta} <ArrowRight size={13} />
              </button>
            </div>
          );
        })}
      </Card>

      <div className="os-mono" style={{ fontSize: 10, color: '#4b5563', textAlign: 'center', marginTop: 16 }}>
        once both are done, your dashboard, queue, and schedule come to life here.
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { data: ov } = usePoll('/api/overview', 5000);
  const { data: sched } = usePoll('/api/schedule', 60000);

  if (ov && ov.setup && ov.setup.needs_setup) {
    return <SetupGuide setup={ov.setup} />;
  }

  return (
    <div>
      <KpiRow ov={ov} />
      <div className="os-grid-main" style={{ marginBottom: 14 }}>
        <CategoryTracking ov={ov} />
        <NextSlots sched={sched} />
      </div>
      <ActivityFeed ov={ov} />
    </div>
  );
}
