import type { UserResponse } from "@kira/contracts";

import { Reveal } from "../components/Reveal";
import { fmt } from "../lib/money";

const WHEN = new Intl.DateTimeFormat("en-MY", { day: "numeric", month: "long", year: "numeric" });

/** Two letters at most, from whatever the name turns out to be. */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "·";
  const letters = parts.length === 1 ? parts[0]!.slice(0, 2) : parts[0]![0]! + parts.at(-1)![0]!;
  return letters.toUpperCase();
}

function when(date: string | undefined): string {
  if (!date) return "not set";
  const parsed = new Date(`${date}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? date : WHEN.format(parsed);
}

function Row({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="prof-row">
      <span>{label}</span>
      <span style={{ textAlign: "right" }}>
        <b>{value}</b>
        {note && <span className="prof-note">{note}</span>}
      </span>
    </div>
  );
}

/**
 * Who Kira thinks you are, and the dates every forecast is measured from.
 *
 * Read-only on purpose. The cycle, the buffer and the payday are what the
 * projection is built on, so they are worth showing in one place — but each is
 * changed where it means something (income in Settings, the rest through the
 * Butler, which records why it changed) rather than by a field on a profile
 * page that would move every number on Today without saying so.
 */
export function Profile({
  profile,
  loading,
  onBack,
}: {
  profile?: UserResponse;
  loading: boolean;
  onBack: () => void;
}) {
  const name = profile?.display_name ?? "";

  return (
    <>
      <div className="goal-screen-head">
        <button className="goal-back" onClick={onBack} aria-label="Back to More">
          ←
        </button>
        <div>
          <p className="eyebrow">My profile</p>
          <h1>{name || (loading ? "Reading…" : "You")}</h1>
        </div>
      </div>

      <div className="pad">
        <Reveal>
          <section className="card">
            <div className="prof-head">
              <span className="prof-mark" aria-hidden="true">
                {initials(name)}
              </span>
              <div style={{ minWidth: 0 }}>
                <b style={{ display: "block", fontSize: 16, letterSpacing: "-.02em" }}>
                  {name || "Not signed in"}
                </b>
                <span
                  style={{
                    display: "block",
                    fontSize: 12.5,
                    color: "var(--muted)",
                    overflowWrap: "anywhere",
                  }}
                >
                  {profile?.email ?? (loading ? "Reading…" : "—")}
                </span>
              </div>
            </div>
          </section>
        </Reveal>

        <Reveal delay={70} style={{ marginTop: 14 }}>
          <section className="card">
            <p className="eyebrow" style={{ margin: "0 0 4px" }}>
              Your money cycle
            </p>
            <Row label="Currency" value={profile?.currency ?? "—"} />
            <Row
              label="Cycle starts"
              value={when(profile?.cycle_start)}
              note={profile ? `${profile.cycle_days} days long` : undefined}
            />
            <Row label="Next payday" value={when(profile?.next_payday)} />
            <Row
              label="Recurring income"
              value={profile ? `RM${fmt(profile.monthly_income_sen)}` : "—"}
              note="forecast, not cash"
            />
            <Row
              label="Safety buffer"
              value={profile ? `RM${fmt(profile.buffer_sen)}` : "—"}
              note="held back from safe-to-spend"
            />
          </section>
        </Reveal>

        <Reveal delay={140} style={{ marginTop: 14 }}>
          <section className="card">
            <p className="voice" style={{ margin: 0, fontSize: 15, lineHeight: 1.5 }}>
              These dates are what every forecast is measured from. Change your income under
              Settings; for the rest, tell the Butler and it will say what moved.
            </p>
          </section>
        </Reveal>
      </div>
    </>
  );
}
