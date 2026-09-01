import { useState, useEffect, useRef, createContext, useContext, useCallback } from "react";

/* ============================================================
   KIRA — AI Money Butler
   Interactive prototype. Money is integer sen throughout.
   Motion: orchestrated boot, scroll-linked parallax, spring
   page transitions, digit odometer, ambient drift.
   ============================================================ */

const STYLES = `
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Newsreader:ital,opsz,wght@0,6..72,400;1,6..72,400;1,6..72,500&display=swap');

.kira-root{
  --paper:#EDEFEB;
  --surface:#FBFCFA;
  --ink:#0F1C1A;
  --ink-2:#193029;
  --ink-3:#2F4A44;
  --muted:#61756F;
  --muted-2:#8C9C96;
  --line:rgba(15,28,26,0.09);
  --line-2:rgba(15,28,26,0.16);
  --brass:#A9853F;
  --brass-lit:#C9A45C;
  --jade:#2C6B57;
  --clay:#9A4A3B;
  --shadow-sm:0 1px 2px rgba(15,28,26,.05), 0 4px 14px -8px rgba(15,28,26,.16);
  --shadow-md:0 2px 6px rgba(15,28,26,.06), 0 18px 40px -22px rgba(15,28,26,.34);
  --spring:cubic-bezier(.22,1,.36,1);
  --spring-2:cubic-bezier(.16,1.3,.3,1);
  --sy:0;

  font-family:'Manrope',system-ui,sans-serif;
  font-feature-settings:'tnum' 1;
  -webkit-font-smoothing:antialiased;
  color:var(--ink);
  min-height:100%;
  background:
    radial-gradient(120% 90% at 78% -8%, #F4F5F1 0%, rgba(244,245,241,0) 58%),
    radial-gradient(90% 80% at 10% 110%, #DFE4DD 0%, rgba(223,228,221,0) 62%),
    #E7EAE5;
  display:flex; flex-direction:column; align-items:center;
  padding:34px 20px 46px;
  box-sizing:border-box;
}
.kira-root *{box-sizing:border-box;}
.kira-root button{font-family:inherit;cursor:pointer;border:none;background:none;color:inherit;}
.kira-root :focus-visible{outline:2px solid var(--brass);outline-offset:2px;border-radius:6px;}

/* ---------- stage ---------- */
.stage-head{width:100%;max-width:392px;display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:20px;gap:14px;}
.lockup b{font-size:15px;font-weight:800;letter-spacing:.24em;text-transform:uppercase;display:block;}
.lockup span{font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted-2);font-weight:600;}
.replay{font-size:11px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:var(--muted-2);
  display:flex;align-items:center;gap:7px;transition:color .3s;}
.replay:hover{color:var(--ink);}
.replay i{width:5px;height:5px;border-radius:50%;background:var(--brass);display:block;
  animation:pulseDot 2.6s ease-in-out infinite;}
@keyframes pulseDot{0%,100%{opacity:.35;transform:scale(1);}50%{opacity:1;transform:scale(1.5);}}

/* ---------- device ---------- */
.device{
  width:390px;max-width:100%;height:820px;position:relative;
  border-radius:46px;padding:9px;
  background:linear-gradient(150deg,#303433 0%,#080A09 30%,#000 68%,#292D2B 100%);
  box-shadow:0 40px 90px -34px rgba(15,28,26,.65), 0 1px 0 rgba(255,255,255,.22) inset,
    0 0 0 1px rgba(0,0,0,.78);
  animation:deviceIn 1.1s var(--spring) both;
}
@keyframes deviceIn{from{opacity:0;transform:translateY(26px) scale(.965);}to{opacity:1;transform:none;}}

.screen{position:relative;height:100%;width:100%;border-radius:38px;overflow:hidden;display:flex;flex-direction:column;isolation:isolate;}
.screen::before,.screen::after{content:'';position:absolute;inset:0;z-index:-2;}
.screen::before{background:var(--paper);}
.screen::after{background:linear-gradient(178deg,#162924 0%,var(--ink) 58%);opacity:0;transition:opacity .62s var(--spring);}
.screen.dim::after{opacity:1;}

/* ambient drift layer */
.motes{position:absolute;inset:0;z-index:-1;pointer-events:none;overflow:hidden;opacity:0;transition:opacity .8s ease;}
.screen.dim .motes{opacity:1;}
.mote{position:absolute;border-radius:50%;background:radial-gradient(circle,rgba(201,164,92,.5),rgba(201,164,92,0) 70%);
  will-change:transform;}
@keyframes drift{
  0%{transform:translate3d(0,0,0) scale(1);}
  33%{transform:translate3d(14px,-26px,0) scale(1.14);}
  66%{transform:translate3d(-11px,-46px,0) scale(.92);}
  100%{transform:translate3d(0,-72px,0) scale(1);}
}

.statusbar{height:42px;flex:none;display:flex;align-items:flex-start;justify-content:space-between;padding:11px 19px 0;
  font-size:12px;font-weight:700;color:var(--ink);position:relative;z-index:30;transition:color .5s ease;}
.screen.dim .statusbar{color:#E9EDE9;}
.status-time,.status-icons{position:relative;z-index:2;}
.status-icons{display:flex;gap:6px;align-items:center;height:13px;}
.device-notch{position:absolute;z-index:1;left:50%;top:0;width:202px;height:31px;transform:translateX(-50%);
  display:flex;align-items:center;justify-content:center;gap:11px;background:#030403;border-radius:0 0 19px 19px;
  box-shadow:0 1px 0 rgba(255,255,255,.04) inset,0 1px 2px rgba(0,0,0,.18);}
.notch-speaker{width:48px;height:5px;border-radius:999px;background:#1B1E1D;
  box-shadow:0 1px 1px rgba(255,255,255,.06) inset;}
.notch-camera{width:8px;height:8px;border-radius:50%;background:radial-gradient(circle at 62% 38%,#22496A 0 10%,#10293D 24%,#080E12 58%,#010202 72%);
  box-shadow:0 0 0 1px #111514,0 0 4px rgba(41,91,132,.35) inset;}
.sb-signal{height:12px;display:flex;gap:2px;align-items:flex-end;}
.sb-signal i{width:2.5px;border-radius:1px;background:currentColor;display:block;}
.sb-signal i:nth-child(1){height:4px}.sb-signal i:nth-child(2){height:7px}
.sb-signal i:nth-child(3){height:10px}.sb-signal i:nth-child(4){height:12px}
.sb-wifi{width:16px;height:13px;overflow:visible;fill:currentColor;stroke:currentColor;stroke-width:1.8;
  stroke-linecap:round;fill:none;}
.sb-wifi circle{fill:currentColor;stroke:none;}
.sb-batt{width:20px;height:10px;border:1.3px solid currentColor;border-radius:3px;position:relative;display:block;}
.sb-batt::after{content:'';position:absolute;right:-3px;top:2px;width:1.5px;height:4px;border-radius:0 1px 1px 0;background:currentColor;opacity:.55;}
.sb-batt i{position:absolute;inset:1.5px;background:currentColor;border-radius:1px;display:block;}

.viewport{flex:1;overflow-y:auto;overflow-x:hidden;scrollbar-width:none;position:relative;}
.viewport::-webkit-scrollbar{display:none;}
.pad{padding:4px 22px 132px;}

/* ---------- page transition ---------- */
.page{animation:pageIn .58s var(--spring) both;transform-origin:50% 30%;}
@keyframes pageIn{
  from{opacity:0;filter:blur(7px);transform:translate3d(calc(var(--dir,0) * 22px),12px,0) scale(.975);}
  60%{filter:blur(0);}
  to{opacity:1;filter:blur(0);transform:none;}
}

/* ---------- scroll reveal ---------- */
.rv{opacity:0;transform:translate3d(0,20px,0) scale(.985);filter:blur(5px);
  transition:opacity .72s var(--spring), transform .72s var(--spring), filter .6s ease;will-change:transform,opacity;}
.rv.in{opacity:1;transform:none;filter:blur(0);}

/* ---------- boot ---------- */
.boot{position:absolute;inset:0;z-index:60;display:grid;place-items:center;background:var(--ink);
  animation:bootOut .9s var(--spring) 1.55s both;}
@keyframes bootOut{to{opacity:0;transform:scale(1.09);visibility:hidden;}}
.boot-mark{display:flex;gap:.20em;font-size:30px;font-weight:800;letter-spacing:.3em;color:#EDF1ED;padding-left:.3em;}
.boot-mark span{display:block;animation:letterUp .82s var(--spring) both;}
@keyframes letterUp{from{opacity:0;transform:translateY(22px) rotate(4deg);filter:blur(9px);}to{opacity:1;transform:none;filter:blur(0);}}
.boot-rule{height:1px;width:0;background:linear-gradient(90deg,transparent,var(--brass-lit),transparent);margin-top:16px;
  animation:ruleOut 1s var(--spring) .5s both;}
@keyframes ruleOut{to{width:190px;}}
.boot-sub{margin-top:13px;font-size:10px;letter-spacing:.28em;text-transform:uppercase;color:rgba(233,237,233,.42);
  animation:fadeUp .8s var(--spring) .78s both;}
@keyframes fadeUp{from{opacity:0;transform:translateY(9px);}to{opacity:1;transform:none;}}

/* ---------- type ---------- */
.eyebrow{font-size:10px;font-weight:700;letter-spacing:.19em;text-transform:uppercase;color:var(--muted-2);}
.eyebrow.on-ink{color:rgba(233,237,233,.5);}
.voice{font-family:'Newsreader',serif;font-style:italic;line-height:1.5;}
.money{font-variant-numeric:tabular-nums;letter-spacing:-.03em;font-weight:800;}
.rm{font-size:.48em;font-weight:700;letter-spacing:.04em;vertical-align:.42em;margin-right:.16em;color:var(--brass-lit);}

/* ---------- odometer ---------- */
.od{display:inline-flex;align-items:flex-end;font-variant-numeric:tabular-nums;letter-spacing:-.03em;font-weight:800;}
.od .rm{align-self:flex-start;margin-top:.06em;}
.od-col{display:inline-block;overflow:hidden;height:1em;line-height:1;}
.od-track{display:block;transition:transform .95s var(--spring);will-change:transform;}
.od-track u{display:block;height:1em;line-height:1;text-decoration:none;}
.od-fix{display:inline-block;height:1em;line-height:1;}

/* ---------- cards ---------- */
.card{background:var(--surface);border-radius:22px;padding:18px;box-shadow:var(--shadow-sm);border:1px solid rgba(255,255,255,.9);}
.card-flat{background:rgba(255,255,255,.55);border:1px solid var(--line);border-radius:20px;padding:16px;}
.tapp{transition:transform .34s var(--spring), box-shadow .34s var(--spring);}
.tapp:active{transform:scale(.977);}

.topbar{padding:10px 22px 16px;display:flex;align-items:flex-start;justify-content:space-between;gap:12px;}
.topbar h1{margin:2px 0 0;font-size:25px;font-weight:800;letter-spacing:-.035em;transition:color .5s ease;}
.pill{display:inline-flex;align-items:center;gap:6px;padding:6px 11px;border-radius:100px;font-size:10.5px;font-weight:700;
  letter-spacing:.05em;text-transform:uppercase;background:rgba(15,28,26,.055);color:var(--ink-3);}
.pill .dot{width:6px;height:6px;border-radius:50%;background:var(--jade);animation:pulseDot 2.8s ease-in-out infinite;}
.pill.warn{background:rgba(154,74,59,.1);color:var(--clay);} .pill.warn .dot{background:var(--clay);}

.rowlink{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;padding:15px 0;
  border-bottom:1px solid var(--line);text-align:left;transition:padding-left .3s var(--spring);}
.rowlink:last-child{border-bottom:none;}
.rowlink:hover{padding-left:5px;}
.rowlink svg{transition:transform .3s var(--spring);}
.rowlink:hover svg{transform:translateX(3px);}

.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:46px;padding:0 20px;border-radius:14px;
  font-size:14px;font-weight:700;letter-spacing:-.01em;position:relative;overflow:hidden;
  transition:transform .28s var(--spring-2), background .25s ease, opacity .2s;}
.btn:active{transform:scale(.955);}
.btn::after{content:'';position:absolute;top:0;bottom:0;width:44%;left:-60%;
  background:linear-gradient(100deg,transparent,rgba(255,255,255,.22),transparent);transform:skewX(-18deg);}
.btn:hover::after{animation:sheen .85s ease;}
@keyframes sheen{to{left:130%;}}
.btn-primary{background:var(--ink);color:#F3F6F2;}
.btn-ghost{background:rgba(15,28,26,.06);color:var(--ink);}
.btn-brass{background:var(--brass);color:#1A1508;}
.btn-line{border:1px solid var(--line-2);color:var(--ink);}
.btn-sm{height:36px;padding:0 14px;font-size:12.5px;border-radius:11px;}

/* ---------- claim line ---------- */
.claim{display:flex;height:40px;border-radius:11px;overflow:hidden;gap:3px;
  background:rgba(6,13,12,.6);border:1px solid rgba(233,237,233,.16);padding:3px;}
.claim-seg{position:relative;flex-basis:0;min-width:14px;overflow:hidden;border-radius:6px;
  box-shadow:0 1px 0 rgba(255,255,255,.2) inset;
  transition:flex-grow .9s var(--spring), opacity .35s ease;cursor:pointer;
  animation:segGrow .9s var(--spring) both;transform-origin:left center;}
@keyframes segGrow{from{transform:scaleX(0);}to{transform:none;}}
.seg-free{background:linear-gradient(180deg,#FBF7EC,#DFCFA4);box-shadow:0 0 0 1px rgba(201,164,92,.8) inset;}
.seg-free::after{content:'';position:absolute;inset:0;left:-70%;width:55%;
  background:linear-gradient(100deg,transparent,rgba(255,255,255,.9),transparent);transform:skewX(-16deg);
  animation:thread 4.6s ease-in-out 1.2s infinite;}
@keyframes thread{0%{left:-70%;}45%,100%{left:150%;}}
.seg-goal{background:linear-gradient(180deg,#E0BB74,#B58F45);}
.seg-commit{background:linear-gradient(180deg,#7FA298,#5B7C74);}
.seg-buffer{background:#43635C;
  background-image:repeating-linear-gradient(115deg,rgba(240,245,240,.4) 0 1.6px,transparent 1.6px 7px);}
.claim-legend{display:grid;grid-template-columns:1fr 1fr;gap:9px 14px;margin-top:15px;}
.leg{display:flex;align-items:flex-start;gap:8px;text-align:left;width:100%;padding:2px 0;
  transition:opacity .3s ease, transform .3s var(--spring);}
.leg:active{transform:scale(.97);}
.leg i{width:10px;height:10px;border-radius:3px;flex:none;margin-top:4px;box-shadow:0 0 0 1px rgba(233,237,233,.18);}
.leg-l{font-size:11px;font-weight:600;color:rgba(233,237,233,.62);display:block;}
.leg-v{font-size:13.5px;font-weight:700;font-variant-numeric:tabular-nums;color:#EDF1ED;letter-spacing:-.02em;}

/* ---------- hero ---------- */
.hero{background:linear-gradient(168deg,var(--ink-2) 0%,var(--ink) 62%);color:#EDF1ED;border-radius:26px;padding:22px;
  box-shadow:var(--shadow-md);position:relative;overflow:hidden;}
.hero::after{content:'';position:absolute;top:-70px;right:-60px;width:210px;height:210px;border-radius:50%;
  background:radial-gradient(circle,rgba(201,164,92,.22),rgba(201,164,92,0) 68%);pointer-events:none;
  animation:halo 9s ease-in-out infinite alternate;}
@keyframes halo{from{transform:translate3d(0,0,0) scale(1);opacity:.75;}to{transform:translate3d(-24px,26px,0) scale(1.22);opacity:1;}}
.hero-parallax{transform:translate3d(0,calc(var(--sy) * -0.09px),0) scale(calc(1 - var(--sy) * 0.00007));
  transform-origin:50% 0;will-change:transform;}
.flash-sweep{position:absolute;inset:0;border-radius:26px;pointer-events:none;z-index:2;
  background:linear-gradient(120deg,transparent 30%,rgba(201,164,92,.30),transparent 70%);
  animation:flashSweep 1.1s ease-out both;}
@keyframes flashSweep{from{opacity:0;transform:translateX(-40%);}30%{opacity:1;}to{opacity:0;transform:translateX(40%);}}

.maths{margin-top:16px;border-top:1px solid rgba(233,237,233,.14);padding-top:13px;overflow:hidden;}
.maths-row{display:flex;justify-content:space-between;align-items:baseline;padding:5.5px 0;font-size:12.5px;
  color:rgba(233,237,233,.66);animation:rowIn .5s var(--spring) both;}
@keyframes rowIn{from{opacity:0;transform:translateX(-12px);}to{opacity:1;transform:none;}}
.maths-row b{font-variant-numeric:tabular-nums;font-weight:600;color:#E3E9E3;}
.maths-row.total{border-top:1px solid rgba(233,237,233,.14);margin-top:6px;padding-top:10px;color:#EDF1ED;font-weight:700;}
.maths-row.total b{color:var(--brass-lit);font-weight:800;}

/* ---------- nav ---------- */
.nav{position:absolute;left:0;right:0;bottom:0;height:96px;display:flex;align-items:flex-start;justify-content:space-between;
  padding:11px 20px 0;backdrop-filter:blur(12px);z-index:20;}
.nav::before,.nav::after{content:'';position:absolute;inset:0;z-index:-1;}
.nav::before{background:linear-gradient(180deg,rgba(237,239,235,0),rgba(237,239,235,.94) 32%,var(--paper) 62%);}
.nav::after{background:linear-gradient(180deg,rgba(15,28,26,0),rgba(15,28,26,.93) 34%,var(--ink) 62%);
  opacity:0;transition:opacity .62s var(--spring);}
.screen.dim .nav::after{opacity:1;}
.nav-item{flex:1;display:flex;flex-direction:column;align-items:center;gap:5px;padding-top:10px;color:var(--muted-2);
  transition:color .4s ease, transform .4s var(--spring-2);}
.nav-item svg{transition:transform .45s var(--spring-2);}
.nav-item.active{color:var(--ink);}
.nav-item.active svg{transform:translateY(-2px) scale(1.1);}
.nav-item:active{transform:scale(.9);}
.screen.dim .nav-item{color:rgba(233,237,233,.42);}
.screen.dim .nav-item.active{color:#EDF1ED;}
.nav-item span{font-size:9.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;}
.nav-dot{width:4px;height:4px;border-radius:50%;background:var(--brass);margin-top:-2px;
  animation:dotIn .5s var(--spring-2) both;}
@keyframes dotIn{from{transform:scale(0);}to{transform:scale(1);}}

.nav-butler{flex:none;width:60px;display:flex;flex-direction:column;align-items:center;gap:6px;margin-top:-19px;}
.butler-orb{width:56px;height:56px;border-radius:20px;display:grid;place-items:center;
  background:linear-gradient(165deg,var(--ink-3),var(--ink));color:var(--brass-lit);
  box-shadow:0 10px 24px -8px rgba(15,28,26,.6), 0 0 0 3px var(--paper);
  transition:transform .4s var(--spring-2), background .5s ease, color .5s ease, box-shadow .5s ease;
  animation:levitate 5.4s ease-in-out infinite;}
@keyframes levitate{0%,100%{transform:translateY(0);}50%{transform:translateY(-4.5px);}}
.butler-orb svg{animation:spinSlow 22s linear infinite;}
@keyframes spinSlow{to{transform:rotate(360deg);}}
.nav-butler:active .butler-orb{transform:scale(.9);}
.nav-butler.active .butler-orb{background:linear-gradient(165deg,var(--brass-lit),var(--brass));color:#17130A;
  box-shadow:0 12px 30px -8px rgba(201,164,92,.55), 0 0 0 3px var(--ink);animation:none;transform:translateY(-2px);}
.nav-butler span{font-size:9.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--muted-2);transition:color .4s;}
.screen.dim .nav-butler span{color:#EDF1ED;}

/* ---------- butler ---------- */
.bubble-user{align-self:flex-end;max-width:80%;background:rgba(233,237,233,.1);border:1px solid rgba(233,237,233,.14);
  padding:11px 15px;border-radius:17px 17px 5px 17px;font-size:14px;font-weight:500;line-height:1.45;color:#E9EDE9;
  animation:userIn .5s var(--spring-2) both;transform-origin:100% 100%;}
@keyframes userIn{from{opacity:0;transform:translateY(14px) scale(.9);}to{opacity:1;transform:none;}}
.bubble-kira{max-width:92%;}
.kira-say{font-family:'Newsreader',serif;font-style:italic;font-size:19px;line-height:1.42;color:#F1F4F0;margin:0;}
.kira-say w{display:inline-block;animation:wordIn .62s var(--spring) both;}
@keyframes wordIn{from{opacity:0;transform:translateY(10px);filter:blur(6px);}to{opacity:1;transform:none;filter:blur(0);}}
.kira-sub{font-size:13.5px;line-height:1.55;color:rgba(233,237,233,.72);margin-top:9px;
  animation:fadeUp .7s var(--spring) .42s both;}
.thinking{display:inline-flex;gap:5px;align-items:center;padding:4px 0;}
.thinking i{width:5px;height:5px;border-radius:50%;background:var(--brass-lit);animation:think 1.25s ease-in-out infinite;}
.thinking i:nth-child(2){animation-delay:.16s}.thinking i:nth-child(3){animation-delay:.32s}
@keyframes think{0%,100%{opacity:.25;transform:translateY(0);}50%{opacity:1;transform:translateY(-4px);}}
.evidence{margin-top:13px;padding-left:12px;display:flex;flex-direction:column;gap:7px;position:relative;}
.evidence::before{content:'';position:absolute;left:0;top:0;width:1.5px;height:100%;background:rgba(201,164,92,.5);
  transform-origin:top;animation:lineDraw .7s var(--spring) .5s both;}
@keyframes lineDraw{from{transform:scaleY(0);}to{transform:scaleY(1);}}
.ev-row{display:flex;justify-content:space-between;gap:12px;font-size:12px;animation:rowIn .5s var(--spring) both;}
.ev-row span{color:rgba(233,237,233,.55);}
.ev-row b{font-weight:700;font-variant-numeric:tabular-nums;color:#E7ECE7;}
.approval{margin-top:14px;background:rgba(233,237,233,.055);border:1px solid rgba(201,164,92,.34);border-radius:18px;padding:15px;
  animation:approvalIn .75s var(--spring-2) .7s both;}
@keyframes approvalIn{from{opacity:0;transform:translateY(22px) scale(.94);}to{opacity:1;transform:none;}}
.scenario{width:100%;text-align:left;padding:12px;border-radius:13px;border:1px solid rgba(233,237,233,.13);margin-top:9px;
  transition:border-color .3s, background .3s, transform .3s var(--spring);}
.scenario:active{transform:scale(.985);}
.scenario.sel{border-color:var(--brass-lit);background:rgba(201,164,92,.11);}
.chips{display:flex;gap:8px;flex-wrap:wrap;}
.chip{padding:9px 13px;border-radius:100px;border:1px solid rgba(233,237,233,.17);font-size:12.5px;font-weight:600;
  color:rgba(233,237,233,.85);transition:.25s var(--spring);animation:rise .6s var(--spring) both;}
.chip:hover{background:rgba(233,237,233,.09);border-color:rgba(201,164,92,.5);}
.chip:active{transform:scale(.95);}
.composer{position:absolute;left:16px;right:16px;bottom:104px;display:flex;gap:7px;align-items:center;z-index:22;
  background:rgba(32,56,49,.92);border:1px solid rgba(233,237,233,.28);border-radius:16px;padding:6px 6px 6px 15px;
  backdrop-filter:blur(14px);box-shadow:0 14px 34px -18px rgba(0,0,0,.9);
  animation:rise .7s var(--spring) .3s both;transition:border-color .3s;}
.composer:focus-within{border-color:#E0BB74;}
.composer input{flex:1;min-width:0;background:none;border:none;outline:none;color:#F4F7F3;font-family:inherit;font-size:14px;padding:11px 0;}
.composer input::placeholder{color:rgba(240,245,240,.58);}
.send{width:38px;height:38px;border-radius:12px;background:#E0BB74;color:#101C1A;
  display:grid;place-items:center;flex:none;box-shadow:0 4px 16px -4px rgba(224,187,116,.7);
  transition:transform .3s var(--spring-2), box-shadow .3s;}
.send:active{transform:scale(.88) rotate(-8deg);}

/* ---------- drafts ---------- */
.draft{border-radius:20px;padding:16px;background:var(--surface);border:1px solid rgba(201,164,92,.4);
  box-shadow:var(--shadow-sm);position:relative;overflow:hidden;transition:opacity .45s ease, transform .45s var(--spring), margin .45s var(--spring);}
.draft.leaving{opacity:0;transform:translateX(38px) scale(.94);}
.draft::before{content:'';position:absolute;left:0;top:18px;bottom:18px;width:2.5px;background:var(--brass);border-radius:0 3px 3px 0;}
.conf{height:3px;border-radius:2px;background:rgba(15,28,26,.09);overflow:hidden;margin-top:9px;}
.conf i{display:block;height:100%;background:var(--brass);border-radius:2px;transform-origin:left;
  animation:confFill 1.1s var(--spring) .25s both;}
@keyframes confFill{from{transform:scaleX(0);}to{transform:scaleX(1);}}
.txn{display:flex;align-items:center;gap:13px;padding:13px 0;border-bottom:1px solid var(--line);}
.txn:last-child{border-bottom:none;}
.txn-ic{width:36px;height:36px;border-radius:12px;background:rgba(15,28,26,.055);display:grid;place-items:center;flex:none;color:var(--ink-3);}
.tag{font-size:9.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted-2);}

/* ---------- options ---------- */
.opt{width:100%;text-align:left;border-radius:20px;padding:16px;background:var(--surface);border:1.5px solid transparent;
  box-shadow:var(--shadow-sm);transition:transform .4s var(--spring), border-color .35s, box-shadow .4s var(--spring);
  transform-style:preserve-3d;}
.opt.sel{border-color:var(--brass);box-shadow:0 0 0 4px rgba(201,164,92,.14),var(--shadow-md);}
.meter{display:flex;gap:3px;margin-top:11px;}
.meter i{height:5px;flex:1;border-radius:3px;background:rgba(15,28,26,.08);transform-origin:bottom;
  animation:barPop .45s var(--spring-2) both;}
@keyframes barPop{from{transform:scaleY(.2);opacity:0;}to{transform:none;opacity:1;}}
.meter i.on{background:var(--brass);}
.meter i.hot{background:var(--clay);}

.ringwrap{position:relative;flex:none;}
.ringwrap figcaption{position:absolute;inset:0;display:grid;place-items:center;text-align:center;}

/* ---------- toast ---------- */
.toast{position:absolute;left:20px;right:20px;bottom:112px;background:var(--ink);color:#EDF1ED;border-radius:16px;
  padding:13px 16px;font-size:13px;font-weight:600;display:flex;gap:10px;align-items:center;box-shadow:var(--shadow-md);
  z-index:40;overflow:hidden;animation:toastIn .55s var(--spring-2);}
@keyframes toastIn{from{opacity:0;transform:translateY(22px) scale(.93);}to{opacity:1;transform:none;}}
.toast::after{content:'';position:absolute;left:0;bottom:0;height:2px;background:var(--brass);width:100%;
  transform-origin:left;animation:toastBar 3.4s linear forwards;}
@keyframes toastBar{from{transform:scaleX(1);}to{transform:scaleX(0);}}
.toast .tick{color:var(--brass-lit);display:grid;place-items:center;animation:tickPop .55s var(--spring-2) .1s both;}
@keyframes tickPop{from{transform:scale(0) rotate(-25deg);}to{transform:none;}}

/* ---------- misc motion ---------- */
@keyframes rise{from{opacity:0;transform:translateY(13px);}to{opacity:1;transform:none;}}
.seg-toggle{position:relative;display:flex;gap:5px;background:rgba(15,28,26,.055);padding:4px;border-radius:14px;}
.seg-thumb{position:absolute;top:4px;bottom:4px;width:calc(50% - 6px);border-radius:11px;background:var(--surface);
  box-shadow:var(--shadow-sm);transition:transform .48s var(--spring-2);}
.seg-btn{position:relative;flex:1;height:36px;border-radius:11px;font-size:12.5px;font-weight:700;color:var(--muted);
  transition:color .3s;z-index:1;}
.seg-btn.on{color:var(--ink);}
.switch{width:46px;height:27px;border-radius:100px;flex:none;position:relative;transition:background .35s var(--spring);}
.switch i{position:absolute;top:3px;width:21px;height:21px;border-radius:50%;background:#fff;
  box-shadow:0 1px 3px rgba(0,0,0,.24);transition:left .42s var(--spring-2), width .25s var(--spring);}
.switch:active i{width:26px;}

/* ---------- capture sheets ---------- */
.scrim{position:absolute;inset:0;z-index:50;background:rgba(6,14,13,.62);backdrop-filter:blur(10px);
  animation:fadeIn .42s ease both;}
@keyframes fadeIn{from{opacity:0;}to{opacity:1;}}
.sheet{position:absolute;left:0;right:0;bottom:0;z-index:51;max-height:90%;overflow-y:auto;scrollbar-width:none;
  background:linear-gradient(180deg,#1C332C 0%,#0F1C1A 62%);border-radius:30px 30px 0 0;
  border-top:1px solid rgba(201,164,92,.3);padding:12px 20px 26px;color:#E9EDE9;
  box-shadow:0 -30px 70px -34px rgba(0,0,0,.85);animation:sheetUp .62s var(--spring-2) both;}
.sheet::-webkit-scrollbar{display:none;}
@keyframes sheetUp{from{transform:translateY(101%);}to{transform:none;}}
.grab{width:38px;height:4px;border-radius:3px;background:rgba(233,237,233,.22);margin:0 auto 16px;}
.sheet-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px;}
.xbtn{width:32px;height:32px;border-radius:11px;background:rgba(233,237,233,.08);display:grid;place-items:center;
  color:rgba(233,237,233,.7);transition:transform .3s var(--spring-2), background .25s;}
.xbtn:active{transform:scale(.88);}

/* voice */
.mic-stage{position:relative;display:grid;place-items:center;padding:14px 0 6px;}
.mic-glow{position:absolute;width:210px;height:210px;border-radius:50%;pointer-events:none;
  background:radial-gradient(circle,rgba(201,164,92,.26),rgba(201,164,92,0) 66%);
  transition:transform .12s linear, opacity .3s;}
.mic-ring{position:absolute;width:132px;height:132px;border-radius:50%;border:1px solid rgba(201,164,92,.32);
  animation:ripple 2.9s ease-out infinite;}
.mic-ring:nth-of-type(2){animation-delay:.95s;}
.mic-ring:nth-of-type(3){animation-delay:1.9s;}
@keyframes ripple{0%{transform:scale(.62);opacity:.85;}100%{transform:scale(1.5);opacity:0;}}
.wave{position:relative;display:flex;align-items:center;justify-content:center;gap:3px;height:92px;width:100%;}
.wave i{width:3px;height:100%;border-radius:2px;background:linear-gradient(180deg,var(--brass-lit),var(--brass));
  transform:scaleY(.06);transform-origin:center;transition:transform .085s linear;}
.timer{font-variant-numeric:tabular-nums;font-size:12px;font-weight:700;letter-spacing:.14em;
  color:rgba(233,237,233,.55);text-align:center;margin:6px 0 0;}
.tscript{font-family:'Newsreader',serif;font-style:italic;font-size:21px;line-height:1.46;color:#F1F4F0;
  min-height:64px;margin:20px 0 0;}
.tscript w{display:inline-block;animation:wordIn .5s var(--spring) both;}
.tscript w.unsure{border-bottom:1.5px dotted var(--brass-lit);color:var(--brass-lit);cursor:pointer;}
.caret{display:inline-block;width:9px;height:19px;background:var(--brass-lit);vertical-align:-3px;margin-left:3px;
  animation:blink 1.05s steps(2,start) infinite;}
@keyframes blink{50%{opacity:0;}}
.intent{display:inline-flex;align-items:center;gap:7px;padding:6px 12px;border-radius:100px;
  background:rgba(201,164,92,.14);border:1px solid rgba(201,164,92,.34);color:var(--brass-lit);
  font-size:10.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
  animation:approvalIn .6s var(--spring-2) both;}

/* scan */
.pick-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.pick{display:flex;flex-direction:column;gap:11px;align-items:flex-start;padding:16px;border-radius:18px;
  background:rgba(233,237,233,.06);border:1px solid rgba(233,237,233,.14);text-align:left;color:#E9EDE9;
  transition:transform .32s var(--spring-2), border-color .3s, background .3s;}
.pick:hover{border-color:rgba(201,164,92,.5);background:rgba(201,164,92,.08);}
.pick:active{transform:scale(.965);}
.pick b{font-size:13.5px;letter-spacing:-.01em;}
.pick span{font-size:11.5px;color:rgba(233,237,233,.5);line-height:1.4;}
.scanframe{position:relative;height:252px;border-radius:20px;overflow:hidden;background:#0A1412;
  display:grid;place-items:center;border:1px solid rgba(233,237,233,.1);}
.scanframe img{width:100%;height:100%;object-fit:cover;}
.laser{position:absolute;left:0;right:0;height:130px;pointer-events:none;
  background:linear-gradient(180deg,transparent,rgba(201,164,92,.30) 78%,rgba(201,164,92,.9) 100%);
  animation:laser 1.75s cubic-bezier(.5,0,.5,1) infinite;}
@keyframes laser{0%{top:-130px;}100%{top:100%;}}
.brk{position:absolute;width:26px;height:26px;border:2px solid var(--brass-lit);pointer-events:none;
  animation:brkIn .55s var(--spring-2) both;}
@keyframes brkIn{from{opacity:0;transform:scale(1.7);}to{opacity:1;transform:none;}}
.receipt{width:150px;background:#F3F1E9;border-radius:3px;padding:14px 13px 20px;color:#2B2A26;
  font-size:8px;line-height:1.75;letter-spacing:.04em;font-weight:600;
  clip-path:polygon(0 0,100% 0,100% 97%,92% 100%,83% 97%,75% 100%,66% 97%,58% 100%,49% 97%,41% 100%,32% 97%,24% 100%,15% 97%,7% 100%,0 97%);
  animation:rise .6s var(--spring) both;}
.receipt hr{border:none;border-top:1px dashed rgba(43,42,38,.35);margin:7px 0;}
.receipt .r-row{display:flex;justify-content:space-between;gap:8px;}
.receipt .r-tot{font-size:11px;font-weight:800;letter-spacing:0;}
.field{display:flex;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid rgba(233,237,233,.1);
  animation:rowIn .55s var(--spring) both;}
.field:last-of-type{border-bottom:none;}
.field-l{font-size:11px;color:rgba(233,237,233,.5);width:70px;flex:none;font-weight:600;}
.field-v{flex:1;font-size:14px;font-weight:700;letter-spacing:-.01em;}
.field-c{width:44px;flex:none;}
.field-c i{display:block;height:3px;border-radius:2px;background:var(--brass);transform-origin:left;
  animation:confFill 1s var(--spring) .3s both;}
.field-c span{font-size:9.5px;color:rgba(233,237,233,.45);font-weight:700;display:block;margin-top:4px;text-align:right;}

/* composer buttons */
.cbtn{width:36px;height:36px;border-radius:12px;display:grid;place-items:center;flex:none;
  color:#F4F7F3;background:rgba(233,237,233,.2);border:1px solid rgba(233,237,233,.3);
  transition:transform .3s var(--spring-2), color .25s, background .25s, border-color .25s;}
.cbtn:hover{color:#12100A;background:#E0BB74;border-color:#E0BB74;}
.cbtn:active{transform:scale(.86);}
.att{display:inline-flex;align-items:center;gap:8px;padding:7px 11px;border-radius:12px;
  background:rgba(15,28,26,.35);border:1px solid rgba(233,237,233,.12);margin-bottom:8px;
  font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:rgba(233,237,233,.62);}
.att-bars{display:flex;align-items:center;gap:2px;height:13px;}
.att-bars i{width:2px;border-radius:2px;background:var(--brass-lit);animation:attBar 1.4s ease-in-out infinite;}
@keyframes attBar{0%,100%{height:3px;}50%{height:12px;}}
.att-img{width:112px;height:80px;border-radius:12px;object-fit:cover;display:block;margin-bottom:9px;
  border:1px solid rgba(233,237,233,.16);animation:rise .55s var(--spring) both;}

/* ---------- places / map ---------- */
.capbar{background:linear-gradient(168deg,var(--ink-2),var(--ink));border-radius:22px;padding:17px 18px 19px;color:#EDF1ED;
  box-shadow:var(--shadow-md);position:relative;overflow:hidden;}
.cap-row{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;}
.slider{-webkit-appearance:none;appearance:none;width:100%;height:5px;border-radius:4px;margin:18px 0 0;
  background:rgba(233,237,233,.18);outline:none;}
.slider::-webkit-slider-thumb{-webkit-appearance:none;width:26px;height:26px;border-radius:50%;cursor:grab;
  background:radial-gradient(circle at 34% 30%,#F3DEB0,#C9A45C 62%,#9C7833);
  box-shadow:0 0 0 5px rgba(201,164,92,.2), 0 4px 12px -3px rgba(0,0,0,.6);transition:box-shadow .25s;}
.slider::-webkit-slider-thumb:active{cursor:grabbing;box-shadow:0 0 0 9px rgba(201,164,92,.26), 0 4px 12px -3px rgba(0,0,0,.6);}
.slider::-moz-range-thumb{width:24px;height:24px;border:none;border-radius:50%;cursor:grab;
  background:radial-gradient(circle at 34% 30%,#F3DEB0,#C9A45C 62%,#9C7833);box-shadow:0 0 0 5px rgba(201,164,92,.2);}
.cap-ticks{display:flex;justify-content:space-between;margin-top:9px;font-size:10.5px;font-weight:700;
  letter-spacing:.06em;color:rgba(233,237,233,.45);}

.filters{display:flex;gap:7px;flex-wrap:wrap;margin-top:14px;}
.fchip{padding:8px 13px;border-radius:100px;font-size:12px;font-weight:700;letter-spacing:-.01em;
  border:1px solid var(--line-2);color:var(--ink);background:var(--surface);
  transition:transform .28s var(--spring-2), background .25s, color .25s, border-color .25s;}
.fchip:active{transform:scale(.93);}
.fchip.on{background:var(--ink);color:#F3F6F2;border-color:var(--ink);}

.mapcard{position:relative;height:304px;border-radius:22px;overflow:hidden;background:#DDE2DC;
  box-shadow:var(--shadow-sm);border:1px solid var(--line);animation:mapIn .8s var(--spring) both;}
@keyframes mapIn{from{opacity:0;transform:scale(.97) translateY(14px);filter:blur(8px);}to{opacity:1;transform:none;filter:blur(0);}}
.mapcard .leaflet-container{height:100%;width:100%;background:#DDE2DC;font-family:'Manrope',sans-serif;}
.mapcard .leaflet-tile-pane{filter:grayscale(.82) sepia(.34) hue-rotate(96deg) saturate(.62) contrast(1.04) brightness(.99);}
.mapcard .leaflet-control-attribution{background:rgba(251,252,250,.82);font-size:8.5px;color:var(--muted);}
.mapcard .leaflet-control-zoom{border:none;box-shadow:var(--shadow-sm);}
.mapcard .leaflet-control-zoom a{background:var(--surface);color:var(--ink);border:none;}
.map-veil{position:absolute;inset:0;z-index:401;pointer-events:none;
  background:linear-gradient(180deg,rgba(15,28,26,.16) 0%,transparent 22%,transparent 72%,rgba(15,28,26,.22) 100%);}
.map-load{position:absolute;inset:0;z-index:402;display:grid;place-items:center;background:#E4E8E2;}

.pin{display:flex;flex-direction:column;align-items:center;gap:0;}
.pin b{font-size:11px;font-weight:800;letter-spacing:-.02em;padding:5px 8px;border-radius:9px;white-space:nowrap;
  box-shadow:0 4px 12px -4px rgba(15,28,26,.55);animation:pinDrop .6s var(--spring-2) both;}
.pin s{width:2px;height:9px;text-decoration:none;display:block;animation:pinDrop .6s var(--spring-2) both;}
@keyframes pinDrop{from{opacity:0;transform:translateY(-16px) scale(.6);}to{opacity:1;transform:none;}}
.pin-ok b{background:#E0BB74;color:#151009;} .pin-ok s{background:#E0BB74;}
.pin-tight b{background:#7FA298;color:#0C1614;} .pin-tight s{background:#7FA298;}
.pin-over b{background:#A85647;color:#FBF3F1;} .pin-over s{background:#A85647;}
.pin-sel b{outline:2.5px solid var(--ink);outline-offset:2px;transform:scale(1.12);}
.me{width:16px;height:16px;border-radius:50%;background:#2C6B57;border:2.5px solid #FBFCFA;
  box-shadow:0 0 0 6px rgba(44,107,87,.22);animation:mePulse 2.6s ease-in-out infinite;}
@keyframes mePulse{0%,100%{box-shadow:0 0 0 6px rgba(44,107,87,.22);}50%{box-shadow:0 0 0 12px rgba(44,107,87,.06);}}

.place{width:100%;text-align:left;display:flex;gap:13px;align-items:center;padding:14px;border-radius:18px;
  background:var(--surface);border:1.5px solid transparent;box-shadow:var(--shadow-sm);
  transition:transform .34s var(--spring), border-color .3s, box-shadow .34s;}
.place:active{transform:scale(.985);}
.place.sel{border-color:var(--brass);box-shadow:0 0 0 4px rgba(201,164,92,.14),var(--shadow-md);}
.place-rank{width:34px;height:34px;border-radius:12px;flex:none;display:grid;place-items:center;
  font-size:13px;font-weight:800;background:rgba(15,28,26,.055);color:var(--ink-3);}
.place.sel .place-rank{background:var(--brass);color:#151009;}
.badge{font-size:9px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;padding:3px 7px;border-radius:6px;}
.badge-best{background:rgba(169,133,63,.16);color:var(--brass);}
.badge-over{background:rgba(154,74,59,.13);color:var(--clay);}
.empty-map{text-align:center;padding:26px 18px;}

.fallmap{position:absolute;inset:0;background:
  linear-gradient(180deg,#E7EBE5,#DCE2DA);}
.fallmap line{stroke:rgba(15,28,26,.13);stroke-linecap:round;}
.fallmap .road-major{stroke:rgba(15,28,26,.2);}

/* ---------- goals ---------- */
.per{font-size:12px;font-weight:700;color:rgba(233,237,233,.5);margin-left:5px;letter-spacing:.02em;}
.dinput{width:100%;background:rgba(233,237,233,.09);border:1px solid rgba(233,237,233,.22);border-radius:14px;
  padding:14px 15px;color:#F4F7F3;font-family:inherit;font-size:15px;font-weight:600;outline:none;
  transition:border-color .3s, background .3s;}
.dinput::placeholder{color:rgba(240,245,240,.42);font-weight:500;}
.dinput:focus{border-color:#E0BB74;background:rgba(233,237,233,.13);}
.dchip{padding:8px 12px;border-radius:100px;font-size:12px;font-weight:700;
  border:1px solid rgba(233,237,233,.22);color:rgba(240,245,240,.8);background:rgba(233,237,233,.06);
  transition:transform .28s var(--spring-2), background .25s, color .25s, border-color .25s;}
.dchip:active{transform:scale(.93);}
.dchip.on{background:#E0BB74;color:#12100A;border-color:#E0BB74;}
.fieldset{margin-top:20px;}
.fs-head{display:flex;justify-content:space-between;align-items:center;gap:12px;}
.fs-note{margin:9px 0 0;font-size:11.5px;color:rgba(233,237,233,.45);font-weight:600;letter-spacing:.04em;}
.stepper{display:flex;align-items:center;gap:4px;background:rgba(233,237,233,.09);border:1px solid rgba(233,237,233,.2);
  border-radius:12px;padding:3px;}
.stepper button{width:30px;height:30px;border-radius:9px;font-size:17px;font-weight:700;color:#F4F7F3;
  background:rgba(233,237,233,.1);transition:transform .25s var(--spring-2), background .2s;}
.stepper button:active{transform:scale(.86);background:#E0BB74;color:#12100A;}
.stepper span{font-size:13px;font-weight:700;letter-spacing:-.01em;min-width:88px;text-align:center;}
.solver{margin-top:22px;border-radius:18px;padding:16px;border:1px solid rgba(233,237,233,.16);
  background:rgba(233,237,233,.05);transition:border-color .45s var(--spring), background .45s var(--spring);
  animation:approvalIn .6s var(--spring-2) both;}
.solver-ok{border-color:rgba(78,143,121,.55);background:rgba(78,143,121,.12);}
.solver-tight{border-color:rgba(201,164,92,.5);background:rgba(201,164,92,.1);}
.solver-over{border-color:rgba(200,110,92,.5);background:rgba(154,74,59,.14);}
.htag{display:inline-block;font-size:9.5px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;
  padding:3px 8px;border-radius:6px;border:1px solid;}
.addgoal{display:flex;gap:13px;align-items:center;width:100%;border-style:dashed;
  border:1.5px dashed var(--line-2);background:rgba(255,255,255,.4);box-shadow:none;}
.addgoal-ic{width:38px;height:38px;border-radius:13px;display:grid;place-items:center;flex:none;
  font-size:21px;font-weight:700;border:1.5px dashed;}

@media (prefers-reduced-motion: reduce){
  .kira-root *,.kira-root *::before,.kira-root *::after{animation:none !important;transition-duration:.01ms !important;}
  .rv{opacity:1 !important;transform:none !important;filter:none !important;}
  .hero-parallax{transform:none !important;}
  .boot{display:none;}
}
@media (max-width:430px){
  .kira-root{padding:16px 10px 24px;}
  .device{height:760px;border-radius:40px;}
}
`;

/* ============================================================
   DATA — integer sen
   ============================================================ */
const fmt = (sen) => (sen / 100).toLocaleString("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const BALANCE_0 = 418040;
const BUFFER = 80000;
const DAYS_TO_PAYDAY = 22;
const CYCLE_ELAPSED = 8, CYCLE_DAYS = 30;

/* A goal's claim on this cycle is what has accrued so far, not the whole contribution. */
const cycleReserve = (g) => Math.round((g.monthly * CYCLE_ELAPSED) / CYCLE_DAYS);
const monthsLeft = (g) => Math.max(1, Math.ceil((g.target - g.saved) / Math.max(g.monthly, 1)));

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthLabel = (ahead) => {
  const d = new Date(2026, 8, 1);
  d.setMonth(d.getMonth() + ahead);
  return `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`;
};

const HORIZONS = {
  short: { label: "Short term", blurb: "Under a year", stroke: "#4E8F79", presets: ["Emergency top-up", "New laptop", "Raya trip", "Course fees"] },
  long: { label: "Long term", blurb: "A year or more", stroke: "#A9853F", presets: ["Wedding", "House deposit", "Car down payment", "Umrah"] },
};

const GOALS_0 = [
  { id: "g1", horizon: "short", name: "Emergency top-up", target: 250000, saved: 115000, monthly: 27000, note: "Three weeks of expenses, kept separate from the buffer." },
  { id: "g2", horizon: "long", name: "Wedding", target: 800000, saved: 329000, monthly: 52500, note: "Deposit and banquet, split with Aida." },
];

const COMMITMENTS = [
  { id: "rent", name: "Rent", sen: 120000, due: "5 Sep", in: 2, protected: true },
  { id: "phone", name: "Phone bill", sen: 8900, due: "8 Sep", in: 5 },
  { id: "loan", name: "Car loan minimum", sen: 52000, due: "10 Sep", in: 7, protected: true },
  { id: "net", name: "Home internet", sen: 13900, due: "18 Sep", in: 15 },
  { id: "sub", name: "Streaming bundle", sen: 5500, due: "14 Sep", in: 11 },
];
const RESERVED = COMMITMENTS.reduce((a, c) => a + c.sen, 0);

const DRAFTS_0 = [
  { id: "d1", source: "Receipt", merchant: "Nasi Kandar Pelita", sen: 1890, cat: "Food", conf: 0.94, at: "12:41", note: "Line item total matched, tax line ignored." },
  { id: "d2", source: "Voice", merchant: "Grab — office to KLCC", sen: 1400, cat: "Transport", conf: 0.71, at: "12:43", note: "Heard “fourteen ringgit”. Amount is worth a second look." },
];

const TXNS = [
  { m: "Village Grocer", c: "Groceries", sen: 6215, d: "Yesterday", s: "Card" },
  { m: "Touch 'n Go reload", c: "Transport", sen: 5000, d: "Yesterday", s: "Manual" },
  { m: "Zus Coffee", c: "Food", sen: 990, d: "2 Sep", s: "Receipt" },
  { m: "Watsons", c: "Household", sen: 3480, d: "1 Sep", s: "Card" },
  { m: "Rent — August", c: "Housing", sen: 120000, d: "1 Sep", s: "Transfer" },
];

const DAY_OPTIONS = [
  { id: "o1", food: "Economy rice", place: "Nasi Kandar Pelita", move: "Walk 8 min", sen: 1250, conf: "Estimate · high", arrive: "12:34", effect: "safe", why: "Cheapest of the three and still back before your 1:15 call." },
  { id: "o2", food: "Chicken rice", place: "Chee Meng", move: "Grab · RM9.00", sen: 2600, conf: "Estimate · medium", arrive: "12:26", effect: "safe", why: "Fastest. Costs about half of today's room." },
  { id: "o3", food: "Sushi counter", place: "Sushi Zanmai", move: "LRT · RM2.10", sen: 4820, conf: "Estimate · low", arrive: "12:41", effect: "tight", why: "Menu prices aren't published, so this one is a rough read." },
];

const TABS = ["today", "activity", "butler", "plan", "more"];

/* ---------- places: a curated KL demo set (the Maps adapter supplies this in the build) ---------- */
const KLCC = { lat: 3.1577, lng: 101.7120, label: "Suria KLCC" };

const PLACES = [
  { id: "p1", name: "Nasi Kandar Pelita", kind: "Mamak", lat: 3.1596, lng: 101.7181, sen: 1250, conf: "high", halal: true, note: "Fast counter service, open late." },
  { id: "p2", name: "Zus Coffee, Jln Ampang", kind: "Cafe", lat: 3.1589, lng: 101.7145, sen: 900, conf: "high", halal: true, note: "Coffee and a pastry, not a full meal." },
  { id: "p3", name: "Suria KLCC food court", kind: "Food court", lat: 3.1577, lng: 101.7120, sen: 1800, conf: "medium", halal: true, note: "Widest choice, busiest at 12:30." },
  { id: "p4", name: "Chee Meng Chicken Rice", kind: "Chinese", lat: 3.1571, lng: 101.7156, sen: 1600, conf: "medium", halal: false, note: "Small shop, queue moves quickly." },
  { id: "p5", name: "Nasi Lemak Antarabangsa", kind: "Malay", lat: 3.1652, lng: 101.7042, sen: 1100, conf: "high", halal: true, note: "Kampung Baru institution." },
  { id: "p6", name: "Sushi Zanmai KLCC", kind: "Japanese", lat: 3.1580, lng: 101.7118, sen: 4600, conf: "low", halal: true, note: "Menu prices aren't published online." },
  { id: "p7", name: "Lot 10 Hutong", kind: "Hawker hall", lat: 3.1465, lng: 101.7106, sen: 2200, conf: "medium", halal: false, note: "Heritage stalls in one basement." },
  { id: "p8", name: "Village Grocer KLCC", kind: "Groceries", lat: 3.1575, lng: 101.7124, sen: 3500, conf: "low", halal: true, note: "Cook at home instead of eating out." },
];

const MODES = {
  walk: { label: "Walk", base: 0, perKm: 0, minPerKm: 13, wait: 0, gmaps: "walking" },
  transit: { label: "LRT", base: 210, perKm: 0, minPerKm: 4.5, wait: 7, gmaps: "transit" },
  ride: { label: "Grab", base: 500, perKm: 190, minPerKm: 3.2, wait: 5, gmaps: "driving" },
};

const haversine = (a, b) => {
  const R = 6371, r = Math.PI / 180;
  const dLat = (b.lat - a.lat) * r, dLng = (b.lng - a.lng) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
};

const NOW_MIN = 12 * 60 + 47; // 12:47
const clock = (mins) => {
  const m = Math.round(mins) % 1440;
  const h = Math.floor(m / 60), mm = String(m % 60).padStart(2, "0");
  return `${h > 12 ? h - 12 : h}:${mm}`;
};

/** Turns a place plus a transport mode into a full outing: cost, time, and what it does to today. */
function evaluate(place, origin, mode, room) {
  const km = haversine(origin, place);
  const m = MODES[mode];
  const travelSen = km < 0.12 ? 0 : Math.round(m.base + m.perKm * km);
  const minutes = Math.round(m.wait + km * m.minPerKm) + 6; // + ordering and eating buffer
  const total = place.sen + travelSen;
  const share = room > 0 ? total / room : 2;
  return {
    ...place, km, travelSen, minutes, total, share,
    arrive: clock(NOW_MIN + Math.round(m.wait + km * m.minPerKm)),
    band: share <= 0.6 ? "ok" : share <= 1 ? "tight" : "over",
  };
}

/* ============================================================
   ICONS
   ============================================================ */
const I = ({ d, size = 20, w = 1.6 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={w} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);
const IcToday = (p) => <I {...p} d={<><path d="M4 13.5 12 6l8 7.5" /><path d="M6.5 12v6.5h11V12" /></>} />;
const IcActivity = (p) => <I {...p} d={<path d="M4 12h4l2.5-5 3 10 2.5-5h4" />} />;
const IcPlan = (p) => <I {...p} d={<><circle cx="12" cy="12" r="7.6" /><path d="M12 7.6V12l3 2" /></>} />;
const IcMore = (p) => <I {...p} d={<><circle cx="6" cy="12" r="1.1" fill="currentColor" /><circle cx="12" cy="12" r="1.1" fill="currentColor" /><circle cx="18" cy="12" r="1.1" fill="currentColor" /></>} />;
const IcBell = (p) => <I {...p} d={<><path d="M8 15V11a4 4 0 0 1 8 0v4l1.5 2.2h-11L8 15Z" /><path d="M10.6 19.4a1.7 1.7 0 0 0 2.8 0" /></>} />;
const IcChev = (p) => <I {...p} d={<path d="m9.5 6 6 6-6 6" />} />;
const IcBack = (p) => <I {...p} d={<path d="m14 6-6 6 6 6" />} />;
const IcLock = (p) => <I {...p} d={<><rect x="5.5" y="10.5" width="13" height="9" rx="2.4" /><path d="M8.6 10.5V8.4a3.4 3.4 0 0 1 6.8 0v2.1" /></>} />;
const IcMic = (p) => <I {...p} d={<><rect x="9.5" y="4" width="5" height="10" rx="2.5" /><path d="M6.5 12a5.5 5.5 0 0 0 11 0M12 17.5V20" /></>} />;
const IcCam = (p) => <I {...p} d={<><path d="M4.5 8.5h3l1.4-2h6.2l1.4 2h3v10h-15Z" /><circle cx="12" cy="13" r="3.1" /></>} />;
const IcPen = (p) => <I {...p} d={<><path d="M5 19h3.2l9-9-3.2-3.2-9 9Z" /><path d="m14.4 6 3.2 3.2" /></>} />;
const IcCheck = (p) => <I {...p} d={<path d="m5.5 12.5 4.2 4.2 8.8-9.4" />} w={2} />;
const IcSpark = (p) => <I {...p} d={<path d="M12 4.5 13.7 10 19 12l-5.3 2-1.7 5.5L10.3 14 5 12l5.3-2Z" />} />;
const IcArrow = (p) => <I {...p} d={<path d="M5 12h13m-5-5 5 5-5 5" />} />;
const IcX = (p) => <I {...p} d={<path d="m7 7 10 10M17 7 7 17" />} />;
const IcImg = (p) => <I {...p} d={<><rect x="4" y="5.5" width="16" height="13" rx="2.6" /><circle cx="9" cy="10" r="1.4" /><path d="m5 16.5 4-3.6 3.4 3 2.6-2.2 4 3.8" /></>} />;
const IcPin = (p) => <I {...p} d={<><path d="M12 20.5s6.2-5.6 6.2-10.2a6.2 6.2 0 1 0-12.4 0C5.8 14.9 12 20.5 12 20.5Z" /><circle cx="12" cy="10.2" r="2.4" /></>} />;
const IcStop = (p) => <I {...p} d={<rect x="7.5" y="7.5" width="9" height="9" rx="2" fill="currentColor" stroke="none" />} />;

/* ============================================================
   MAP
   ============================================================ */
function useLeaflet() {
  const [L, setL] = useState(() => (typeof window !== "undefined" ? window.L : null));
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (L) return;
    if (!document.getElementById("leaflet-css")) {
      const css = document.createElement("link");
      css.id = "leaflet-css";
      css.rel = "stylesheet";
      css.href = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css";
      document.head.appendChild(css);
    }
    let s = document.getElementById("leaflet-js");
    if (!s) {
      s = document.createElement("script");
      s.id = "leaflet-js";
      s.src = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js";
      document.head.appendChild(s);
    }
    const ok = () => window.L && setL(window.L);
    s.addEventListener("load", ok);
    s.addEventListener("error", () => setFailed(true));
    const poll = setInterval(ok, 250);
    const bail = setTimeout(() => { if (!window.L) setFailed(true); }, 5000);
    return () => { clearInterval(poll); clearTimeout(bail); s.removeEventListener("load", ok); };
  }, [L]);
  return { L, failed };
}

function pinHtml(p, selected) {
  return `<div class="pin pin-${p.band} ${selected ? "pin-sel" : ""}">
    <b>RM${fmt(p.total)}</b><s></s>
  </div>`;
}

function LiveMap({ L, origin, results, selected, onSelect }) {
  const box = useRef(null);
  const map = useRef(null);
  const layer = useRef(null);

  useEffect(() => {
    if (!L || !box.current || map.current) return;
    map.current = L.map(box.current, { zoomControl: false, attributionControl: true })
      .setView([origin.lat, origin.lng], 15);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "© OpenStreetMap",
    }).addTo(map.current);
    L.control.zoom({ position: "bottomright" }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => { map.current?.remove(); map.current = null; };
  }, [L, origin.lat, origin.lng]);

  /* redraw markers whenever the money maths changes the results */
  useEffect(() => {
    if (!L || !map.current || !layer.current) return;
    layer.current.clearLayers();
    L.marker([origin.lat, origin.lng], {
      icon: L.divIcon({ className: "", html: `<div class="me"></div>`, iconSize: [16, 16], iconAnchor: [8, 8] }),
      interactive: false,
    }).addTo(layer.current);

    results.forEach((p) => {
      L.marker([p.lat, p.lng], {
        icon: L.divIcon({
          className: "", html: pinHtml(p, selected === p.id),
          iconSize: [70, 34], iconAnchor: [35, 34],
        }),
      }).addTo(layer.current).on("click", () => onSelect(p.id));
    });

    const pts = [[origin.lat, origin.lng], ...results.map((p) => [p.lat, p.lng])];
    if (pts.length > 1) map.current.fitBounds(pts, { padding: [42, 42], maxZoom: 16, animate: true });
  }, [L, results, selected, origin, onSelect]);

  /* ease to the chosen place */
  useEffect(() => {
    if (!map.current || !selected) return;
    const p = results.find((x) => x.id === selected);
    if (p) map.current.flyTo([p.lat, p.lng], 16, { duration: 0.85 });
  }, [selected, results]);

  return <div ref={box} style={{ height: "100%", width: "100%" }} />;
}

/** Used when tiles can't load: relative positions, honestly labelled. */
function FallbackMap({ origin, results, selected, onSelect }) {
  const pts = [origin, ...results];
  const lats = pts.map((p) => p.lat), lngs = pts.map((p) => p.lng);
  const pad = 0.004;
  const minLat = Math.min(...lats) - pad, maxLat = Math.max(...lats) + pad;
  const minLng = Math.min(...lngs) - pad, maxLng = Math.max(...lngs) + pad;
  const X = (lng) => ((lng - minLng) / (maxLng - minLng)) * 100;
  const Y = (lat) => (1 - (lat - minLat) / (maxLat - minLat)) * 100;

  return (
    <div className="fallmap">
      <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        {[18, 38, 58, 78].map((y) => <line key={`h${y}`} x1="0" y1={y} x2="100" y2={y} strokeWidth=".5" className={y === 38 ? "road-major" : ""} />)}
        {[16, 34, 52, 70, 88].map((x) => <line key={`v${x}`} x1={x} y1="0" x2={x} y2="100" strokeWidth=".5" className={x === 52 ? "road-major" : ""} />)}
        <line x1="4" y1="94" x2="96" y2="8" strokeWidth=".9" className="road-major" />
      </svg>
      <div style={{ position: "absolute", left: `${X(origin.lng)}%`, top: `${Y(origin.lat)}%`, transform: "translate(-50%,-50%)" }}>
        <span className="me" style={{ display: "block" }} />
      </div>
      {results.map((p) => (
        <button key={p.id} onClick={() => onSelect(p.id)}
          style={{ position: "absolute", left: `${X(p.lng)}%`, top: `${Y(p.lat)}%`, transform: "translate(-50%,-100%)" }}>
          <span className={`pin pin-${p.band} ${selected === p.id ? "pin-sel" : ""}`} style={{ display: "flex" }}>
            <b>RM{fmt(p.total)}</b><s />
          </span>
        </button>
      ))}
      <p style={{ position: "absolute", left: 10, bottom: 8, margin: 0, fontSize: 9.5, color: "var(--muted)", fontWeight: 600 }}>
        Map tiles unavailable — showing relative positions
      </p>
    </div>
  );
}
/* ============================================================
   MOTION UTILITIES
   ============================================================ */
const ScrollCtx = createContext(null);

/** Reveals children when they scroll into the phone viewport. */
function Reveal({ children, delay = 0, as: Tag = "div", ...rest }) {
  const root = useContext(ScrollCtx);
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const show = () => {
      el.style.transitionDelay = `${delay}ms`;
      el.classList.add("in");
    };
    if (!("IntersectionObserver" in window)) return show();
    const io = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { show(); io.disconnect(); } },
      { root: root?.current ?? null, rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
    );
    io.observe(el);
    const t = setTimeout(show, 1400); // safety net
    return () => { io.disconnect(); clearTimeout(t); };
  }, [delay, root]);
  return <Tag ref={ref} className={`rv ${rest.className || ""}`} {...rest}>{children}</Tag>;
}

/** Per-digit odometer. Digits settle left to right. */
function Odometer({ sen, size = 52, rm = true }) {
  const chars = fmt(sen).split("");
  return (
    <span className="od" style={{ fontSize: size, lineHeight: 1 }}>
      {rm && <span className="rm">RM</span>}
      {chars.map((c, i) => {
        if (!/\d/.test(c)) return <span className="od-fix" key={`f${i}`}>{c}</span>;
        const d = Number(c);
        return (
          <span className="od-col" key={`d${i}`}>
            <span className="od-track"
              style={{ transform: `translateY(${-d * 10}%)`, transitionDelay: `${i * 55}ms` }}>
              {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => <u key={n}>{n}</u>)}
            </span>
          </span>
        );
      })}
    </span>
  );
}

/** Pointer-following tilt, disabled for touch and reduced motion. */
function useTilt(strength = 5) {
  const ref = useRef(null);
  const onMove = useCallback((e) => {
    const el = ref.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    el.style.transform = `perspective(700px) rotateX(${-y * strength}deg) rotateY(${x * strength}deg) translateY(-2px)`;
  }, [strength]);
  const onLeave = useCallback(() => {
    if (ref.current) ref.current.style.transform = "";
  }, []);
  return { ref, onMouseMove: onMove, onMouseLeave: onLeave };
}

function Motes() {
  const spec = [
    { l: "12%", t: "22%", s: 74, dur: 17, d: 0 },
    { l: "68%", t: "38%", s: 112, dur: 23, d: -6 },
    { l: "34%", t: "66%", s: 58, dur: 19, d: -11 },
    { l: "82%", t: "76%", s: 92, dur: 27, d: -3 },
    { l: "50%", t: "12%", s: 46, dur: 15, d: -9 },
  ];
  return (
    <div className="motes" aria-hidden="true">
      {spec.map((m, i) => (
        <span className="mote" key={i} style={{
          left: m.l, top: m.t, width: m.s, height: m.s,
          animation: `drift ${m.dur}s ease-in-out ${m.d}s infinite alternate`,
          opacity: 0.5,
        }} />
      ))}
    </div>
  );
}

/* ============================================================
   APP
   ============================================================ */
export default function Kira() {
  const [tab, setTab] = useState("today");
  const [dir, setDir] = useState(0);
  const [boot, setBoot] = useState(true);
  const [bootKey, setBootKey] = useState(0);
  const [balance, setBalance] = useState(BALANCE_0);
  const [goals, setGoals] = useState(GOALS_0);
  const [drafts, setDrafts] = useState(DRAFTS_0);
  const [leaving, setLeaving] = useState(null);
  const [log, setLog] = useState([]);
  const [picked, setPicked] = useState(null);
  const [maths, setMaths] = useState(false);
  const [toast, setToast] = useState(null);
  const [flash, setFlash] = useState(0);
  const [chosenPlan, setChosenPlan] = useState(null);
  const [planVersion, setPlanVersion] = useState(2);
  const [audit, setAudit] = useState([
    { t: "12:43", e: "Voice draft created", by: "Kira" },
    { t: "12:41", e: "Receipt draft created", by: "Kira" },
    { t: "09:02", e: "Plan v2 approved by you", by: "You" },
  ]);
  const [thread, setThread] = useState([]);
  const [approval, setApproval] = useState(null);
  const [scenario, setScenario] = useState("s1");
  const viewRef = useRef(null);
  const screenRef = useRef(null);

  const goalReserve = goals.reduce((a, g) => a + cycleReserve(g), 0);
  const unclaimed = balance - RESERVED - BUFFER - goalReserve;
  const perDay = Math.floor(unclaimed / DAYS_TO_PAYDAY);
  const spentToday = log.reduce((a, x) => a + x.sen, 0);
  const safeToday = Math.max(0, perDay - spentToday);

  useEffect(() => {
    const t = setTimeout(() => setBoot(false), 2500);
    return () => clearTimeout(t);
  }, [bootKey]);

  useEffect(() => { viewRef.current?.scrollTo({ top: 0, behavior: "auto" }); }, [tab]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3400);
    return () => clearTimeout(t);
  }, [toast]);

  /* scroll-linked parallax: write a CSS var, no re-render */
  useEffect(() => {
    const v = viewRef.current, s = screenRef.current;
    if (!v || !s) return;
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        s.style.setProperty("--sy", String(v.scrollTop));
        raf = 0;
      });
    };
    v.addEventListener("scroll", onScroll, { passive: true });
    return () => { v.removeEventListener("scroll", onScroll); cancelAnimationFrame(raf); };
  }, [tab]);

  const go = (next) => {
    if (next === tab) return;
    const norm = (t) => t.replace(/bills|accounts|safety/, "more").replace(/places/, "plan");
    const a = TABS.indexOf(norm(tab));
    const b = TABS.indexOf(norm(next));
    setDir(next === "butler" || tab === "butler" ? 0 : b > a ? 1 : -1);
    setTab(next);
  };

  const say = (msg) => setToast(msg);
  const addAudit = (e, by = "You") =>
    setAudit((a) => [{ t: new Date().toLocaleTimeString("en-MY", { hour: "2-digit", minute: "2-digit", hour12: false }), e, by }, ...a]);

  const confirmDraft = (d) => {
    setLeaving(d.id);
    setTimeout(() => {
      setDrafts((x) => x.filter((y) => y.id !== d.id));
      setLeaving(null);
      setBalance((b) => b - d.sen);
      setLog((l) => [...l, { sen: d.sen, m: d.merchant }]);
      setFlash((f) => f + 1);
      addAudit(`${d.source} confirmed — ${d.merchant} RM${fmt(d.sen)}`);
      const next = Math.max(0, Math.floor((balance - d.sen - RESERVED - BUFFER - goalReserve) / DAYS_TO_PAYDAY) - spentToday);
      say(`Added. Safe to spend is now RM${fmt(next)}.`);
    }, 400);
  };
  const discardDraft = (d) => {
    setLeaving(d.id);
    setTimeout(() => {
      setDrafts((x) => x.filter((y) => y.id !== d.id));
      setLeaving(null);
      addAudit(`${d.source} draft discarded — ${d.merchant}`);
      say("Draft discarded. Nothing was written to your ledger.");
    }, 400);
  };

  /* ---------- butler ---------- */
  const answer = (q) => {
    const k = q.toLowerCase();
    if (k.includes("afford") || k.includes("60") || k.includes("dinner"))
      return {
        head: "Not without borrowing from tomorrow.",
        sub: `RM60 leaves you RM${fmt(Math.max(0, 6000 - safeToday))} short today. You'd be spending the next two days at about RM47.50 instead of RM${fmt(perDay)}. Rent, the car loan and your buffer stay untouched either way — this only moves flexible money.`,
        ev: [["Safe to spend today", `RM${fmt(safeToday)}`], ["Confirmed so far today", `RM${fmt(spentToday)}`], ["Next commitment", "Rent RM1,200 · in 2 days"], ["Buffer status", "RM800 protected"]],
      };
    if (k.includes("why") || k.includes("drop") || k.includes("changed"))
      return {
        head: "Two confirmations and one new bill.",
        sub: "You confirmed a receipt and a voice note this afternoon, and I detected a recurring internet bill of RM139 that wasn't reserved before. Together that trimmed about RM6.32 a day off your room until payday.",
        ev: [["Receipt · Nasi Kandar Pelita", "−RM18.90"], ["Voice · Grab to KLCC", "−RM14.00"], ["New recurring bill detected", "−RM139.00 reserved"], ["Plan version in use", `v${planVersion}`]],
      };
    if (k.includes("overspent") || k.includes("120") || k.includes("weekend"))
      return {
        head: "That's recoverable. Here are two ways.",
        sub: "Neither one touches your rent, your car loan minimum or the RM800 buffer. Pick one and I'll draft the change — it only takes effect once you approve it.",
        ev: [["Overspend recorded", "−RM120.00"], ["Days until payday", `${DAYS_TO_PAYDAY}`], ["Protected and untouched", "Rent · Loan · Buffer"]],
        approval: true,
      };
    if (k.includes("receipt"))
      return {
        head: "RM18.90 at Pelita — about a third of today's room.",
        sub: `I've read it but I haven't counted it. Save it as a draft and confirm it in Activity, and today's safe-to-spend drops to RM${fmt(Math.max(0, safeToday - 1890))}. Dinner at RM60 stops being possible after that without borrowing from tomorrow.`,
        ev: [["Read from the receipt", "RM18.90"], ["Confidence", "94%"], ["Room today", `RM${fmt(safeToday)}`], ["Status", "Draft — not counted yet"]],
      };
    if (k.includes("goal") || k.includes("wedding") || k.includes("saving"))
      return {
        head: goals.length
          ? `Both goals are on track, and they cost you RM${fmt(Math.round(goals.reduce((a, g) => a + g.monthly, 0) / 30))} a day.`
          : "You haven't set a goal yet.",
        sub: goals.length
          ? `${goals.map((g) => `${g.name} needs RM${fmt(g.monthly)} a month and lands in ${monthLabel(monthsLeft(g))}`).join(". ")}. I hold RM${fmt(goalReserve)} of that back this cycle before I tell you what's safe to spend, which is why today's number is lower than your balance suggests.`
          : "Open Plan and set a short-term and a long-term goal, and I'll work out what each one costs you per day.",
        ev: goals.length
          ? [...goals.map((g) => [g.name, `RM${fmt(g.saved)} of RM${fmt(g.target)}`]),
             ["Held this cycle", `RM${fmt(goalReserve)}`],
             ["Monthly total", `RM${fmt(goals.reduce((a, g) => a + g.monthly, 0))}`]]
          : [["Goals set", "0"], ["Room today", `RM${fmt(safeToday)}`]],
      };
    return {
      head: "I can only answer from what you've confirmed.",
      sub: "This prototype covers affordability, why your numbers moved, overspend recovery, and your wedding goal. Try one of the prompts below and I'll show you the working.",
      ev: [["Confirmed transactions", "5 this week"], ["Data confidence", "High"], ["Drafts waiting", `${drafts.length}`]],
    };
  };

  const ask = (q, att) => {
    if (!q.trim()) return;
    const a = answer(q);
    setThread((t) => [...t, { role: "user", text: q, att }, { role: "kira", thinking: true }]);
    setApproval(null);
    setTimeout(() => {
      setThread((t) => t.map((m, i) => (i === t.length - 1 ? { role: "kira", ...a } : m)));
      setApproval(a.approval ? "open" : null);
    }, att?.kind === "image" ? 1350 : 950);
  };

  const addScanDraft = (src) => {
    if (drafts.some((d) => d.id === "scan")) return say("That receipt is already waiting in Activity.");
    setDrafts((d) => [{ id: "scan", source: "Receipt", merchant: "Nasi Kandar Pelita", sen: 1890, cat: "Food", conf: 0.94, at: "12:38", note: "Five line items, total matched.", src }, ...d]);
    addAudit("Receipt draft created — Nasi Kandar Pelita", "Kira");
    say("Saved as a draft. Confirm it in Activity when you're ready.");
  };

  const applyPlan = () => {
    setPlanVersion((v) => v + 1);
    setApproval("done");
    addAudit(`Plan change approved — recovery ${scenario === "s1" ? "spread over 6 days" : "taken from goal contribution"} · v${planVersion + 1}`);
    say(`Approved. Your plan is now v${planVersion + 1}.`);
  };

  const dark = tab === "butler";
  const shared = { safeToday, perDay, unclaimed, balance, spentToday, picked, setPicked, maths, setMaths, drafts, setTab: go, chosenPlan, flash, goals, goalReserve };

  return (
    <div className="kira-root">
      <style>{STYLES}</style>

      <div className="stage-head">
        <div className="lockup">
          <b>Kira</b>
          <span>AI money butler</span>
        </div>
        <button className="replay" onClick={() => { setBoot(true); setBootKey((k) => k + 1); }}>
          <i />Replay intro
        </button>
      </div>

      <div className="device">
        <div className={`screen ${dark ? "dim" : ""}`} ref={screenRef} style={{ "--dir": dir }}>
          <Motes />

          {boot && (
            <div className="boot" key={bootKey}>
              <div style={{ textAlign: "center" }}>
                <div className="boot-mark">
                  {"KIRA".split("").map((c, i) => (
                    <span key={i} style={{ animationDelay: `${0.07 * i}s` }}>{c}</span>
                  ))}
                </div>
                <div className="boot-rule" />
                <p className="boot-sub">AI money butler</p>
              </div>
            </div>
          )}

          <div className="statusbar" aria-label="Device status">
            <span className="status-time">12:47</span>
            <span className="device-notch" aria-hidden="true">
              <i className="notch-speaker" />
              <i className="notch-camera" />
            </span>
            <span className="status-icons" aria-hidden="true">
              <span className="sb-signal"><i /><i /><i /><i /></span>
              <svg className="sb-wifi" viewBox="0 0 18 14">
                <path d="M1.5 4.25A11.3 11.3 0 0 1 16.5 4.25" />
                <path d="M4.1 7.2a7.4 7.4 0 0 1 9.8 0" />
                <path d="M7 10.15a3.2 3.2 0 0 1 4 0" />
                <circle cx="9" cy="12.25" r="1.05" />
              </svg>
              <span className="sb-batt"><i /></span>
            </span>
          </div>

          <ScrollCtx.Provider value={viewRef}>
            <div className="viewport" ref={viewRef}>
              <div className="page" key={tab}>
                {tab === "today" && <Today {...shared} />}
                {tab === "activity" && <Activity {...{ drafts, confirmDraft, discardDraft, log, say, leaving }} />}
                {tab === "butler" && <Butler {...{ thread, ask, approval, scenario, setScenario, applyPlan, setApproval, say, planVersion, onDraft: addScanDraft }} />}
                {tab === "plan" && <Plan {...{ safeToday, chosenPlan, setChosenPlan, say, addAudit, setTab: go, goals, setGoals, goalReserve, balance }} />}
                {tab === "places" && <Places {...{ setTab: go, safeToday, setChosenPlan, say, addAudit }} />}
                {tab === "more" && <More setTab={go} drafts={drafts} />}
                {tab === "bills" && <Bills setTab={go} say={say} />}
                {tab === "accounts" && <Accounts setTab={go} say={say} balance={balance} />}
                {tab === "safety" && <Safety setTab={go} audit={audit} planVersion={planVersion} say={say} />}
              </div>
            </div>
          </ScrollCtx.Provider>

          {toast && (
            <div className="toast" role="status" key={toast}>
              <span className="tick"><IcCheck size={17} /></span>
              <span style={{ lineHeight: 1.35 }}>{toast}</span>
            </div>
          )}

          <nav className="nav">
            <NavItem id="today" tab={tab} go={go} Ic={IcToday} label="Today" />
            <NavItem id="activity" tab={tab} go={go} Ic={IcActivity} label="Activity" />
            <button className={`nav-butler ${tab === "butler" ? "active" : ""}`} onClick={() => go("butler")}>
              <span className="butler-orb"><IcSpark size={25} /></span>
              <span>Butler</span>
            </button>
            <NavItem id="plan" tab={tab} go={go} Ic={IcPlan} label="Plan"
              active={["plan", "places"].includes(tab)} />
            <NavItem id="more" tab={tab} go={go} Ic={IcMore} label="More"
              active={["more", "bills", "accounts", "safety"].includes(tab)} />
          </nav>
        </div>
      </div>
    </div>
  );
}

function NavItem({ id, tab, go, Ic, label, active }) {
  const on = active ?? tab === id;
  return (
    <button className={`nav-item ${on ? "active" : ""}`} onClick={() => go(id)}>
      <Ic />
      <span>{label}</span>
      {on && <i className="nav-dot" />}
    </button>
  );
}

/* ============================================================
   CLAIM LINE
   ============================================================ */
function ClaimLine({ free, goalReserve, goalCount, onPick, picked }) {
  const segs = [
    { k: "free", v: free, cls: "seg-free", label: "Unclaimed", sub: "Yours to decide" },
    { k: "goal", v: goalReserve, cls: "seg-goal", label: "Goal reserve", sub: `${goalCount} goal${goalCount > 1 ? "s" : ""}, accrued this cycle` },
    { k: "commit", v: RESERVED, cls: "seg-commit", label: "Committed", sub: `${COMMITMENTS.length} bills before payday` },
    { k: "buffer", v: BUFFER, cls: "seg-buffer", label: "Buffer", sub: "Protected, not spendable" },
  ];
  const swatch = {
    free: "linear-gradient(180deg,#FBF7EC,#DFCFA4)",
    goal: "linear-gradient(180deg,#E0BB74,#B58F45)",
    commit: "linear-gradient(180deg,#7FA298,#5B7C74)",
    buffer: "#43635C",
  };
  return (
    <div>
      <div className="claim" role="img" aria-label="How your balance is claimed">
        {segs.map((s, i) => (
          <button key={s.k} className={`claim-seg ${s.cls}`}
            style={{ flexGrow: s.v, animationDelay: `${0.35 + i * 0.09}s`, opacity: picked && picked !== s.k ? 0.45 : 1 }}
            onClick={() => onPick(picked === s.k ? null : s.k)} aria-label={`${s.label} RM${fmt(s.v)}`} />
        ))}
      </div>
      <div className="claim-legend">
        {segs.map((s) => (
          <button key={s.k} className="leg" onClick={() => onPick(picked === s.k ? null : s.k)}
            style={{ opacity: picked && picked !== s.k ? 0.38 : 1 }}>
            <i style={{ background: swatch[s.k] }} />
            <span>
              <span className="leg-l">{s.label}</span>
              <span className="leg-v">{fmt(s.v)}</span>
            </span>
          </button>
        ))}
      </div>
      {picked && (
        <p className="voice" style={{ margin: "13px 0 0", fontSize: 13.5, color: "rgba(233,237,233,.7)", animation: "fadeUp .5s var(--spring) both" }}>
          {segs.find((s) => s.k === picked).sub}.
        </p>
      )}
    </div>
  );
}

function Ring({ pct, size = 96, stroke = "#A9853F" }) {
  const r = size / 2 - 7, c = 2 * Math.PI * r;
  const [on, setOn] = useState(false);
  useEffect(() => { const t = setTimeout(() => setOn(true), 260); return () => clearTimeout(t); }, []);
  return (
    <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }} aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(15,28,26,.09)" strokeWidth="6" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={stroke} strokeWidth="6" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={on ? c - c * pct : c}
        style={{ transition: "stroke-dashoffset 1.4s cubic-bezier(.22,1,.36,1)" }} />
    </svg>
  );
}

/* ============================================================
   TODAY
   ============================================================ */
function Today({ safeToday, perDay, unclaimed, balance, spentToday, picked, setPicked, maths, setMaths, drafts, setTab, chosenPlan, flash, goals, goalReserve }) {
  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0, animation: "fadeUp .6s var(--spring) both" }}>Wednesday, 3 September</p>
          <h1 style={{ animation: "fadeUp .7s var(--spring) .06s both" }}>Good afternoon, Floyd</h1>
        </div>
        <button className="pill" style={{ marginTop: 6, animation: "fadeUp .7s var(--spring) .14s both" }} onClick={() => setTab("safety")}>
          <span className="dot" />High
        </button>
      </div>

      <div className="pad">
        <Reveal>
          <div className="hero-parallax">
          <section className="hero">
            {flash > 0 && <span className="flash-sweep" key={flash} />}
            <p className="eyebrow on-ink" style={{ margin: 0 }}>Safe to spend today</p>
            <div style={{ marginTop: 11 }}><Odometer sen={safeToday} size={52} /></div>
            <p className="voice" style={{ margin: "12px 0 0", fontSize: 15, color: "rgba(233,237,233,.78)" }}>
              Rent, your car loan and the RM800 buffer are already set aside. This is what's left over, spread evenly across the {DAYS_TO_PAYDAY} days to payday.
            </p>

            <div style={{ marginTop: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
                <span className="eyebrow on-ink">Where your RM{fmt(balance)} stands</span>
                <span style={{ fontSize: 11.5, color: "rgba(233,237,233,.5)", fontWeight: 600 }}>tap a band</span>
              </div>
              <ClaimLine free={unclaimed} goalReserve={goalReserve} goalCount={goals.length} onPick={setPicked} picked={picked} />
            </div>

            <button className="btn btn-sm" style={{ marginTop: 16, background: "rgba(233,237,233,.17)", color: "#F4F7F3", border: "1px solid rgba(233,237,233,.26)", width: "100%" }}
              onClick={() => setMaths((m) => !m)}>
              {maths ? "Hide the working" : "Show the working"}
            </button>

            {maths && (
              <div className="maths">
                {[
                  ["In hand", fmt(balance)],
                  ["Bills due before payday", `−${fmt(RESERVED)}`],
                  ["Emergency buffer", `−${fmt(BUFFER)}`],
                  ["Goals, accrued this cycle", `−${fmt(goalReserve)}`],
                  ["Unclaimed until payday", fmt(unclaimed), true],
                  [`÷ ${DAYS_TO_PAYDAY} days`, `${fmt(perDay)}/day`],
                  ...(spentToday > 0 ? [["Confirmed today", `−${fmt(spentToday)}`]] : []),
                  ["Safe to spend today", fmt(safeToday), true],
                ].map(([k, v, total], i) => (
                  <div className={`maths-row ${total ? "total" : ""}`} key={k} style={{ animationDelay: `${i * 55}ms` }}>
                    <span>{k}</span><b>{v}</b>
                  </div>
                ))}
              </div>
            )}
          </section>
          </div>
        </Reveal>

        {drafts.length > 0 && (
          <Reveal delay={40} style={{ marginTop: 16 }}>
            <button className="card tapp" style={{ display: "flex", gap: 13, alignItems: "center", width: "100%", textAlign: "left" }}
              onClick={() => setTab("activity")}>
              <span style={{ width: 38, height: 38, borderRadius: 13, background: "rgba(169,133,63,.14)", color: "var(--brass)", display: "grid", placeItems: "center", flex: "none" }}>
                <IcBell size={19} />
              </span>
              <span style={{ flex: 1 }}>
                <b style={{ fontSize: 14.5, display: "block", letterSpacing: "-.01em" }}>
                  {drafts.length} capture{drafts.length > 1 ? "s" : ""} waiting on you
                </b>
                <span style={{ fontSize: 12.5, color: "var(--muted)" }}>Nothing enters your ledger until you confirm it.</span>
              </span>
              <IcChev size={17} />
            </button>
          </Reveal>
        )}

        <Reveal delay={60} style={{ marginTop: 16 }}>
          <section className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <p className="eyebrow" style={{ margin: "0 0 6px" }}>Next commitment</p>
                <b style={{ fontSize: 17, letterSpacing: "-.02em" }}>Rent</b>
                <p style={{ margin: "3px 0 0", fontSize: 12.5, color: "var(--muted)" }}>Due Friday, 5 September · in 2 days</p>
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="money" style={{ fontSize: 21 }}>1,200.00</div>
                <span className="pill" style={{ marginTop: 7, fontSize: 9.5, padding: "4px 9px" }}><IcLock size={11} /> Reserved</span>
              </div>
            </div>
          </section>
        </Reveal>

        <Reveal delay={40} style={{ marginTop: 16 }}>
          <button className="card tapp" style={{ width: "100%", textAlign: "left" }} onClick={() => setTab("plan")}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14 }}>
              <p className="eyebrow" style={{ margin: 0 }}>Your goals</p>
              <span className="tag" style={{ color: "var(--brass)" }}>RM{fmt(goalReserve)} held</span>
            </div>
            <div style={{ display: "flex", gap: 14 }}>
              {goals.map((g) => {
                const H = HORIZONS[g.horizon];
                return (
                  <span key={g.id} style={{ flex: 1, display: "flex", gap: 11, alignItems: "center", minWidth: 0 }}>
                    <span className="ringwrap" style={{ width: 46, height: 46, flex: "none" }}>
                      <Ring pct={Math.min(1, g.saved / g.target)} size={46} stroke={H.stroke} />
                      <figcaption><b style={{ fontSize: 11, letterSpacing: "-.03em" }}>{Math.round((g.saved / g.target) * 100)}%</b></figcaption>
                    </span>
                    <span style={{ minWidth: 0 }}>
                      <b style={{ fontSize: 12.5, letterSpacing: "-.01em", display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{g.name}</b>
                      <span style={{ fontSize: 11, color: "var(--muted)" }}>{monthLabel(monthsLeft(g))}</span>
                    </span>
                  </span>
                );
              })}
              {goals.length === 0 && (
                <span style={{ fontSize: 13, color: "var(--muted)" }}>No goals set. Tap to add one.</span>
              )}
            </div>
          </button>
        </Reveal>

        <Reveal delay={40} style={{ marginTop: 16 }}>
          <section className="card" style={{ background: "linear-gradient(150deg,#F6F3EA,#EFEFE7)", border: "1px solid rgba(169,133,63,.24)" }}>
            <p className="eyebrow" style={{ margin: "0 0 7px", color: "var(--brass)" }}>It's 12:47</p>
            <p className="voice" style={{ margin: 0, fontSize: 17, lineHeight: 1.4 }}>
              {chosenPlan
                ? `You picked ${chosenPlan.place}. Leave in about ten minutes to arrive by ${chosenPlan.arrive}.`
                : "Shall I plan lunch and the trip to KLCC before your 1:15 call?"}
            </p>
            <button className="btn btn-primary btn-sm" style={{ marginTop: 14 }} onClick={() => setTab("plan")}>
              {chosenPlan ? "Review the plan" : "Plan my day"} <IcArrow size={15} />
            </button>
          </section>
        </Reveal>
      </div>
    </>
  );
}

/* ============================================================
   ACTIVITY
   ============================================================ */
function Activity({ drafts, confirmDraft, discardDraft, log, say, leaving }) {
  const [edit, setEdit] = useState(null);
  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0, animation: "fadeUp .6s var(--spring) both" }}>Activity</p>
          <h1 style={{ animation: "fadeUp .7s var(--spring) .06s both" }}>Capture what you spent</h1>
        </div>
      </div>

      <div className="pad">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 9 }}>
          {[["Manual", IcPen], ["Receipt", IcCam], ["Voice", IcMic]].map(([l, Ic], i) => (
            <Reveal key={l} delay={i * 70}>
              <button className="card-flat tapp" style={{ display: "flex", flexDirection: "column", gap: 9, alignItems: "flex-start", padding: 14, width: "100%" }}
                onClick={() => say(`${l} capture opens the camera, mic or a form. Drafts appear here for review.`)}>
                <Ic size={19} />
                <span style={{ fontSize: 12.5, fontWeight: 700 }}>{l}</span>
              </button>
            </Reveal>
          ))}
        </div>

        {drafts.length > 0 ? (
          <div style={{ marginTop: 22 }}>
            <p className="eyebrow" style={{ margin: "0 0 11px" }}>Waiting for you · {drafts.length}</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {drafts.map((d, i) => (
                <Reveal key={d.id} delay={i * 90}>
                  <div className={`draft ${leaving === d.id ? "leaving" : ""}`}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
                      {d.src && (
                        <img src={d.src} alt="" style={{
                          width: 46, height: 58, borderRadius: 10, objectFit: "cover", flex: "none",
                          border: "1px solid var(--line)", animation: "rise .5s var(--spring) both",
                        }} />
                      )}
                      <div style={{ flex: 1 }}>
                        <span className="tag" style={{ color: "var(--brass)" }}>{d.source} · {d.at}</span>
                        <b style={{ display: "block", fontSize: 15.5, letterSpacing: "-.02em", marginTop: 5 }}>{d.merchant}</b>
                        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{d.cat}</span>
                      </div>
                      <div className="money" style={{ fontSize: 20 }}>{fmt(d.sen)}</div>
                    </div>

                    <div className="conf"><i style={{ width: `${d.conf * 100}%` }} /></div>
                    <p className="voice" style={{ margin: "9px 0 0", fontSize: 13, color: "var(--muted)" }}>
                      {Math.round(d.conf * 100)}% sure. {d.note}
                    </p>

                    {edit === d.id && (
                      <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
                        {[["Merchant", d.merchant], ["Amount", `RM${fmt(d.sen)}`], ["Category", d.cat]].map(([k, v], j) => (
                          <div key={k} style={{
                            display: "flex", justifyContent: "space-between", padding: "10px 12px",
                            background: "rgba(15,28,26,.04)", borderRadius: 11, fontSize: 13,
                            animation: `rowIn .45s var(--spring) ${j * 60}ms both`,
                          }}>
                            <span style={{ color: "var(--muted)" }}>{k}</span><b>{v}</b>
                          </div>
                        ))}
                        <p style={{ fontSize: 11.5, color: "var(--muted-2)", margin: "2px 0 0" }}>Every field stays editable before it counts.</p>
                      </div>
                    )}

                    <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                      <button className="btn btn-primary btn-sm" style={{ flex: 1 }} onClick={() => confirmDraft(d)}>Confirm</button>
                      <button className="btn btn-line btn-sm" onClick={() => setEdit(edit === d.id ? null : d.id)}>Edit</button>
                      <button className="btn btn-ghost btn-sm" onClick={() => discardDraft(d)}>Discard</button>
                    </div>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        ) : (
          <Reveal style={{ marginTop: 22 }}>
            <div className="card-flat" style={{ textAlign: "center", padding: "30px 20px" }}>
              <p className="voice" style={{ margin: 0, fontSize: 16 }}>Nothing waiting.</p>
              <p style={{ margin: "7px 0 0", fontSize: 13, color: "var(--muted)" }}>Snap a receipt or say what you spent, and it'll land here for review.</p>
            </div>
          </Reveal>
        )}

        <Reveal delay={60} style={{ marginTop: 16 }}>
          <section className="card">
            <p className="eyebrow" style={{ margin: "0 0 4px" }}>Confirmed</p>
            {log.map((l, i) => (
              <div className="txn" key={`n${i}`} style={{ animation: "rowIn .55s var(--spring) both" }}>
                <span className="txn-ic" style={{ background: "rgba(169,133,63,.14)", color: "var(--brass)" }}><IcCheck size={16} /></span>
                <span style={{ flex: 1 }}>
                  <b style={{ fontSize: 14 }}>{l.m}</b>
                  <span style={{ display: "block", fontSize: 11.5, color: "var(--muted)" }}>Just now</span>
                </span>
                <span className="money" style={{ fontSize: 14.5 }}>−{fmt(l.sen)}</span>
              </div>
            ))}
            {TXNS.map((t) => (
              <div className="txn" key={t.m}>
                <span className="txn-ic">{t.s === "Receipt" ? <IcCam size={16} /> : t.s === "Manual" ? <IcPen size={16} /> : <IcActivity size={16} />}</span>
                <span style={{ flex: 1 }}>
                  <b style={{ fontSize: 14, letterSpacing: "-.01em" }}>{t.m}</b>
                  <span style={{ display: "block", fontSize: 11.5, color: "var(--muted)" }}>{t.c} · {t.d} · {t.s}</span>
                </span>
                <span className="money" style={{ fontSize: 14.5 }}>−{fmt(t.sen)}</span>
              </div>
            ))}
          </section>
        </Reveal>
      </div>
    </>
  );
}

/* ============================================================
   BUTLER
   ============================================================ */
function Words({ text }) {
  return (
    <>
      {text.split(" ").map((w, i) => (
        <span key={i}>
          <w style={{ animationDelay: `${i * 42}ms` }}>{w}</w>{" "}
        </span>
      ))}
    </>
  );
}

/* ---------- voice capture ---------- */
const PHRASE = [
  { w: "Can" }, { w: "I" }, { w: "afford" }, { w: "sixty", unsure: true },
  { w: "ringgit", unsure: true }, { w: "for" }, { w: "dinner" }, { w: "tonight?" },
];
const REDUCED = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function VoiceSheet({ onClose, onSend }) {
  const [stage, setStage] = useState("listening");
  const [n, setN] = useState(0);
  const [ms, setMs] = useState(0);
  const bars = useRef([]);
  const glow = useRef(null);
  const BARS = 34;

  /* waveform */
  useEffect(() => {
    if (stage !== "listening" || REDUCED()) return;
    let raf, t = 0;
    const loop = () => {
      t += 0.055;
      const breath = Math.max(0.12, Math.sin(t * 0.72) * 0.5 + 0.62); // pauses between words
      bars.current.forEach((el, i) => {
        if (!el) return;
        const c = 1 - Math.abs(i - (BARS - 1) / 2) / ((BARS - 1) / 2); // centre-weighted
        const v = Math.abs(Math.sin(t * (1.15 + i * 0.06) + i * 0.8)) * 0.55
          + Math.abs(Math.sin(t * 2.6 + i * 0.37)) * 0.45;
        el.style.transform = `scaleY(${(0.06 + v * breath * (0.35 + c * 0.65) * 0.94).toFixed(3)})`;
      });
      if (glow.current) glow.current.style.transform = `scale(${(0.86 + breath * 0.3).toFixed(3)})`;
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => cancelAnimationFrame(raf);
  }, [stage]);

  /* transcript + timer */
  useEffect(() => {
    if (stage !== "listening") return;
    const tick = setInterval(() => setMs((m) => m + 100), 100);
    const words = setInterval(() => setN((x) => Math.min(PHRASE.length, x + 1)), 285);
    return () => { clearInterval(tick); clearInterval(words); };
  }, [stage]);

  useEffect(() => {
    if (stage === "listening" && n === PHRASE.length) {
      const t = setTimeout(() => setStage("review"), 850);
      return () => clearTimeout(t);
    }
  }, [n, stage]);

  const text = PHRASE.map((p) => p.w).join(" ");
  const dur = `0:0${Math.max(1, Math.round(ms / 1000))}`;

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="sheet" role="dialog" aria-label="Voice note">
        <div className="grab" />
        <div className="sheet-head">
          <div>
            <p className="eyebrow on-ink" style={{ margin: 0 }}>{stage === "listening" ? "Listening" : "Before I answer"}</p>
            <h2 style={{ margin: "5px 0 0", fontSize: 20, fontWeight: 800, letterSpacing: "-.03em" }}>
              {stage === "listening" ? "Say it however you like" : "Did I hear that right?"}
            </h2>
          </div>
          <button className="xbtn" onClick={onClose} aria-label="Close"><IcX size={16} /></button>
        </div>

        {stage === "listening" ? (
          <>
            <div className="mic-stage">
              <span className="mic-glow" ref={glow} />
              <span className="mic-ring" /><span className="mic-ring" /><span className="mic-ring" />
              <div className="wave">
                {Array.from({ length: BARS }).map((_, i) => (
                  <i key={i} ref={(el) => (bars.current[i] = el)} />
                ))}
              </div>
            </div>
            <p className="timer">{dur}</p>
          </>
        ) : (
          <div className="intent"><IcSpark size={13} /> Affordability check</div>
        )}

        <p className="tscript">
          {PHRASE.slice(0, stage === "review" ? PHRASE.length : n).map((p, i) => (
            <span key={i}>
              <w className={p.unsure ? "unsure" : ""} style={{ animationDelay: `${i * 30}ms` }}>{p.w}</w>{" "}
            </span>
          ))}
          {stage === "listening" && <span className="caret" />}
        </p>

        {stage === "review" && (
          <p style={{ fontSize: 12, color: "rgba(233,237,233,.5)", lineHeight: 1.5, margin: "4px 0 0", animation: "fadeUp .6s var(--spring) .1s both" }}>
            The underlined words are the ones I'm least sure of. Tap one to correct it before I use it.
          </p>
        )}

        <div style={{ display: "flex", gap: 9, marginTop: 20 }}>
          {stage === "listening" ? (
            <>
              <button className="btn btn-sm" style={{ flex: 1, background: "rgba(233,237,233,.17)", color: "#F4F7F3", border: "1px solid rgba(233,237,233,.26)" }} onClick={onClose}>Cancel</button>
              <button className="btn btn-brass btn-sm" style={{ flex: 1 }} onClick={() => { setN(PHRASE.length); setStage("review"); }}>
                <IcStop size={13} /> Stop
              </button>
            </>
          ) : (
            <>
              <button className="btn btn-sm" style={{ background: "rgba(233,237,233,.17)", color: "#F4F7F3", border: "1px solid rgba(233,237,233,.26)" }}
                onClick={() => { setN(0); setMs(0); setStage("listening"); }}>Re-record</button>
              <button className="btn btn-brass btn-sm" style={{ flex: 1 }}
                onClick={() => onSend(text, { kind: "voice", dur })}>Ask Kira <IcArrow size={14} /></button>
            </>
          )}
        </div>
      </div>
    </>
  );
}

/* ---------- receipt capture ---------- */
const SampleReceipt = () => (
  <div className="receipt">
    <div style={{ textAlign: "center", fontWeight: 800, letterSpacing: ".12em", fontSize: 9 }}>NASI KANDAR PELITA</div>
    <div style={{ textAlign: "center", opacity: .6 }}>JLN AMPANG, KUALA LUMPUR</div>
    <hr />
    <div className="r-row"><span>NASI PUTIH</span><span>2.00</span></div>
    <div className="r-row"><span>AYAM GORENG</span><span>7.50</span></div>
    <div className="r-row"><span>SAYUR CAMPUR</span><span>3.00</span></div>
    <div className="r-row"><span>TELUR DADAR</span><span>2.50</span></div>
    <div className="r-row"><span>TEH TARIK</span><span>3.90</span></div>
    <hr />
    <div className="r-row r-tot"><span>TOTAL</span><span>18.90</span></div>
    <div className="r-row" style={{ opacity: .6, marginTop: 4 }}><span>03/09/26</span><span>12:38</span></div>
  </div>
);

const FIELDS = [
  ["Merchant", "Nasi Kandar Pelita", 0.94],
  ["Total", "RM18.90", 0.97],
  ["Date", "3 Sep 2026, 12:38", 0.91],
  ["Category", "Food · lunch", 0.83],
];

function ScanSheet({ onClose, onSend, onDraft }) {
  const [stage, setStage] = useState("pick");
  const [src, setSrc] = useState(null);
  const fileRef = useRef(null);

  const beginScan = (dataUrl) => {
    setSrc(dataUrl || null);
    setStage("scanning");
    setTimeout(() => setStage("result"), 2600);
  };

  const onFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = () => beginScan(String(r.result));
    r.readAsDataURL(f);
  };

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="sheet" role="dialog" aria-label="Scan a receipt">
        <div className="grab" />
        <div className="sheet-head">
          <div>
            <p className="eyebrow on-ink" style={{ margin: 0 }}>
              {stage === "pick" ? "Receipt" : stage === "scanning" ? "Reading" : "Draft · not counted yet"}
            </p>
            <h2 style={{ margin: "5px 0 0", fontSize: 20, fontWeight: 800, letterSpacing: "-.03em" }}>
              {stage === "pick" ? "Show me the receipt" : stage === "scanning" ? "Reading the receipt" : "Here's what I read"}
            </h2>
          </div>
          <button className="xbtn" onClick={onClose} aria-label="Close"><IcX size={16} /></button>
        </div>

        {stage === "pick" && (
          <>
            <div className="pick-grid">
              <button className="pick" onClick={() => fileRef.current?.click()}>
                <IcCam size={22} />
                <b>Choose a photo</b>
                <span>Camera roll or a fresh shot.</span>
              </button>
              <button className="pick" onClick={() => beginScan(null)}>
                <IcImg size={22} />
                <b>Use a sample</b>
                <span>A Malaysian lunch receipt.</span>
              </button>
            </div>
            <input ref={fileRef} type="file" accept="image/*" onChange={onFile} style={{ display: "none" }} />
            <p style={{ fontSize: 12, color: "rgba(233,237,233,.5)", lineHeight: 1.5, margin: "16px 0 0" }}>
              The photo stays on your phone until you confirm the draft. I read it, I don't keep it.
            </p>
          </>
        )}

        {stage !== "pick" && (
          <div className="scanframe">
            {src ? <img src={src} alt="Receipt" /> : <SampleReceipt />}
            {stage === "scanning" && (
              <>
                <span className="laser" />
                <span className="brk" style={{ top: 14, left: 14, borderRight: "none", borderBottom: "none", borderRadius: "6px 0 0 0" }} />
                <span className="brk" style={{ top: 14, right: 14, borderLeft: "none", borderBottom: "none", borderRadius: "0 6px 0 0", animationDelay: ".08s" }} />
                <span className="brk" style={{ bottom: 14, left: 14, borderRight: "none", borderTop: "none", borderRadius: "0 0 0 6px", animationDelay: ".16s" }} />
                <span className="brk" style={{ bottom: 14, right: 14, borderLeft: "none", borderTop: "none", borderRadius: "0 0 6px 0", animationDelay: ".24s" }} />
              </>
            )}
          </div>
        )}

        {stage === "scanning" && (
          <div style={{ display: "flex", alignItems: "center", gap: 11, marginTop: 16 }}>
            <span className="thinking"><i /><i /><i /></span>
            <span style={{ fontSize: 13, color: "rgba(233,237,233,.6)" }}>Finding the merchant, the total and the date…</span>
          </div>
        )}

        {stage === "result" && (
          <>
            <div style={{ marginTop: 16 }}>
              {FIELDS.map(([k, v, c], i) => (
                <div className="field" key={k} style={{ animationDelay: `${i * 90}ms` }}>
                  <span className="field-l">{k}</span>
                  <span className="field-v">{v}</span>
                  <span className="field-c">
                    <i style={{ width: `${c * 100}%`, animationDelay: `${0.3 + i * 0.09}s` }} />
                    <span>{Math.round(c * 100)}%</span>
                  </span>
                </div>
              ))}
            </div>
            <p style={{ fontSize: 12, color: "rgba(233,237,233,.5)", lineHeight: 1.5, margin: "14px 0 0", animation: "fadeUp .6s var(--spring) .4s both" }}>
              Five line items came to RM18.90. Nothing enters your ledger until you confirm it.
            </p>
            <div style={{ display: "flex", gap: 9, marginTop: 18 }}>
              <button className="btn btn-sm" style={{ flex: 1, background: "rgba(233,237,233,.17)", color: "#F4F7F3", border: "1px solid rgba(233,237,233,.26)" }}
                onClick={() => onDraft(src)}>Save as draft</button>
              <button className="btn btn-brass btn-sm" style={{ flex: 1 }}
                onClick={() => onSend("What does this receipt do to my day?", { kind: "image", src })}>
                Ask Kira <IcArrow size={14} />
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );
}

function Butler({ thread, ask, approval, scenario, setScenario, applyPlan, setApproval, say, planVersion, onDraft }) {
  const [text, setText] = useState("");
  const [sheet, setSheet] = useState(null);
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [thread, approval]);

  const sendFrom = (q, att) => { setSheet(null); ask(q, att); };

  const prompts = ["Can I afford RM60 dinner tonight?", "Why did safe-to-spend drop?", "I overspent RM120 this weekend", "How is my wedding goal doing?"];

  return (
    <>
      <div className="topbar" style={{ paddingBottom: 10 }}>
        <div>
          <p className="eyebrow on-ink" style={{ margin: 0, animation: "fadeUp .6s var(--spring) both" }}>Butler · plan v{planVersion}</p>
          <h1 style={{ color: "#EDF1ED", animation: "fadeUp .7s var(--spring) .07s both" }}>Ask me anything about your money</h1>
        </div>
      </div>

      <div className="pad" style={{ paddingBottom: 176, display: "flex", flexDirection: "column", gap: 20 }}>
        {thread.length === 0 && (
          <p className="voice" style={{ fontSize: 20, lineHeight: 1.45, color: "rgba(233,237,233,.82)", margin: "6px 0 0", animation: "fadeUp .8s var(--spring) .2s both" }}>
            I answer from your confirmed transactions only, and I show you the numbers I used. I can't move money — that isn't mine to do.
          </p>
        )}

        {thread.map((m, i) =>
          m.role === "user" ? (
            <div className="bubble-user" key={i}>
              {m.att?.kind === "image" && (m.att.src
                ? <img className="att-img" src={m.att.src} alt="Receipt" />
                : <span className="att"><IcImg size={14} /> Receipt · RM18.90</span>)}
              {m.att?.kind === "voice" && (
                <span className="att">
                  <span className="att-bars">
                    {[0, 1, 2, 3, 4].map((b) => <i key={b} style={{ animationDelay: `${b * 0.13}s` }} />)}
                  </span>
                  Voice · {m.att.dur}
                </span>
              )}
              <span style={{ display: "block" }}>{m.text}</span>
            </div>
          ) : m.thinking ? (
            <div className="thinking" key={i}><i /><i /><i /></div>
          ) : (
            <div className="bubble-kira" key={i}>
              <p className="kira-say"><Words text={m.head} /></p>
              <p className="kira-sub">{m.sub}</p>
              <div className="evidence">
                <span className="eyebrow on-ink" style={{ marginBottom: 2, animation: "rowIn .5s var(--spring) .55s both" }}>What I used</span>
                {m.ev.map(([k, v], j) => (
                  <div className="ev-row" key={k} style={{ animationDelay: `${0.62 + j * 0.08}s` }}>
                    <span>{k}</span><b>{v}</b>
                  </div>
                ))}
              </div>

              {m.approval && approval && (
                <div className="approval">
                  <span className="eyebrow on-ink" style={{ color: "var(--brass-lit)" }}>Proposed plan change · draft</span>
                  {approval === "done" ? (
                    <div style={{ marginTop: 12 }}>
                      <p className="kira-say" style={{ fontSize: 17 }}><Words text={`Applied. Your plan is now v${planVersion}.`} /></p>
                      <p className="kira-sub" style={{ marginTop: 7 }}>I logged who approved it and when. You can undo this from Safety.</p>
                    </div>
                  ) : (
                    <>
                      {[
                        { id: "s1", t: "Spread it over 6 days", d: "RM20 a day less until Tuesday. Goal date unchanged.", tag: "Goal protected" },
                        { id: "s2", t: "Take it from this month's saving", d: "Wedding contribution drops to RM330. Goal date moves 8 days later.", tag: "Goal slips" },
                      ].map((s) => (
                        <button key={s.id} className={`scenario ${scenario === s.id ? "sel" : ""}`} onClick={() => setScenario(s.id)}>
                          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                            <b style={{ fontSize: 14, letterSpacing: "-.01em" }}>{s.t}</b>
                            <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: s.id === "s1" ? "var(--brass-lit)" : "rgba(233,237,233,.45)", flex: "none", marginTop: 2 }}>{s.tag}</span>
                          </div>
                          <p style={{ margin: "5px 0 0", fontSize: 12.5, color: "rgba(233,237,233,.62)", lineHeight: 1.45 }}>{s.d}</p>
                        </button>
                      ))}
                      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                        <button className="btn btn-brass btn-sm" style={{ flex: 1 }} onClick={applyPlan}>Approve</button>
                        <button className="btn btn-sm" style={{ background: "rgba(233,237,233,.17)", color: "#F4F7F3", border: "1px solid rgba(233,237,233,.26)" }}
                          onClick={() => say("Editing lets you change the daily amount before approving.")}>Edit</button>
                        <button className="btn btn-sm" style={{ background: "rgba(233,237,233,.17)", color: "#F4F7F3", border: "1px solid rgba(233,237,233,.26)" }}
                          onClick={() => { setApproval(null); say("Rejected. Nothing changed."); }}>Reject</button>
                      </div>
                      <p style={{ margin: "11px 0 0", fontSize: 11.5, color: "rgba(233,237,233,.45)", lineHeight: 1.45 }}>
                        Nothing changes until you approve. Rent, the loan minimum and your buffer are off limits in both options.
                      </p>
                    </>
                  )}
                </div>
              )}
            </div>
          )
        )}

        <div ref={endRef} />

        {thread.length === 0 && (
          <div className="chips" style={{ marginTop: 4 }}>
            {prompts.map((p, i) => (
              <button className="chip" key={p} style={{ animationDelay: `${0.4 + i * 0.09}s` }} onClick={() => ask(p)}>{p}</button>
            ))}
          </div>
        )}
      </div>

      <div className="composer">
        <input value={text} placeholder="Ask, speak, or show me a receipt…"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { ask(text); setText(""); } }} />
        <button className="cbtn" onClick={() => setSheet("scan")} aria-label="Scan a receipt"><IcCam size={19} w={1.9} /></button>
        <button className="cbtn" onClick={() => setSheet("voice")} aria-label="Record a voice note"><IcMic size={19} w={1.9} /></button>
        <button className="send" onClick={() => { ask(text); setText(""); }} aria-label="Send"><IcArrow size={18} w={2.1} /></button>
      </div>

      {sheet === "voice" && <VoiceSheet onClose={() => setSheet(null)} onSend={sendFrom} />}
      {sheet === "scan" && (
        <ScanSheet onClose={() => setSheet(null)} onSend={sendFrom}
          onDraft={(src) => { setSheet(null); onDraft(src); }} />
      )}
    </>
  );
}

/* ============================================================
   PLAN
   ============================================================ */
function OptionCard({ o, selected, safeToday, onPick }) {
  const tilt = useTilt(4.5);
  const share = Math.min(1, o.sen / Math.max(safeToday, 1));
  const hot = share > 0.8;
  return (
    <button ref={tilt.ref} onMouseMove={tilt.onMouseMove} onMouseLeave={tilt.onMouseLeave}
      className={`opt ${selected ? "sel" : ""}`} onClick={onPick}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <span className="tag">{o.food}</span>
          <b style={{ display: "block", fontSize: 16, letterSpacing: "-.02em", marginTop: 4 }}>{o.place}</b>
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{o.move} · arrive {o.arrive}</span>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="money" style={{ fontSize: 20 }}>{fmt(o.sen)}</div>
          <span className="tag" style={{ color: "var(--brass)" }}>{o.conf}</span>
        </div>
      </div>
      <div className="meter">
        {Array.from({ length: 10 }).map((_, i) => (
          <i key={i} className={i < Math.round(share * 10) ? (hot ? "hot" : "on") : ""} style={{ animationDelay: `${i * 45}ms` }} />
        ))}
      </div>
      <p style={{ margin: "9px 0 0", fontSize: 12.5, color: hot ? "var(--clay)" : "var(--muted)", lineHeight: 1.45 }}>
        Uses {Math.round(share * 100)}% of today's room. {o.why}
      </p>
    </button>
  );
}

function Plan({ safeToday, chosenPlan, setChosenPlan, say, addAudit, setTab, goals, setGoals, goalReserve, balance }) {
  const [seg, setSeg] = useState("goal");
  const [sheet, setSheet] = useState(null); // {goal} | {horizon}
  const monthlyTotal = goals.reduce((a, g) => a + g.monthly, 0);
  const byHorizon = (h) => goals.find((g) => g.horizon === h);

  const saveGoal = (g) => {
    setGoals((list) => (list.some((x) => x.id === g.id) ? list.map((x) => (x.id === g.id ? g : x)) : [...list, g]));
    addAudit(`${goals.some((x) => x.id === g.id) ? "Goal updated" : "Goal created"} — ${g.name} · RM${fmt(g.monthly)}/month`);
    say(`${g.name} saved. RM${fmt(g.monthly)} a month, ready ${monthLabel(monthsLeft(g))}.`);
    setSheet(null);
  };
  const removeGoal = (id) => {
    const g = goals.find((x) => x.id === id);
    setGoals((list) => list.filter((x) => x.id !== id));
    addAudit(`Goal deleted — ${g?.name}`);
    say("Goal removed. That money goes back into what's unclaimed.");
    setSheet(null);
  };
  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0, animation: "fadeUp .6s var(--spring) both" }}>Plan</p>
          <h1 key={seg} style={{ animation: "fadeUp .55s var(--spring) both" }}>
            {seg === "goal" ? "One goal, protected" : "Lunch and the trip there"}
          </h1>
        </div>
      </div>

      <div className="pad">
        <div className="seg-toggle">
          <span className="seg-thumb" style={{ transform: `translateX(${seg === "goal" ? 0 : "calc(100% + 5px)"})` }} />
          {[["goal", "Goal"], ["day", "Plan my day"]].map(([k, l]) => (
            <button key={k} className={`seg-btn ${seg === k ? "on" : ""}`} onClick={() => setSeg(k)}>{l}</button>
          ))}
        </div>

        <div key={seg} style={{ animation: "pageIn .5s var(--spring) both" }}>
          {seg === "goal" ? (
            <>
              <Reveal style={{ marginTop: 16 }}>
                <section className="capbar">
                  <div className="cap-row">
                    <div>
                      <p className="eyebrow on-ink" style={{ margin: 0 }}>Going to your goals</p>
                      <div style={{ marginTop: 9 }}><Odometer sen={monthlyTotal} size={32} /><span className="per">/month</span></div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <p className="eyebrow on-ink" style={{ margin: 0 }}>Held this cycle</p>
                      <div className="money" style={{ fontSize: 17, color: "#EDF1ED", marginTop: 7 }}>RM{fmt(goalReserve)}</div>
                    </div>
                  </div>
                  <p className="voice" style={{ margin: "14px 0 0", fontSize: 14.5, color: "rgba(233,237,233,.78)" }}>
                    {goals.length === 2
                      ? "One goal you'll reach this year, one you're building toward. Both are set aside before I tell you what's safe to spend."
                      : goals.length === 1
                        ? "One goal running. Add the other horizon and I'll recalculate what today can take."
                        : "No goals yet. Set one up and I'll work out what it costs you per day."}
                  </p>
                </section>
              </Reveal>

              {["short", "long"].map((h, i) => {
                const g = byHorizon(h);
                const H = HORIZONS[h];
                return (
                  <Reveal key={h} delay={60 + i * 60} style={{ marginTop: 14 }}>
                    {g ? (
                      <GoalCard g={g} onEdit={() => setSheet({ goal: g })} />
                    ) : (
                      <button className="card tapp addgoal" onClick={() => setSheet({ horizon: h })}>
                        <span className="addgoal-ic" style={{ color: H.stroke, borderColor: `${H.stroke}55` }}>+</span>
                        <span style={{ flex: 1, textAlign: "left" }}>
                          <b style={{ fontSize: 15, letterSpacing: "-.02em", display: "block" }}>Add a {H.label.toLowerCase()} goal</b>
                          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{H.blurb} · {H.presets.slice(0, 2).join(", ")}…</span>
                        </span>
                        <IcChev size={17} />
                      </button>
                    )}
                  </Reveal>
                );
              })}

              <Reveal delay={60} style={{ marginTop: 16 }}>
                <section className="card">
                  <p className="eyebrow" style={{ margin: "0 0 12px" }}>Protected rules</p>
                  {[["Emergency buffer", `RM${fmt(BUFFER)} · never spendable`], ["Rent", "RM1,200 · reserved from payday"], ["Car loan minimum", "RM520 · reserved"],
                    ...goals.map((g) => [g.name, `RM${fmt(g.monthly)} · reducible with approval`])].map(([k, v], i) => (
                    <div key={k} style={{ display: "flex", gap: 11, alignItems: "center", padding: "11px 0", borderBottom: "1px solid var(--line)", animation: `rowIn .55s var(--spring) ${i * 70}ms both` }}>
                      <span style={{ color: "var(--brass)" }}><IcLock size={16} /></span>
                      <span style={{ flex: 1 }}>
                        <b style={{ fontSize: 14 }}>{k}</b>
                        <span style={{ display: "block", fontSize: 12, color: "var(--muted)" }}>{v}</span>
                      </span>
                    </div>
                  ))}
                  <p className="voice" style={{ margin: "14px 0 0", fontSize: 13.5, color: "var(--muted)" }}>
                    A scenario can never propose touching the first three. Goal contributions can move, but only with your approval.
                  </p>
                </section>
              </Reveal>

              {goals.length > 0 && (
                <Reveal delay={60} style={{ marginTop: 16 }}>
                  <section className="card">
                    <p className="eyebrow" style={{ margin: "0 0 11px" }}>If you changed {goals[goals.length - 1].name}</p>
                    {[-0.25, 0, 0.25].map((d, i) => {
                      const g = goals[goals.length - 1];
                      const m = Math.max(500, Math.round((g.monthly * (1 + d)) / 500) * 500);
                      const when = monthLabel(Math.max(1, Math.ceil((g.target - g.saved) / m)));
                      return (
                        <div key={d} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "11px 0", borderBottom: i < 2 ? "1px solid var(--line)" : "none" }}>
                          <span>
                            <b style={{ fontSize: 14, letterSpacing: "-.01em" }}>RM{fmt(m)}/month</b>
                            <span style={{ display: "block", fontSize: 12, color: "var(--muted)" }}>Ready {when}</span>
                          </span>
                          <span className="tag" style={{ color: d === 0 ? "var(--brass)" : d < 0 ? "var(--clay)" : "var(--jade)" }}>
                            {d === 0 ? "current" : d < 0 ? "slower" : "faster"}
                          </span>
                        </div>
                      );
                    })}
                  </section>
                </Reveal>
              )}
            </>
          ) : (
            <>
              <Reveal style={{ marginTop: 16 }}>
                <section className="card-flat">
                  <p className="eyebrow" style={{ margin: "0 0 9px" }}>What I'm working with</p>
                  {[["From", "KLCC office · shared once, for this plan"], ["Back by", "1:15 pm call"], ["Preference", "Halal · no rush food"], ["Room today", `RM${fmt(safeToday)}`]].map(([k, v], i) => (
                    <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "6px 0", fontSize: 12.5, animation: `rowIn .5s var(--spring) ${i * 60}ms both` }}>
                      <span style={{ color: "var(--muted)" }}>{k}</span><b style={{ textAlign: "right" }}>{v}</b>
                    </div>
                  ))}
                </section>
              </Reveal>

              <Reveal delay={40} style={{ marginTop: 14 }}>
                <button className="card tapp" style={{ width: "100%", textAlign: "left", display: "flex", gap: 13, alignItems: "center",
                  background: "linear-gradient(150deg,#F6F3EA,#EFEFE7)", border: "1px solid rgba(169,133,63,.28)" }}
                  onClick={() => setTab("places")}>
                  <span style={{ width: 38, height: 38, borderRadius: 13, background: "rgba(169,133,63,.16)", color: "var(--brass)", display: "grid", placeItems: "center", flex: "none" }}>
                    <IcPin size={19} />
                  </span>
                  <span style={{ flex: 1 }}>
                    <b style={{ fontSize: 14.5, display: "block", letterSpacing: "-.01em" }}>Search places near me</b>
                    <span style={{ fontSize: 12.5, color: "var(--muted)" }}>On a map, filtered by what today can take.</span>
                  </span>
                  <IcChev size={17} />
                </button>
              </Reveal>

              <p className="eyebrow" style={{ margin: "20px 0 11px" }}>Or three I've already costed</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                {DAY_OPTIONS.map((o, i) => (
                  <Reveal key={o.id} delay={i * 90}>
                    <OptionCard o={o} selected={chosenPlan?.id === o.id} safeToday={safeToday}
                      onPick={() => { setChosenPlan(o); addAudit(`Day plan selected — ${o.place}`); say(`${o.place} it is. I've pencilled RM${fmt(o.sen)} against today.`); }} />
                  </Reveal>
                ))}
              </div>

              {chosenPlan && (
                <section className="hero" key={chosenPlan.id} style={{ marginTop: 16, animation: "approvalIn .8s var(--spring-2) both" }}>
                  <p className="eyebrow on-ink" style={{ margin: 0 }}>Effect on your wedding goal</p>
                  <p className="voice" style={{ fontSize: 18, margin: "11px 0 0", color: "#F1F4F0" }}>
                    {chosenPlan.effect === "tight"
                      ? "None, if tomorrow stays under RM40. Otherwise I'll offer you a recovery scenario."
                      : "None. This sits inside today's room and your contribution is untouched."}
                  </p>
                  <div className="evidence" style={{ marginTop: 15 }}>
                    {[["Estimated outing", `RM${fmt(chosenPlan.sen)}`], ["Room left today", `RM${fmt(Math.max(0, safeToday - chosenPlan.sen))}`], ["Arrive by", chosenPlan.arrive]].map(([k, v], j) => (
                      <div className="ev-row" key={k} style={{ animationDelay: `${0.3 + j * 0.09}s` }}><span>{k}</span><b>{v}</b></div>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                    <button className="btn btn-brass btn-sm" style={{ flex: 1 }} onClick={() => say(`Opening Maps with the route to ${chosenPlan.place}.`)}>Open in Maps</button>
                    <button className="btn btn-sm" style={{ background: "rgba(233,237,233,.17)", color: "#F4F7F3", border: "1px solid rgba(233,237,233,.26)" }} onClick={() => setTab("butler")}>Ask Kira</button>
                  </div>
                  <p style={{ margin: "12px 0 0", fontSize: 11.5, color: "rgba(233,237,233,.5)", lineHeight: 1.45 }}>
                    Prices are estimates from venue price level and your own history — not live menu prices.
                  </p>
                </section>
              )}
            </>
          )}
        </div>
      </div>

      {sheet && (
        <GoalSheet goal={sheet.goal} horizon={sheet.horizon} goals={goals} balance={balance}
          onSave={saveGoal} onDelete={removeGoal} onClose={() => setSheet(null)} />
      )}
    </>
  );
}

/* ============================================================
   GOAL SETUP — solver decides, Kira explains
   ============================================================ */
function GoalSheet({ goal, horizon, goals, balance, onSave, onDelete, onClose }) {
  const editing = !!goal;
  const h = goal?.horizon || horizon;
  const H = HORIZONS[h];
  const [name, setName] = useState(goal?.name || "");
  const [target, setTarget] = useState(goal?.target ?? (h === "short" ? 200000 : 800000));
  const [saved, setSaved] = useState(goal?.saved ?? 0);
  const [months, setMonths] = useState(goal ? monthsLeft(goal) : h === "short" ? 6 : 18);

  const span = h === "short" ? { min: 1, max: 12 } : { min: 12, max: 60 };
  const maxTarget = h === "short" ? 500000 : 5000000;

  /* the deterministic part */
  const required = Math.max(500, Math.ceil((target - saved) / months / 500) * 500);
  const draft = { ...(goal || {}), horizon: h, monthly: required, target, saved };
  const others = goals.filter((g) => g.id !== goal?.id);
  const newReserve = others.reduce((a, g) => a + cycleReserve(g), 0) + cycleReserve(draft);
  const room = Math.floor((balance - RESERVED - BUFFER - newReserve) / DAYS_TO_PAYDAY);
  const verdict = room >= 4500 ? "ok" : room >= 3000 ? "tight" : "over";

  const valid = name.trim().length > 0 && target > saved;

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="sheet" role="dialog" aria-label={editing ? "Edit goal" : "New goal"}>
        <div className="grab" />
        <div className="sheet-head">
          <div style={{ flex: 1 }}>
            <p className="eyebrow on-ink" style={{ margin: 0 }}>{H.label} · {H.blurb}</p>
            <h2 style={{ margin: "5px 0 0", fontSize: 20, fontWeight: 800, letterSpacing: "-.03em" }}>
              {editing ? "Edit this goal" : "What are you saving for?"}
            </h2>
          </div>
          <button className="xbtn" onClick={onClose} aria-label="Close"><IcX size={16} /></button>
        </div>

        <input className="dinput" value={name} placeholder="Give it a name" maxLength={28}
          onChange={(e) => setName(e.target.value)} />
        {!editing && (
          <div className="filters" style={{ marginTop: 10 }}>
            {H.presets.map((x) => (
              <button key={x} className={`dchip ${name === x ? "on" : ""}`} onClick={() => setName(x)}>{x}</button>
            ))}
          </div>
        )}

        <div className="fieldset">
          <div className="fs-head">
            <span className="eyebrow on-ink">Target amount</span>
            <Odometer sen={target} size={26} />
          </div>
          <input className="slider" type="range" min={h === "short" ? 20000 : 100000} max={maxTarget} step={5000}
            value={target} onChange={(e) => setTarget(Number(e.target.value))} aria-label="Target amount" />
        </div>

        <div className="fieldset">
          <div className="fs-head">
            <span className="eyebrow on-ink">Already saved</span>
            <span className="money" style={{ fontSize: 16, color: "#EDF1ED" }}>RM{fmt(saved)}</span>
          </div>
          <input className="slider" type="range" min={0} max={target} step={5000}
            value={Math.min(saved, target)} onChange={(e) => setSaved(Number(e.target.value))} aria-label="Already saved" />
        </div>

        <div className="fieldset">
          <div className="fs-head">
            <span className="eyebrow on-ink">Have it by</span>
            <div className="stepper">
              <button onClick={() => setMonths((m) => Math.max(span.min, m - 1))} aria-label="Sooner">−</button>
              <span>{monthLabel(months)}</span>
              <button onClick={() => setMonths((m) => Math.min(span.max, m + 1))} aria-label="Later">+</button>
            </div>
          </div>
          <p className="fs-note">{months} month{months > 1 ? "s" : ""} from now</p>
        </div>

        <div className={`solver solver-${verdict}`}>
          <div className="cap-row">
            <div>
              <p className="eyebrow on-ink" style={{ margin: 0 }}>You'd need to put aside</p>
              <div style={{ marginTop: 8 }}><Odometer sen={required} size={30} /><span className="per">/month</span></div>
            </div>
            <div style={{ textAlign: "right" }}>
              <p className="eyebrow on-ink" style={{ margin: 0 }}>Leaves you</p>
              <div className="money" style={{ fontSize: 17, color: "#EDF1ED", marginTop: 7 }}>RM{fmt(Math.max(0, room))}/day</div>
            </div>
          </div>
          <p className="voice" style={{ margin: "13px 0 0", fontSize: 14.5, color: "rgba(233,237,233,.8)" }}>
            {verdict === "ok"
              ? `That fits. Your daily room stays healthy and nothing touches rent, the loan minimum or your RM${fmt(BUFFER)} buffer.`
              : verdict === "tight"
                ? `Workable, but tight. You'd be deciding on about RM${fmt(Math.max(0, room))} a day, so one bad week would need a recovery scenario.`
                : `Too aggressive. At this pace there isn't enough left to live on day to day — give it more months, or lower the target.`}
          </p>
        </div>

        <div style={{ display: "flex", gap: 9, marginTop: 18 }}>
          {editing && (
            <button className="btn btn-sm" style={{ color: "#F0C4BB", background: "rgba(154,74,59,.24)", border: "1px solid rgba(200,110,92,.4)" }}
              onClick={() => onDelete(goal.id)}>Delete</button>
          )}
          <button className="btn btn-brass btn-sm" style={{ flex: 1 }} disabled={!valid}
            onClick={() => onSave({
              id: goal?.id || `g${Date.now()}`, horizon: h, name: name.trim(),
              target, saved, monthly: required, note: goal?.note || "",
            })}>
            {editing ? "Save changes" : "Create goal"}
          </button>
        </div>
        <p style={{ margin: "12px 0 0", fontSize: 11.5, color: "rgba(233,237,233,.45)", lineHeight: 1.5 }}>
          The monthly figure is calculated, not suggested. Change the date or the target and it recalculates before you commit.
        </p>
      </div>
    </>
  );
}

function GoalCard({ g, onEdit }) {
  const pct = Math.min(1, g.saved / g.target);
  const H = HORIZONS[g.horizon];
  const left = monthsLeft(g);
  return (
    <section className="card" style={{ display: "flex", gap: 16, alignItems: "center" }}>
      <span className="ringwrap" style={{ width: 78, height: 78 }}>
        <Ring pct={pct} size={78} stroke={H.stroke} />
        <figcaption>
          <b className="money" style={{ fontSize: 16 }}>{Math.round(pct * 100)}%</b>
        </figcaption>
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <span className="htag" style={{ color: H.stroke, borderColor: `${H.stroke}55` }}>{H.label}</span>
        <b style={{ display: "block", fontSize: 16, letterSpacing: "-.02em", marginTop: 6 }}>{g.name}</b>
        <div className="money" style={{ fontSize: 15, marginTop: 3 }}>
          {fmt(g.saved)}<span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600 }}> / {fmt(g.target)}</span>
        </div>
        <p style={{ margin: "5px 0 0", fontSize: 12, color: "var(--muted)", lineHeight: 1.45 }}>
          RM{fmt(g.monthly)} a month · ready {monthLabel(left)}
        </p>
      </div>
      <button className="btn btn-line btn-sm" style={{ flex: "none" }} onClick={onEdit}>Edit</button>
    </section>
  );
}

/* ============================================================
   PLACES — money-constrained discovery
   ============================================================ */
function Places({ setTab, safeToday, setChosenPlan, say, addAudit }) {
  const { L, failed } = useLeaflet();
  const [origin, setOrigin] = useState({ ...KLCC, real: false });
  const [locState, setLocState] = useState("idle"); // idle | asking | ok | denied
  const [mode, setMode] = useState("walk");
  const [halalOnly, setHalalOnly] = useState(true);
  const [cap, setCap] = useState(safeToday);
  const [selected, setSelected] = useState(null);

  const useMyLocation = () => {
    if (!navigator.geolocation) return setLocState("denied");
    setLocState("asking");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setOrigin({ lat: pos.coords.latitude, lng: pos.coords.longitude, label: "Your location", real: true });
        setLocState("ok");
        addAudit("Location used once for a day plan", "You");
        say("Got it. Distances and travel costs are now measured from where you are.");
      },
      () => { setLocState("denied"); say("No location, so I'm planning from KLCC instead."); },
      { timeout: 8000, maximumAge: 60000 }
    );
  };

  const all = PLACES
    .map((p) => evaluate(p, origin, mode, safeToday))
    .filter((p) => (halalOnly ? p.halal : true))
    .sort((a, b) => a.total - b.total);
  const results = all.filter((p) => p.total <= cap);
  const hidden = all.length - results.length;
  const pick = results.find((p) => p.id === selected) || null;

  const maxCap = Math.max(safeToday * 2, 6000);
  const onSelect = useCallback((id) => setSelected((s) => (s === id ? null : id)), []);

  const gmapsUrl = (p) =>
    `https://www.google.com/maps/dir/?api=1&origin=${origin.lat},${origin.lng}` +
    `&destination=${encodeURIComponent(p.name)}&destination_place_id=&travelmode=${MODES[mode].gmaps}`;

  return (
    <>
      <div className="topbar" style={{ alignItems: "center" }}>
        <button className="btn btn-ghost btn-sm" style={{ width: 36, padding: 0, marginTop: 4 }} onClick={() => setTab("plan")} aria-label="Back">
          <IcBack size={17} />
        </button>
        <div style={{ flex: 1, marginLeft: 12 }}>
          <p className="eyebrow" style={{ margin: 0, animation: "fadeUp .6s var(--spring) both" }}>Near {origin.real ? "you" : "KLCC"}</p>
          <h1 style={{ fontSize: 21, animation: "fadeUp .7s var(--spring) .06s both" }}>What today's money can buy</h1>
        </div>
      </div>

      <div className="pad">
        <Reveal>
          <section className="capbar">
            <div className="cap-row">
              <div>
                <p className="eyebrow on-ink" style={{ margin: 0 }}>Spending ceiling</p>
                <div style={{ marginTop: 9 }}><Odometer sen={cap} size={34} /></div>
              </div>
              <div style={{ textAlign: "right" }}>
                <p className="eyebrow on-ink" style={{ margin: 0 }}>Room today</p>
                <div className="money" style={{ fontSize: 17, color: "#EDF1ED", marginTop: 7 }}>RM{fmt(safeToday)}</div>
              </div>
            </div>

            <input className="slider" type="range" min={500} max={maxCap} step={50} value={cap}
              onChange={(e) => setCap(Number(e.target.value))} aria-label="Spending ceiling" />
            <div className="cap-ticks">
              <span>RM5</span>
              <span style={{ color: cap > safeToday ? "var(--clay)" : "var(--brass-lit)" }}>
                {cap > safeToday ? "Above today's room" : "Inside today's room"}
              </span>
              <span>RM{fmt(maxCap)}</span>
            </div>

            <p className="voice" style={{ margin: "15px 0 0", fontSize: 14.5, color: "rgba(233,237,233,.78)" }}>
              {results.length === 0
                ? "Nothing fits that ceiling yet. Drag it up and I'll show you what appears."
                : `${results.length} place${results.length > 1 ? "s" : ""} fit, ${MODES[mode].label.toLowerCase()} from ${origin.real ? "where you are" : "KLCC"}. The price on each pin is the whole outing — meal and travel together.`}
            </p>
          </section>
        </Reveal>

        <Reveal delay={50} style={{ marginTop: 14 }}>
          <div className="filters">
            {Object.entries(MODES).map(([k, m]) => (
              <button key={k} className={`fchip ${mode === k ? "on" : ""}`} onClick={() => setMode(k)}>{m.label}</button>
            ))}
            <button className={`fchip ${halalOnly ? "on" : ""}`} onClick={() => setHalalOnly((h) => !h)}>Halal</button>
            <button className="fchip" onClick={useMyLocation} disabled={locState === "asking"}>
              {locState === "asking" ? "Locating…" : locState === "ok" ? "Located" : "Use my location"}
            </button>
          </div>
        </Reveal>

        <Reveal delay={70} style={{ marginTop: 14 }}>
          <div className="mapcard">
            {L ? (
              <LiveMap L={L} origin={origin} results={results} selected={selected} onSelect={onSelect} />
            ) : failed ? (
              <FallbackMap origin={origin} results={results} selected={selected} onSelect={onSelect} />
            ) : (
              <div className="map-load">
                <span className="thinking" style={{ filter: "invert(1) hue-rotate(180deg)" }}><i /><i /><i /></span>
              </div>
            )}
            <span className="map-veil" />
          </div>
        </Reveal>

        <Reveal delay={40} style={{ marginTop: 8 }}>
          <p style={{ fontSize: 11.5, color: "var(--muted)", lineHeight: 1.5, margin: 0 }}>
            {locState === "denied" && "Location declined, so I'm planning from KLCC. "}
            Pin colour is affordability, not distance: brass sits inside today's room, green uses most of it, red needs a recovery scenario.
          </p>
        </Reveal>

        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 18 }}>
          {results.map((p, i) => (
            <Reveal key={p.id} delay={i * 70}>
              <button className={`place ${selected === p.id ? "sel" : ""}`} onClick={() => onSelect(p.id)}>
                <span className="place-rank">{i + 1}</span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <b style={{ fontSize: 15, letterSpacing: "-.02em" }}>{p.name}</b>
                    {i === 0 && <span className="badge badge-best">Best fit</span>}
                  </span>
                  <span style={{ display: "block", fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
                    {p.kind} · {p.km < 1 ? `${Math.round(p.km * 1000)} m` : `${p.km.toFixed(1)} km`} · arrive {p.arrive}
                  </span>
                  <span style={{ display: "block", fontSize: 12, color: p.band === "over" ? "var(--clay)" : "var(--muted)", marginTop: 3 }}>
                    {Math.round(p.share * 100)}% of today's room
                    {p.travelSen > 0 && ` · incl. RM${fmt(p.travelSen)} travel`}
                  </span>
                </span>
                <span style={{ textAlign: "right", flex: "none" }}>
                  <span className="money" style={{ fontSize: 18, display: "block" }}>{fmt(p.total)}</span>
                  <span className="tag" style={{ color: "var(--brass)" }}>Est · {p.conf}</span>
                </span>
              </button>
            </Reveal>
          ))}

          {results.length === 0 && (
            <Reveal>
              <div className="card-flat empty-map">
                <p className="voice" style={{ margin: 0, fontSize: 16 }}>Nothing under RM{fmt(cap)} yet.</p>
                <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--muted)", lineHeight: 1.5 }}>
                  Raise the ceiling, walk instead of riding, or eat at home — groceries usually beat a delivered meal on the same money.
                </p>
              </div>
            </Reveal>
          )}

          {hidden > 0 && (
            <p style={{ fontSize: 12, color: "var(--muted-2)", textAlign: "center", margin: "4px 0 0" }}>
              {hidden} more {hidden > 1 ? "places sit" : "place sits"} above your ceiling.
            </p>
          )}
        </div>

        <Reveal delay={60} style={{ marginTop: 16 }}>
          <p style={{ fontSize: 11.5, color: "var(--muted-2)", lineHeight: 1.5, margin: 0 }}>
            Prices are estimates from price level and your own history, never live menu prices. Places come from a fixed demo set here;
            in the build they arrive through the Maps adapter.
          </p>
        </Reveal>
      </div>

      {pick && (
        <>
          <div className="scrim" onClick={() => setSelected(null)} />
          <div className="sheet" role="dialog" aria-label={pick.name}>
            <div className="grab" />
            <div className="sheet-head">
              <div style={{ flex: 1 }}>
                <p className="eyebrow on-ink" style={{ margin: 0 }}>{pick.kind} · {MODES[mode].label}</p>
                <h2 style={{ margin: "5px 0 0", fontSize: 20, fontWeight: 800, letterSpacing: "-.03em" }}>{pick.name}</h2>
              </div>
              <button className="xbtn" onClick={() => setSelected(null)} aria-label="Close"><IcX size={16} /></button>
            </div>

            <p className="voice" style={{ margin: 0, fontSize: 17, lineHeight: 1.45, color: "#F1F4F0" }}>
              {pick.band === "ok"
                ? `Comfortable. This leaves RM${fmt(Math.max(0, safeToday - pick.total))} for the rest of today and your wedding contribution is untouched.`
                : pick.band === "tight"
                  ? `This works, but it uses ${Math.round(pick.share * 100)}% of today's room. Tomorrow would need to stay light.`
                  : `This is RM${fmt(pick.total - safeToday)} over today's room. I'd have to propose a recovery scenario, and you'd have to approve it.`}
            </p>

            <div className="evidence" style={{ marginTop: 16 }}>
              {[
                ["Meal estimate", `RM${fmt(pick.sen)}`],
                ["Travel", pick.travelSen ? `RM${fmt(pick.travelSen)} · ${MODES[mode].label}` : "Free · on foot"],
                ["Total outing", `RM${fmt(pick.total)}`],
                ["Distance", pick.km < 1 ? `${Math.round(pick.km * 1000)} m` : `${pick.km.toFixed(1)} km`],
                ["Arrive by", pick.arrive],
                ["Confidence", `Estimate · ${pick.conf}`],
              ].map(([k, v], j) => (
                <div className="ev-row" key={k} style={{ animationDelay: `${0.1 + j * 0.07}s` }}><span>{k}</span><b>{v}</b></div>
              ))}
            </div>

            <p style={{ fontSize: 12, color: "rgba(233,237,233,.55)", lineHeight: 1.5, margin: "14px 0 0" }}>{pick.note}</p>

            <div style={{ display: "flex", gap: 9, marginTop: 18 }}>
              <button className="btn btn-sm" style={{ flex: 1, background: "rgba(233,237,233,.17)", color: "#F4F7F3", border: "1px solid rgba(233,237,233,.26)" }}
                onClick={() => window.open(gmapsUrl(pick), "_blank", "noopener")}>
                Open in Maps
              </button>
              <button className="btn btn-brass btn-sm" style={{ flex: 1 }}
                onClick={() => {
                  setChosenPlan({
                    id: pick.id, place: pick.name, food: pick.kind, move: `${MODES[mode].label}${pick.travelSen ? ` · RM${fmt(pick.travelSen)}` : ""}`,
                    sen: pick.total, conf: `Estimate · ${pick.conf}`, arrive: pick.arrive,
                    effect: pick.band === "ok" ? "safe" : "tight", why: pick.note,
                  });
                  addAudit(`Day plan selected — ${pick.name}`);
                  say(`${pick.name} added to today. RM${fmt(pick.total)} pencilled in.`);
                  setSelected(null);
                  setTab("plan");
                }}>
                Add to today
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}

/* ============================================================
   MORE + SUBPAGES
   ============================================================ */
function More({ setTab, drafts }) {
  const items = [
    ["accounts", "Accounts", "Read-only balances and imports"],
    ["bills", "Bills", "What's reserved before you spend"],
    ["safety", "Safety", "Confidence, consent, and the audit trail"],
  ];
  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0, animation: "fadeUp .6s var(--spring) both" }}>More</p>
          <h1 style={{ animation: "fadeUp .7s var(--spring) .06s both" }}>Settings and sources</h1>
        </div>
      </div>
      <div className="pad">
        <Reveal>
          <section className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
            {items.map(([k, t, s], i) => (
              <button key={k} className="rowlink" onClick={() => setTab(k)} style={{ animation: `rowIn .55s var(--spring) ${i * 80}ms both` }}>
                <span>
                  <b style={{ fontSize: 15, letterSpacing: "-.02em" }}>{t}</b>
                  <span style={{ display: "block", fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>{s}</span>
                </span>
                <IcChev size={17} />
              </button>
            ))}
          </section>
        </Reveal>
        <Reveal delay={80} style={{ marginTop: 16 }}>
          <div className="card-flat">
            <p className="eyebrow" style={{ margin: "0 0 8px" }}>This build</p>
            <p className="voice" style={{ margin: 0, fontSize: 14, color: "var(--muted)", lineHeight: 1.5 }}>
              Kira never moves money, recommends investments, or changes a plan quietly. {drafts.length > 0 ? `${drafts.length} draft${drafts.length > 1 ? "s are" : " is"} waiting and none of them count yet.` : "Every draft has been reviewed."}
            </p>
          </div>
        </Reveal>
      </div>
    </>
  );
}

function SubHead({ setTab, eyebrow, title }) {
  return (
    <div className="topbar" style={{ alignItems: "center" }}>
      <button className="btn btn-ghost btn-sm" style={{ width: 36, padding: 0, marginTop: 4 }} onClick={() => setTab("more")} aria-label="Back">
        <IcBack size={17} />
      </button>
      <div style={{ flex: 1, marginLeft: 12 }}>
        <p className="eyebrow" style={{ margin: 0, animation: "fadeUp .6s var(--spring) both" }}>{eyebrow}</p>
        <h1 style={{ fontSize: 21, animation: "fadeUp .7s var(--spring) .06s both" }}>{title}</h1>
      </div>
    </div>
  );
}

function Bills({ setTab, say }) {
  return (
    <>
      <SubHead setTab={setTab} eyebrow="Bills" title="Reserved before payday" />
      <div className="pad">
        <Reveal>
          <section className="hero">
            <p className="eyebrow on-ink" style={{ margin: 0 }}>Total reserved</p>
            <div style={{ marginTop: 10 }}><Odometer sen={RESERVED} size={40} /></div>
            <p className="voice" style={{ margin: "11px 0 0", fontSize: 14.5, color: "rgba(233,237,233,.75)" }}>
              Held back from your safe-to-spend so a bill never surprises you.
            </p>
          </section>
        </Reveal>
        <Reveal delay={60} style={{ marginTop: 16 }}>
          <section className="card">
            {COMMITMENTS.map((c, i) => (
              <div className="txn" key={c.id} style={{ animation: `rowIn .55s var(--spring) ${i * 70}ms both` }}>
                <span className="txn-ic" style={c.protected ? { background: "rgba(169,133,63,.14)", color: "var(--brass)" } : {}}>
                  {c.protected ? <IcLock size={16} /> : <IcBell size={16} />}
                </span>
                <span style={{ flex: 1 }}>
                  <b style={{ fontSize: 14.5, letterSpacing: "-.01em" }}>{c.name}</b>
                  <span style={{ display: "block", fontSize: 11.5, color: "var(--muted)" }}>
                    {c.due} · in {c.in} days{c.protected ? " · protected" : ""}
                  </span>
                </span>
                <span className="money" style={{ fontSize: 15 }}>{fmt(c.sen)}</span>
              </div>
            ))}
          </section>
        </Reveal>
        <Reveal delay={60} style={{ marginTop: 16 }}>
          <section className="card-flat">
            <p className="eyebrow" style={{ margin: "0 0 7px", color: "var(--brass)" }}>Worth a look</p>
            <p className="voice" style={{ margin: 0, fontSize: 15, lineHeight: 1.45 }}>
              Your streaming bundle has been charged for 7 months. You've opened it twice since June.
            </p>
            <button className="btn btn-line btn-sm" style={{ marginTop: 13 }} onClick={() => say("Kira opens the provider's cancellation page. It never cancels on your behalf.")}>
              Review it
            </button>
          </section>
        </Reveal>
      </div>
    </>
  );
}

function Accounts({ setTab, say, balance }) {
  return (
    <>
      <SubHead setTab={setTab} eyebrow="Accounts" title="Where the numbers come from" />
      <div className="pad">
        <Reveal>
          <section className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <p className="eyebrow" style={{ margin: "0 0 6px" }}>Cash account</p>
                <b style={{ fontSize: 16, letterSpacing: "-.02em" }}>Maybank · 4471</b>
                <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--muted)" }}>Read-only · synced 12:31</p>
              </div>
              <div className="money" style={{ fontSize: 20 }}>{fmt(balance)}</div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 15 }}>
              <button className="btn btn-ghost btn-sm" style={{ flex: 1 }} onClick={() => say("Refreshing balances. Kira only ever reads.")}>Refresh</button>
              <button className="btn btn-line btn-sm" onClick={() => say("Access revoked. Kira keeps your ledger and stops syncing.")}>Revoke access</button>
            </div>
          </section>
        </Reveal>
        <Reveal delay={70} style={{ marginTop: 16 }}>
          <section className="card">
            <p className="eyebrow" style={{ margin: "0 0 12px" }}>Other sources</p>
            {[["Touch 'n Go eWallet", "Not connected", false], ["CSV statement import", "Last import 1 Sep · 42 rows", true]].map(([a, b, ok]) => (
              <div key={a} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "11px 0", borderBottom: "1px solid var(--line)" }}>
                <span>
                  <b style={{ fontSize: 14 }}>{a}</b>
                  <span style={{ display: "block", fontSize: 12, color: "var(--muted)" }}>{b}</span>
                </span>
                <span className={`pill ${ok ? "" : "warn"}`} style={{ fontSize: 9.5 }}><span className="dot" />{ok ? "Active" : "Add"}</span>
              </div>
            ))}
            <button className="btn btn-primary btn-sm" style={{ width: "100%", marginTop: 15 }} onClick={() => say("Import a statement and Kira turns it into a review queue — not straight into your ledger.")}>
              Import a statement
            </button>
          </section>
        </Reveal>
      </div>
    </>
  );
}

function Safety({ setTab, audit, planVersion, say }) {
  const [loc, setLoc] = useState(true);
  const [approve, setApprove] = useState(true);
  return (
    <>
      <SubHead setTab={setTab} eyebrow="Safety" title="What Kira may and may not do" />
      <div className="pad">
        <Reveal>
          <section className="card">
            <p className="eyebrow" style={{ margin: "0 0 12px" }}>Trust boundaries</p>
            {[
              ["Ask before any plan change", approve, setApprove, "Kira drafts; you decide."],
              ["Use my location", loc, setLoc, "Only when you tap Plan my day."],
            ].map(([label, val, set, sub]) => (
              <div key={label} style={{ display: "flex", gap: 12, alignItems: "center", padding: "12px 0", borderBottom: "1px solid var(--line)" }}>
                <span style={{ flex: 1 }}>
                  <b style={{ fontSize: 14 }}>{label}</b>
                  <span style={{ display: "block", fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{sub}</span>
                </span>
                <button className="switch" onClick={() => set(!val)} aria-pressed={val}
                  style={{ background: val ? "var(--brass)" : "rgba(15,28,26,.16)" }}>
                  <i style={{ left: val ? 22 : 3 }} />
                </button>
              </div>
            ))}
            <div style={{ display: "flex", justifyContent: "space-between", padding: "13px 0 2px" }}>
              <span style={{ fontSize: 14, fontWeight: 700 }}>Money movement</span>
              <span className="tag" style={{ color: "var(--jade)" }}>Not possible in this build</span>
            </div>
          </section>
        </Reveal>

        <Reveal delay={70} style={{ marginTop: 16 }}>
          <section className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
              <p className="eyebrow" style={{ margin: 0 }}>Audit trail</p>
              <span className="tag">Plan v{planVersion}</span>
            </div>
            {audit.slice(0, 6).map((a, i) => (
              <div key={i} style={{ display: "flex", gap: 12, padding: "9px 0", borderBottom: i < Math.min(5, audit.length - 1) ? "1px solid var(--line)" : "none", animation: `rowIn .5s var(--spring) ${i * 65}ms both` }}>
                <span className="money" style={{ fontSize: 12, color: "var(--muted-2)", fontWeight: 600, width: 38, flex: "none" }}>{a.t}</span>
                <span style={{ flex: 1, fontSize: 13, lineHeight: 1.4 }}>{a.e}</span>
                <span className="tag" style={{ flex: "none" }}>{a.by}</span>
              </div>
            ))}
          </section>
        </Reveal>

        <Reveal delay={70} style={{ marginTop: 16 }}>
          <section className="card-flat">
            <p className="eyebrow" style={{ margin: "0 0 8px" }}>Your data</p>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btn-line btn-sm" style={{ flex: 1 }} onClick={() => say("Export requested. You'll get a file with every transaction and plan version.")}>Export</button>
              <button className="btn btn-line btn-sm" style={{ flex: 1, color: "var(--clay)", borderColor: "rgba(154,74,59,.35)" }} onClick={() => say("Deletion needs a second confirmation and removes provider tokens first.")}>Delete</button>
            </div>
          </section>
        </Reveal>
      </div>
    </>
  );
}
