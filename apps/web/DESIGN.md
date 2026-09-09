# Kira — design language

Kira already had a voice before this file existed. This is not a new direction; it
is the one in `src/styles/kira.css`, written down so it stops drifting.

The problem it solves: the stylesheet carried **27 distinct font sizes** and the
components another **19 inline**, covering nearly every half-pixel from 8 to 30.
Three people picking `14.5px` or `13px` by eye is not a type scale. Below is the
scale those values collapse into, chosen so almost nothing moves on screen.

Density note: this is a 390px phone surface, not a marketing page. The steps are
deliberately tight — ratios of 1.10–1.20, not the 1.33 a landing page would use.

---

## Character

Calm, ledger-like, Malaysian. Money is stated plainly and never dramatised. The
interface is paper-coloured. The figure that matters sits on the lightest,
most-lifted card on the screen — the number carries itself, so it does not need
a dark box to shout from. Dark is spent once per screen, on the surface where
Kira asks the user something. Brass is used for accrual and holding; jade for
safety; clay for warning. Never more than one accent in a single view.

The serif italic (`Newsreader`) is Kira's speaking voice. It appears only where
Kira addresses the user in a sentence. Anything the user must *read as data* is
`Manrope` with tabular figures. This split is the identity — keep it.

---

## Colour

Set on `.kira-root`.

| Token | Value | Use |
|---|---|---|
Two colours carry the app: **deep green and gold**. Green is the ground and every
surface — sage paper, forest ink, the one deep-green card each screen is allowed.
Gold is the only accent, and it is spent on money: what is held, what is yours to
decide, and what a press will do. Nothing else is coloured. Clay survives for
warning, because a warning must read as neither of the two.

Gold is a fill and a mark, not a text colour on paper: `--accent` at 12px on
`--surface` sits near 3.9:1. Set small text in `--ink` or `--label` and let gold
carry the figure marks, the fills and the rules. On the deep-green surfaces,
`--accent-lit` is the readable one.

| Token | Value | Use |
|---|---|---|
| `--paper` | `#E8EDE6` | app canvas |
| `--surface` | `#F8FBF7` | card fill |
| `--ink` | `#0B1F1A` | primary text |
| `--ink-2` | `#12332B` | dark gradient top |
| `--ink-3` | `#255146` | tertiary text, orb gradient |
| `--muted` | `#5A716A` | secondary text |
| `--muted-2` | `#879992` | labels — **see contrast note** |
| `--line` | `rgba(15,28,26,.09)` | hairlines |
| `--line-2` | `rgba(15,28,26,.16)` | button borders |
| `--accent` | `#B08C3E` | held / accrued money, focus ring, primary action |
| `--accent-lit` | `#E3C071` | the accent on a deep-green surface |
| `--accent-deep` | `#7A5F23` | the bottom of a gold gradient |
| `--gold-pale` | `#F2DFA6` | the lit end of the claim line |
| `--green-1` | `#17453A` | deep-green surface, top |
| `--green-2` | `#08201A` | deep-green surface, bottom |
| `--jade` | `#2C6B57` | safe, confirmed; the short-horizon goal bar |
| `--clay` | `#9A4A3B` | over budget, warning |

**Contrast note.** `--muted-2` on `--surface` is roughly 2.7:1 — below the 4.5:1
WCAG AA threshold for body text. It is the fill of `.eyebrow` and `.tag`, which
appear on every card. New tokens `--label` (`#6B7C77`) and `--label-on-ink`
raise these to passing without changing the impression. Use `--label` for any
text a user must read; `--muted-2` is now reserved for decorative rules and
disabled states.

### On the deep-green surfaces (the Today figure, Butler)

| Token | Value |
|---|---|
| `--on-ink` | `#EDF1ED` |
| `--on-ink-2` | `rgba(233,237,233,.78)` |
| `--on-ink-3` | `rgba(233,237,233,.58)` |
| `--on-ink-line` | `rgba(233,237,233,.16)` |

`--on-ink-3` replaces the several hand-written `rgba(233,237,233,.5)` labels,
which sat under 4.5:1 against the hero gradient.

---

## Type scale

Ten steps. The `--fs-*` names are positional so a step can be retuned without a
rename; the role column is what you match against.

| Token | Size | Role | Replaces |
|---|---|---|---|
| `--fs-1` | `9.5px` | nav labels, `.tag` | 8, 8.5, 9, 9.5 |
| `--fs-2` | `10.5px` | `.eyebrow`, uppercase section labels | 10, 10.5 |
| `--fs-3` | `11.5px` | caption, tertiary meta | 11, 11.5 |
| `--fs-4` | `12.5px` | secondary body, muted lines | 12, 12.5 |
| `--fs-5` | `13.5px` | **default body** | 13, 13.5 |
| `--fs-6` | `15px` | lead copy, Kira's voice | 14, 14.5, 15, 15.5 |
| `--fs-7` | `17px` | card titles | 16, 17 |
| `--fs-8` | `21px` | money figures, subheads | 18, 19, 20, 21, 22 |
| `--fs-9` | `25px` | screen headline | 24, 25, 26, 27 |
| `--fs-10` | `31px` | rare display line | 30, 31 |
| `--fs-hero` | `62px` | the Today odometer, and nothing else | — |

Weights: `400` body · `500` emphasis · `600` labels · `700` titles · `800`
display and figures. `650` and `750` are removed — they were unintentional.

Tracking: `-0.035em` at `--fs-9`, `-0.02em` at `--fs-8`/`--fs-7`, `-0.01em` at
title weight, `0` on body, `+0.19em` on `.eyebrow`, `+0.09em` on nav labels.
Large text tightens; small uppercase text opens.

Line height: `1.5` on serif voice copy, `1.4` on body, `1.15` on figures.

---

## Spacing

A 4px base with two off-grid steps — `11` and `22` — that the phone layout is
genuinely built on (the 22px screen gutter, the 11px icon-to-text gap). Keeping
them beats re-laying-out every card to satisfy a grid nobody sees.

| Token | Value | Typical use |
|---|---|---|
| `--s-1` | `4px` | icon nudge |
| `--s-2` | `6px` | label to value |
| `--s-3` | `8px` | inline gaps |
| `--s-4` | `11px` | icon to text |
| `--s-5` | `14px` | intra-card blocks |
| `--s-6` | `16px` | **card to card** |
| `--s-7` | `20px` | section breaks |
| `--s-8` | `22px` | screen gutter, card padding |
| `--s-9` | `26px` | major separation |
| `--s-10` | `32px` | figure to claim line |
| `--s-11` | `44px` | screen-scale air around the figure |

---

## Radius

| Token | Value | Use |
|---|---|---|
| `--r-1` | `6px` | small inner marks |
| `--r-2` | `11px` | small buttons, chips |
| `--r-3` | `14px` | buttons, icon tiles |
| `--r-4` | `20px` | flat cards, options |
| `--r-5` | `22px` | **cards** |
| `--r-6` | `26px` | the Today figure, the invitation |
| `--r-pill` | `999px` | pills |

Radius grows with the surface: an inner element is always tighter than its
container. Device chrome (`46/51/53px`) is hardware, not UI — left alone.

---

## Elevation

Shadows are tinted with the ink hue, never neutral black.

- `--shadow-sm` — resting cards
- `--shadow-md` — the Today figure, the invitation, and any lifted or selected surface

One light source, from above. Nothing else casts.

---

## Motion

- `--spring` `cubic-bezier(.22,1,.36,1)` — entrances, reveals
- `--spring-2` `cubic-bezier(.16,1.3,.3,1)` — presses, overshoot

Durations: `.28–.34s` press feedback, `.5–.7s` entrance, `.9s+` ambient.
Every interactive surface presses (`scale(.955)`–`.977`). Reveals stagger by
30–60ms; nothing mounts all at once.

Ambient loops (halo drift, orb levitation, mote drift) run 5–9s and must stay
under 25% opacity change — they should be felt, not watched.

---

## Rules

1. **No raw px for type, space, or radius in components.** Use a token. If no
   step fits, the scale is wrong — change the scale, not the component.
2. **No inline `style={{}}` for anything the stylesheet can name.** Inline is for
   values computed at runtime (a progress percentage, a stagger delay).
3. **Kira never states what she does not know.** Copy is built from the data in
   hand. No placeholder place names, no invented appointments. A screen with
   nothing to say says nothing.
4. **Every state is designed**: loading (skeleton in the shape of the content),
   error (what failed, and a way to retry), empty (what to do next).
5. **One accent per view.**
6. Sentence case. No exclamation marks. No "Oops".

## Today

Today is the one screen where the app's card language is stretched rather than
repeated. Three rules hold it together:

1. **One figure, one deep-green surface.** `safe_today_sen` sits on the only
   `--green-1` → `--green-2` card on the screen. Everything else is paper, so the
   contrast between the two does the work a label would otherwise have to do.
   Hierarchy is carried by tone and scale, not by four boxes of equal weight.
2. **One accent per band.** The claim line is a 12px rule: gold on `free` — the
   only band that is actually yours to decide — and a single light ramp on the
   rest, since it sits on the green surface. The 2×2 colour legend it replaced repeated what "Show the working"
   already lists in full, so removing it costs no information.
3. **Kira speaks twice.** Newsreader italic appears in the greeting and in the
   closing invitation, and nowhere between. Everything in the middle is data, so
   it is Manrope with tabular figures. The invitation stays on paper with a gold
   edge and a gold button — the deep green is spent once per screen, on the
   figure, and the gold marks the one thing there is to press.

Section labels use the app-wide `.eyebrow`, the same as Activity, Plan and More —
Today does not get a label style of its own.
