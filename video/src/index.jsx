import React from 'react';
import {
  registerRoot, Composition, AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, spring, Easing,
  staticFile, Audio, Sequence, random, getInputProps,
} from 'remotion';
import {TransitionSeries, springTiming, linearTiming} from '@remotion/transitions';
import {slide} from '@remotion/transitions/slide';
import {wipe} from '@remotion/transitions/wipe';
import {fade} from '@remotion/transitions/fade';
import timeline from '../timeline.json';

const C = {
  bg: '#F7F8FA', white: '#FFFFFF', ink: '#0E1116', muted: '#566070', line: '#E2E6EB', mist: '#EEF1F4',
  mint: '#3BE6A2', deep: '#0A7D55', amber: '#E8962A', red: '#D64545', dark2: '#171B22', dline: '#2A303B', dmuted: '#A3ACBA',
};
const fontCss = `
@font-face { font-family: 'Archivo'; src: url('${staticFile('Archivo.ttf')}'); font-weight: 100 900; }
@font-face { font-family: 'Plex'; src: url('${staticFile('PlexSans.ttf')}'); font-weight: 100 700; }
@font-face { font-family: 'PlexMono'; src: url('${staticFile('PlexMono-Medium.ttf')}'); font-weight: 500; }
`;
const D = "'Archivo', sans-serif", B = "'Plex', sans-serif", M = "'PlexMono', 'DejaVu Sans Mono', monospace";

const useSpr = (delay = 0, cfg = {damping: 14, stiffness: 160, mass: 0.7}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  return spring({frame: f - delay, fps, config: cfg});
};
const lerp = (k, a, b) => a + (b - a) * k;

const Grid = ({dark}) => (
  <AbsoluteFill style={{
    backgroundImage: `linear-gradient(${dark ? 'rgba(255,255,255,0.04)' : 'rgba(14,17,22,0.045)'} 1px, transparent 1px), linear-gradient(90deg, ${dark ? 'rgba(255,255,255,0.04)' : 'rgba(14,17,22,0.045)'} 1px, transparent 1px)`,
    backgroundSize: '96px 96px',
  }} />
);

const Tag = ({children, delay = 0, dark}) => {
  const k = useSpr(delay);
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 14, fontFamily: M, fontSize: 24, letterSpacing: 2,
      color: dark ? C.mint : C.deep, opacity: k, transform: `translateX(${lerp(k, -30, 0)}px)`}}>
      <div style={{width: 46 * k, height: 3, background: dark ? C.mint : C.deep, borderRadius: 2}} />{children}
    </div>
  );
};

// Words that slam in
const Slam = ({words, delay = 0, gap = 5, size = 150, color = C.ink, accent = {}, style = {}}) => (
  <div style={{display: 'flex', flexWrap: 'wrap', columnGap: size * 0.26, ...style}}>
    {words.map((w, i) => <SlamWord key={i} w={w} delay={delay + i * gap} size={size} color={accent[i] || color} />)}
  </div>
);
const SlamWord = ({w, delay, size, color}) => {
  const k = useSpr(delay, {damping: 12, stiffness: 220, mass: 0.6});
  return (
    <span style={{fontFamily: D, fontWeight: 800, fontSize: size, lineHeight: 1.02, letterSpacing: -size * 0.035, color,
      display: 'inline-block', opacity: Math.min(1, k * 1.6), transform: `translateY(${lerp(k, 70, 0)}px) scale(${lerp(k, 1.35, 1)})`,
      filter: `blur(${(1 - Math.min(1, k)) * 10}px)`}}>{w}</span>
  );
};

const Card = ({r, s, delay = 0, w = 128, h = 178, back}) => {
  const k = useSpr(delay, {damping: 13, stiffness: 170, mass: 0.6});
  const red = s === '♥' || s === '♦';
  return (
    <div style={{width: w, height: h, perspective: 900, opacity: Math.min(1, k * 2)}}>
      <div style={{width: '100%', height: '100%', borderRadius: 14, transform: `translateY(${lerp(k, -80, 0)}px) rotateY(${lerp(k, 100, 0)}deg) rotateZ(${lerp(k, -12, 0)}deg)`,
        background: back ? 'repeating-linear-gradient(45deg, #1d2430 0 10px, #252e3d 10px 20px)' : '#fff',
        border: back ? '2px solid #3a4558' : '1px solid #dfe3e8', boxShadow: '0 18px 40px -18px rgba(0,0,0,0.5)',
        color: red ? '#D62839' : '#12141a', padding: 14, boxSizing: 'border-box', fontFamily: D, fontWeight: 800}}>
        {!back && <><div style={{fontSize: w * 0.42, lineHeight: 1}}>{r}</div><div style={{fontSize: w * 0.36, fontFamily: 'DejaVu Sans'}}>{s}</div></>}
      </div>
    </div>
  );
};

// ---------- scenes ----------
const S1 = () => {
  const f = useCurrentFrame();
  const u = useSpr(38, {damping: 20, stiffness: 120});
  return (
    <AbsoluteFill style={{background: C.bg}}>
      <Grid />
      <AbsoluteFill style={{padding: '0 150px', justifyContent: 'center'}}>
        <Slam words={['Every', 'hand', 'has']} delay={2} size={160} />
        <Slam words={['a', 'right', 'answer.']} delay={14} size={160} accent={{2: C.deep}} />
        <div style={{height: 12, width: 1040 * u, background: C.mint, borderRadius: 8, marginTop: 10}} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const S2 = () => {
  const f = useCurrentFrame();
  const word = 'PokerScribe';
  const dot = useSpr(26, {damping: 8, stiffness: 260, mass: 0.5});
  const tl = useSpr(30);
  return (
    <AbsoluteFill style={{background: C.ink, alignItems: 'center', justifyContent: 'center'}}>
      <Grid dark />
      <div style={{display: 'flex', alignItems: 'flex-start'}}>
        {word.split('').map((ch, i) => {
          const k = spring({frame: f - 2 - i * 1.6, fps: 30, config: {damping: 13, stiffness: 200, mass: 0.5}});
          return <span key={i} style={{fontFamily: D, fontWeight: 800, fontSize: 190, color: '#fff', letterSpacing: -6,
            display: 'inline-block', opacity: Math.min(1, k * 1.5), transform: `translateY(${lerp(k, 120, 0)}px) rotate(${lerp(k, 12, 0)}deg)`}}>{ch}</span>;
        })}
        <div style={{width: 40, height: 40, borderRadius: 20, background: C.mint, marginTop: 120, marginLeft: 6, transform: `scale(${dot})`,
          boxShadow: `0 0 ${60 * dot}px ${C.mint}`}} />
      </div>
      <div style={{fontFamily: B, fontSize: 44, color: C.dmuted, marginTop: 20, opacity: tl, transform: `translateY(${lerp(tl, 20, 0)}px)`}}>
        The AI poker coach, built on game theory.
      </div>
    </AbsoluteFill>
  );
};

const Bracket = ({x, y, w, h, label, delay, below}) => {
  const k = useSpr(delay, {damping: 11, stiffness: 240, mass: 0.5});
  const L = 30, pad = lerp(k, 40, 0);
  const corner = (cx, cy, dx, dy) => (
    <div style={{position: 'absolute', left: cx + dx * -pad - (dx < 0 ? L : 0), top: cy + dy * -pad - (dy < 0 ? L : 0), width: L, height: L,
      borderTop: dy > 0 ? `4px solid ${C.mint}` : 'none', borderBottom: dy < 0 ? `4px solid ${C.mint}` : 'none',
      borderLeft: dx > 0 ? `4px solid ${C.mint}` : 'none', borderRight: dx < 0 ? `4px solid ${C.mint}` : 'none', opacity: k}} />
  );
  return (
    <>
      {corner(x, y, 1, 1)}{corner(x + w, y, -1, 1)}{corner(x, y + h, 1, -1)}{corner(x + w, y + h, -1, -1)}
      <div style={{position: 'absolute', left: x, top: below ? y + h + 12 : y - 52, background: C.mint, color: '#06120D', fontFamily: M,
        fontSize: 22, padding: '6px 14px', borderRadius: 8, transform: `scale(${k})`, transformOrigin: 'left center', whiteSpace: 'nowrap'}}>{label}</div>
    </>
  );
};

const S3 = () => {
  const f = useCurrentFrame();
  const t = useSpr(4);
  const tbl = useSpr(8, {damping: 18, stiffness: 120});
  const scan = interpolate(f, [70, 110], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic)});
  const cx = 960, cy = 600;
  return (
    <AbsoluteFill style={{background: C.bg}}>
      <Grid />
      <div style={{position: 'absolute', left: 120, top: 80}}>
        <Tag delay={2}>01 READ</Tag>
        <div style={{fontFamily: D, fontWeight: 800, fontSize: 84, letterSpacing: -3, color: C.ink, marginTop: 14, opacity: t, transform: `translateY(${lerp(t, 30, 0)}px)`}}>It reads the table.</div>
      </div>
      <div style={{position: 'absolute', left: cx - 660, top: cy - 250, width: 1320, height: 500, borderRadius: 260,
        background: 'radial-gradient(ellipse at center, #17473a 0%, #0f2f27 70%)', border: '6px solid #0b2019',
        boxShadow: `inset 0 0 0 3px rgba(59,230,162,0.25), 0 40px 80px -40px rgba(0,0,0,0.5)`, transform: `scale(${lerp(tbl, 0.85, 1)})`, opacity: tbl}} />
      <div style={{position: 'absolute', left: cx - 70, top: cy - 330, display: 'flex', gap: 14}}>
        <Card back w={92} h={128} delay={18} /><Card back w={92} h={128} delay={21} />
      </div>
      <div style={{position: 'absolute', left: cx - 360, top: cy - 100, display: 'flex', gap: 22}}>
        {[['Q', '♠'], ['9', '♥'], ['4', '♠'], ['2', '♣'], ['K', '♠']].map(([r, s], i) => <Card key={i} r={r} s={s} delay={26 + i * 4} w={124} h={172} />)}
      </div>
      <div style={{position: 'absolute', left: cx - 140, top: cy + 190, display: 'flex', gap: 18}}>
        <Card r="A" s="♠" delay={46} /><Card r="Q" s="♦" delay={50} />
      </div>
      <ChipBet x={cx + 300} y={cy - 210} delay={56} />
      {scan > 0 && scan < 1 && <div style={{position: 'absolute', left: cx - 700, width: 1400, top: cy - 360 + 760 * scan, height: 4, background: C.mint, boxShadow: `0 0 30px ${C.mint}`}} />}
      <Bracket x={cx - 380} y={cy - 120} w={760} h={212} label="BOARD  Q♠ 9♥ 4♠ 2♣ K♠" delay={84} />
      <Bracket x={cx + 270} y={cy - 240} w={190} h={64} label="BET 18 bb" delay={94} />
      <Bracket x={cx - 160} y={cy + 170} w={330} h={218} label="YOU  A♠ Q♦  ·  TO ACT" delay={104} below />
    </AbsoluteFill>
  );
};
const ChipBet = ({x, y, delay}) => {
  const k = useSpr(delay, {damping: 10, stiffness: 220, mass: 0.5});
  return (
    <div style={{position: 'absolute', left: x, top: y, display: 'flex', alignItems: 'center', gap: 14, transform: `scale(${k})`}}>
      <div style={{width: 46, height: 46, borderRadius: 23, background: C.amber, border: '5px dashed #fff3dc', boxSizing: 'border-box'}} />
      <span style={{fontFamily: M, fontSize: 36, color: '#fff'}}>18</span>
    </div>
  );
};

const CALCS = [
  ['Pot odds', 'need 29.8%', -620, -300], ['Their range', '34 value · 9 bluffs', 470, -320], ['Player read', '2 bluffs in 31 rivers', -700, 120],
  ['Blockers', 'A♠ kills the nut flush', 520, 150], ['Bluff chance', '15%', -560, 330], ['EV of calling', '−8.9 bb', 560, 340],
];
const S4 = () => {
  const f = useCurrentFrame();
  const t = useSpr(2);
  const ranks = 'AKQJT98765432';
  const stamp = spring({frame: f - 128, fps: 30, config: {damping: 9, stiffness: 300, mass: 0.6}});
  const shake = f >= 128 && f < 140 ? (random(`sx${f}`) - 0.5) * 18 * (1 - (f - 128) / 12) : 0;
  const shake2 = f >= 128 && f < 140 ? (random(`sy${f}`) - 0.5) * 18 * (1 - (f - 128) / 12) : 0;
  const gridOut = interpolate(f, [96, 116], [1, 0.18], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{background: C.ink, transform: `translate(${shake}px, ${shake2}px)`}}>
      <Grid dark />
      <div style={{position: 'absolute', left: 120, top: 80}}>
        <Tag delay={2} dark>02 SOLVE</Tag>
        <div style={{fontFamily: D, fontWeight: 800, fontSize: 84, letterSpacing: -3, color: '#fff', marginTop: 14, opacity: t, transform: `translateY(${lerp(t, 30, 0)}px)`}}>One decision. Every angle.</div>
      </div>
      <div style={{position: 'absolute', left: 960 - 330, top: 330, width: 660, display: 'grid', gridTemplateColumns: 'repeat(13, 1fr)', gap: 5, opacity: gridOut}}>
        {Array.from({length: 169}).map((_, i) => {
          const r = Math.floor(i / 13), c = i % 13; const hi = Math.min(r, c), lo = Math.max(r, c);
          const sc = (12 - hi) * 2 + (12 - lo) + (r === c ? 20 : c > r ? 4 : 0);
          const k = spring({frame: f - 6 - (r + c) * 1.2, fps: 30, config: {damping: 14, stiffness: 200, mass: 0.5}});
          const bg = sc >= 30 ? C.mint : sc >= 24 ? '#F5B14C' : C.dark2;
          return <div key={i} style={{aspectRatio: '1', borderRadius: 6, background: bg, transform: `scale(${k})`, opacity: k}} />;
        })}
      </div>
      {CALCS.map(([a, b, dx, dy], i) => {
        const d = 34 + i * 9; const k = spring({frame: f - d, fps: 30, config: {damping: 11, stiffness: 220, mass: 0.5}});
        const out = interpolate(f, [118, 128], [1, 0.25], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
        return (
          <div key={i} style={{position: 'absolute', left: 960 + dx * lerp(k, 0.4, 1) - 190, top: 600 + dy * lerp(k, 0.4, 1) - 50, width: 380,
            background: 'rgba(23,27,34,0.96)', border: `1px solid ${C.dline}`, borderRadius: 16, padding: '18px 22px', boxSizing: 'border-box',
            transform: `scale(${k})`, opacity: Math.min(1, k) * out, boxShadow: '0 20px 50px -20px rgba(0,0,0,0.8)'}}>
            <div style={{fontFamily: M, fontSize: 20, color: C.dmuted, letterSpacing: 1}}>{a.toUpperCase()}</div>
            <div style={{fontFamily: D, fontWeight: 700, fontSize: 38, color: i === 5 ? '#FF8A80' : '#fff', marginTop: 4}}>{b}</div>
          </div>
        );
      })}
      {f >= 120 && (
        <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
          <div style={{fontFamily: D, fontWeight: 900, fontSize: 260, letterSpacing: -10, color: C.mint, transform: `scale(${lerp(stamp, 3, 1)}) rotate(${lerp(stamp, -8, -3)}deg)`,
            opacity: Math.min(1, stamp * 2), textShadow: `0 0 80px rgba(59,230,162,0.6)`, border: `10px solid ${C.mint}`, borderRadius: 30, padding: '0 50px'}}>FOLD</div>
          <div style={{fontFamily: M, fontSize: 34, color: '#fff', marginTop: 40, opacity: interpolate(f, [140, 150], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}>
            saves 8.9 bb against this player
          </div>
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};


const STREETS = [
  ['Preflop', 'A♠ Q♦ on the cutoff', 'Raise 2.5 bb', 'ok', 'Standard open'],
  ['Flop  Q♠ 9♥ 4♠', 'Top pair, top kicker', 'C-bet 33%', 'ok', 'Solver bets here 88% of the time'],
  ['Turn  2♣', 'Still ahead of most calls', 'Check', 'mix', 'Betting 50% earns more · −0.6 bb'],
  ['River  K♠', 'Seat 4 bets 18 into 24.5', 'Call', 'bad', 'Losing call · −8.9 bb'],
];
const SEG = [['Flushes', 12, '#D64545'], ['Two pair', 9, '#E26D5A'], ['Sets', 7, '#EE8F6B'], ['Straights', 4, '#F2AE88'], ['K-Q', 2, '#F6C9AE'], ['Bluffs', 9, '#3BE6A2']];
const PARA = 'The K♠ completes the flush and J-T. Seat 4 checked the turn, then bet big: a line that is about four parts value to one part bluff. Your A♠ blocks the nut flush, but nine other flushes remain. You need to win 29.8% to call. Against this player you win about 15%.';
const S5 = () => {
  const f = useCurrentFrame();
  const t = useSpr(2);
  const panel = useSpr(58, {damping: 18, stiffness: 140});
  const total = SEG.reduce((a, b) => a + b[1], 0);
  const typed = Math.max(0, Math.min(PARA.length, Math.floor((f - 118) * 3.4)));
  const chip = (kind) => ({ok: ['✓', C.deep, 'rgba(59,230,162,0.16)'], mix: ['~', '#9a5c0a', 'rgba(232,150,42,0.15)'], bad: ['✕', C.red, 'rgba(214,69,69,0.13)']})[kind];
  return (
    <AbsoluteFill style={{background: C.bg}}>
      <Grid />
      <div style={{position: 'absolute', left: 100, top: 64}}>
        <Tag delay={2}>03 COACH</Tag>
        <div style={{fontFamily: D, fontWeight: 800, fontSize: 70, letterSpacing: -2.5, color: C.ink, marginTop: 10, opacity: t, transform: `translateY(${lerp(t, 30, 0)}px)`}}>Then it tells you exactly why.</div>
      </div>
      <div style={{position: 'absolute', left: 100, top: 250, width: 720, background: '#fff', border: `1px solid ${C.line}`, borderRadius: 22, overflow: 'hidden', boxShadow: '0 30px 80px -50px rgba(14,17,22,0.45)'}}>
        <div style={{display: 'flex', justifyContent: 'space-between', padding: '20px 28px', borderBottom: `1px solid ${C.line}`, fontFamily: B, fontWeight: 600, fontSize: 26}}>
          <span>Hand #142 · vs Seat 4</span><span style={{fontFamily: M, fontSize: 18, color: C.muted, alignSelf: 'center'}}>SAMPLE</span>
        </div>
        {STREETS.map(([st, sit, act, kind, note], i) => {
          const k = spring({frame: f - 14 - i * 14, fps: 30, config: {damping: 14, stiffness: 190, mass: 0.6}});
          const [g, col, bg] = chip(kind);
          return (
            <div key={i} style={{display: 'grid', gridTemplateColumns: '1fr auto', gap: 6, padding: '18px 28px', borderBottom: i < 3 ? `1px solid ${C.line}` : 'none',
              background: kind === 'bad' ? 'rgba(214,69,69,0.05)' : 'transparent', opacity: k, transform: `translateX(${lerp(k, -60, 0)}px)`}}>
              <span style={{fontFamily: M, fontSize: 19, color: C.muted}}>{st}</span>
              <span style={{gridRow: 'span 2', alignSelf: 'center', width: 46, height: 46, borderRadius: 23, background: bg, color: col, display: 'grid', placeItems: 'center', fontFamily: D, fontWeight: 800, fontSize: 24}}>{g}</span>
              <span style={{fontFamily: B, fontSize: 26, color: C.ink}}><b style={{fontWeight: 700}}>{act}</b> <span style={{color: C.muted}}>· {sit}</span></span>
              <span style={{gridColumn: '1 / -1', fontFamily: M, fontSize: 18, color: col}}>{note}</span>
            </div>
          );
        })}
      </div>
      <div style={{position: 'absolute', left: 860, top: 250, right: 100, bottom: 70, background: C.ink, borderRadius: 22, padding: '28px 34px', color: '#fff',
        opacity: panel, transform: `translateY(${lerp(panel, 60, 0)}px)`, display: 'flex', flexDirection: 'column', gap: 20}}>
        <div style={{fontFamily: D, fontWeight: 700, fontSize: 34}}>Why the river call loses</div>
        <div>
          <div style={{fontFamily: M, fontSize: 17, color: C.dmuted, marginBottom: 10}}>SEAT 4'S BETTING RANGE HERE · 43 COMBOS</div>
          <div style={{display: 'flex', height: 34, borderRadius: 8, overflow: 'hidden', gap: 2}}>
            {SEG.map(([n, v, col], i) => {
              const k = interpolate(f, [76 + i * 5, 92 + i * 5], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic)});
              return <div key={i} style={{width: `${(v / total) * 100 * k}%`, background: col}} />;
            })}
          </div>
          <div style={{display: 'flex', flexWrap: 'wrap', gap: '6px 18px', marginTop: 10, fontFamily: M, fontSize: 16, color: C.dmuted,
            opacity: interpolate(f, [100, 112], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}>
            {SEG.map(([n, v, col], i) => <span key={i}><span style={{display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: col, marginRight: 6}} />{n} {v}</span>)}
          </div>
        </div>
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12}}>
          {[['You need', '29.8%', '#fff'], ['You win', '~15%', '#FF8A80'], ['Seat 4 river bluffs', '2 of 31', C.mint]].map(([a, b, col], i) => {
            const k = spring({frame: f - 104 - i * 5, fps: 30, config: {damping: 12, stiffness: 220, mass: 0.5}});
            return <div key={i} style={{border: `1px solid ${C.dline}`, borderRadius: 14, padding: '12px 16px', transform: `scale(${k})`, opacity: k}}>
              <div style={{fontFamily: M, fontSize: 15, color: C.dmuted}}>{a.toUpperCase()}</div>
              <div style={{fontFamily: D, fontWeight: 800, fontSize: 38, color: col}}>{b}</div></div>;
          })}
        </div>
        <div style={{fontFamily: B, fontSize: 25, lineHeight: 1.5, color: '#E6E9EE', minHeight: 150}}>
          {PARA.slice(0, typed)}<span style={{opacity: typed < PARA.length && f % 16 < 8 ? 1 : 0, color: C.mint}}>▍</span>
        </div>
        <div style={{display: 'grid', gap: 10, marginTop: 'auto'}}>
          {[['PATTERN', '4th river call below the price tonight. Total cost −18.4 bb.', '#FF8A80', 184], ['FIX', 'Against players who bluff under 20% of rivers, fold one pair to big bets when the draws come in.', C.mint, 196]].map(([a, b, col, d], i) => {
            const k = spring({frame: f - d, fps: 30, config: {damping: 14, stiffness: 200, mass: 0.6}});
            return <div key={i} style={{display: 'flex', gap: 14, alignItems: 'baseline', opacity: k, transform: `translateY(${lerp(k, 20, 0)}px)`}}>
              <span style={{fontFamily: M, fontSize: 16, color: col, minWidth: 80}}>{a}</span><span style={{fontFamily: B, fontSize: 23, color: '#fff'}}>{b}</span></div>;
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const S6 = () => {
  const f = useCurrentFrame();
  const k = interpolate(f, [8, 44], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.cubic)});
  const val = Math.round(1e12 * k);
  const done = f >= 44; const pop = spring({frame: f - 44, fps: 30, config: {damping: 8, stiffness: 300, mass: 0.5}});
  const sub = useSpr(12);
  return (
    <AbsoluteFill style={{background: C.ink, alignItems: 'center', justifyContent: 'center'}}>
      <AbsoluteFill style={{display: 'grid', gridTemplateColumns: 'repeat(48, 1fr)', gap: 6, padding: 30, opacity: 0.55}}>
        {Array.from({length: 48 * 26}).map((_, i) => {
          const on = random(`d${i}`) < k * 1.05;
          return <div key={i} style={{borderRadius: 3, background: on ? (random(`c${i}`) > 0.5 ? C.mint : '#2b6b55') : '#151a21', opacity: on ? 0.9 : 1}} />;
        })}
      </AbsoluteFill>
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at center, rgba(14,17,22,0.96) 30%, rgba(14,17,22,0.4) 75%)'}} />
      <div style={{fontFamily: B, fontSize: 46, color: C.dmuted, opacity: sub}}>Built to learn from</div>
      <div style={{fontFamily: D, fontWeight: 900, fontSize: 176, letterSpacing: -6, color: done ? C.mint : '#fff', fontVariantNumeric: 'tabular-nums',
        transform: `scale(${done ? lerp(pop, 1.25, 1) : 1})`, textShadow: done ? `0 0 70px rgba(59,230,162,0.55)` : 'none'}}>
        {val.toLocaleString('en-US')}{done ? '+' : ''}</div>
      <div style={{fontFamily: D, fontWeight: 700, fontSize: 58, color: '#fff', opacity: sub}}>hands of self-play</div>
      <div style={{position: 'absolute', bottom: 60, fontFamily: M, fontSize: 22, color: C.dmuted, opacity: sub}}>Training target</div>
    </AbsoluteFill>
  );
};

const S7 = () => {
  const f = useCurrentFrame();
  const flash = interpolate(f, [0, 6], [1, 0], {extrapolateRight: 'clamp'});
  const slamA = spring({frame: f - 10, fps: 30, config: {damping: 10, stiffness: 260, mass: 0.6}});
  const slamB = spring({frame: f - 30, fps: 30, config: {damping: 8, stiffness: 300, mass: 0.7}});
  const sh = f >= 30 && f < 44 ? (random(`k${f}`) - 0.5) * 30 * (1 - (f - 30) / 14) : 0;
  const lift = interpolate(f, [64, 84], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const items = [['2017', 'Libratus beats four top pros, heads-up'], ['2019', 'Pluribus beats elite pros at six-max'], ['PokerScribe', 'Training target: 3× the scale of Pluribus']];
  return (
    <AbsoluteFill style={{background: C.ink, transform: `translate(${sh}px, ${sh * 0.6}px)`}}>
      <Grid dark />
      <AbsoluteFill style={{padding: '0 150px', justifyContent: 'center', transform: `translateY(${lerp(lift, 0, -190)}px) scale(${lerp(lift, 1, 0.72)})`, transformOrigin: 'left center'}}>
        <div style={{fontFamily: D, fontWeight: 900, fontSize: 200, letterSpacing: -8, color: '#fff', lineHeight: 0.95,
          opacity: Math.min(1, slamA * 1.5), transform: `translateX(${lerp(slamA, -200, 0)}px)`}}>Built to beat</div>
        <div style={{fontFamily: D, fontWeight: 900, fontSize: 260, letterSpacing: -10, color: C.mint, lineHeight: 0.95,
          opacity: Math.min(1, slamB * 2), transform: `scale(${lerp(slamB, 2.6, 1)})`, transformOrigin: 'left center', textShadow: `0 0 90px rgba(59,230,162,${0.5 * slamB})`}}>the pros.</div>
      </AbsoluteFill>
      <div style={{position: 'absolute', left: 150, right: 150, bottom: 110, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 24}}>
        {items.map(([y, txt], i) => {
          const k = spring({frame: f - 84 - i * 10, fps: 30, config: {damping: 13, stiffness: 200, mass: 0.6}});
          const ours = i === 2; const pulse = ours ? 0.5 + 0.5 * Math.sin((f - 110) / 5) : 0;
          return (
            <div key={i} style={{border: `2px solid ${ours ? C.mint : C.dline}`, borderRadius: 20, padding: '26px 30px', background: ours ? 'rgba(59,230,162,0.08)' : C.dark2,
              transform: `translateY(${lerp(k, 80, 0)}px)`, opacity: k, boxShadow: ours ? `0 0 ${30 + 30 * pulse}px rgba(59,230,162,0.35)` : 'none'}}>
              <div style={{fontFamily: ours ? D : M, fontWeight: ours ? 800 : 500, fontSize: ours ? 40 : 26, color: ours ? C.mint : C.dmuted}}>{y}</div>
              <div style={{fontFamily: D, fontWeight: 700, fontSize: 36, color: '#fff', marginTop: 8, lineHeight: 1.15}}>{txt}</div>
            </div>
          );
        })}
      </div>
      <div style={{position: 'absolute', left: 150, bottom: 50, fontFamily: M, fontSize: 20, color: C.dmuted, opacity: interpolate(f, [110, 125], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}>
        Same family of methods: counterfactual regret minimization and real-time search.
      </div>
      <AbsoluteFill style={{background: '#fff', opacity: flash}} />
    </AbsoluteFill>
  );
};

const S8 = () => {
  const f = useCurrentFrame();
  const a = useSpr(4); const dot = useSpr(16, {damping: 8, stiffness: 260, mass: 0.5}); const b = useSpr(24); const btn = useSpr(32, {damping: 10, stiffness: 220});
  const pulse = 1 + 0.03 * Math.sin(Math.max(0, f - 50) / 5);
  return (
    <AbsoluteFill style={{background: C.bg, alignItems: 'center', justifyContent: 'center'}}>
      <Grid />
      <div style={{display: 'flex', alignItems: 'flex-start', opacity: a, transform: `translateY(${lerp(a, 40, 0)}px)`}}>
        <span style={{fontFamily: D, fontWeight: 800, fontSize: 170, letterSpacing: -6, color: C.ink}}>PokerScribe</span>
        <div style={{width: 36, height: 36, borderRadius: 18, background: C.mint, marginTop: 110, marginLeft: 6, transform: `scale(${dot})`}} />
      </div>
      <div style={{fontFamily: B, fontSize: 46, color: C.muted, marginTop: 6, opacity: b}}>Now, you’ll know it for sure.</div>
      <div style={{marginTop: 50, background: C.ink, color: '#fff', fontFamily: B, fontWeight: 600, fontSize: 40, padding: '24px 54px', borderRadius: 18,
        transform: `scale(${btn * pulse})`}}>Join the waitlist</div>
      <div style={{position: 'absolute', bottom: 50, fontFamily: M, fontSize: 22, color: C.muted, opacity: b}}>AI poker coaching · Coaching beta in development · No real-money play</div>
    </AbsoluteFill>
  );
};


// Sound: Remotion's sound library (remotion.media) plus an optional music file in public/
const SND = (n) => `https://remotion.media/${n}.wav`;
const starts = (() => { const out = []; let a = 0; timeline.scenes.forEach((d, i) => { out.push(a); a += d - timeline.trans; }); return out; })();
const CUES = [
  ...starts.slice(1).map((st, i) => [st - 6, i === 5 ? null : 'whoosh', 0.55]),
  [24, 'whip', 0.6], [starts[1] + 26, 'ding', 0.35],
  ...[18, 21, 26, 30, 34, 38, 42, 46, 50].map((f) => [starts[2] + f, 'mouse-click', 0.25]),
  ...[84, 94, 104].map((f) => [starts[2] + f, 'switch', 0.45]),
  ...[0, 1, 2, 3, 4, 5].map((i) => [starts[3] + 34 + i * 9, 'mouse-click', 0.3]),
  [starts[3] + 126, 'dramatic-boomer', 0.8],
  ...[0, 1, 2, 3].map((i) => [starts[4] + 14 + i * 14, 'switch', 0.35]),
  [starts[4] + 184, 'ding', 0.35],
  [starts[5] + 44, 'ding', 0.5],
  [starts[6] + 8, 'whip', 0.7], [starts[6] + 28, 'dramatic-boomer', 1.0],
  ...[84, 94, 104].map((f) => [starts[6] + f, 'switch', 0.4]),
  [starts[7] + 16, 'ding', 0.4],
].filter((c) => c[1]);
const Sound = () => {
  const {sfx = true, music = null, musicVolume = 0.35, narration = null, narrationVolume = 1} = getInputProps();
  return (
    <>
      {music && <Audio src={staticFile(music)} volume={(f) => musicVolume * Math.min(1, f / 15)} />}
      {narration && <Audio src={staticFile(narration)} volume={narrationVolume} />}
      {sfx && CUES.map(([at, name, vol], i) => (
        <Sequence key={i} from={Math.max(0, Math.round(at))} durationInFrames={90}><Audio src={SND(name)} volume={vol} /></Sequence>
      ))}
    </>
  );
};

const T = timeline.trans;
const tr = (p) => <TransitionSeries.Transition presentation={p} timing={springTiming({config: {damping: 200}, durationInFrames: T})} />;
const Video = () => {
  const s = timeline.scenes;
  const comps = [S1, S2, S3, S4, S5, S6, S7, S8];
  const pres = [wipe({direction: 'from-left'}), slide({direction: 'from-bottom'}), wipe({direction: 'from-right'}), slide({direction: 'from-right'}),
    slide({direction: 'from-left'}), fade(), slide({direction: 'from-bottom'})];
  return (
    <AbsoluteFill>
      <style>{fontCss}</style>
      <TransitionSeries>
        {comps.map((Comp, i) => (
          <React.Fragment key={i}>
            <TransitionSeries.Sequence durationInFrames={s[i]}><Comp /></TransitionSeries.Sequence>
            {i < comps.length - 1 && tr(pres[i])}
          </React.Fragment>
        ))}
      </TransitionSeries>
      <Sound />
    </AbsoluteFill>
  );
};
const total = timeline.scenes.reduce((a, b) => a + b, 0) - timeline.trans * (timeline.scenes.length - 1);
registerRoot(() => (
  <>
    <Composition id="Demo" component={Video} durationInFrames={total} fps={30} width={1920} height={1080} />
  </>
));
