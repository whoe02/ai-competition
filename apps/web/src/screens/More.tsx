import { useId, useState } from "react";

import type { FinancialProfileUpdate, Memory, UserResponse } from "@kira/contracts";

import { useCorrectMemory, useForgetMemory } from "../api/hooks";
import { IcChev, IcGear, IcTrash, IcUser } from "../components/Icons";
import { Reveal } from "../components/Reveal";
import { parseNonNegativeSen, toRinggitInput } from "../lib/money";
import { Profile } from "./Profile";

const KIND_BLURB: Record<string, string> = {
  preference: "how you want to be told things",
  constraint: "a rule you set",
  context: "something true about your life",
  person: "someone in your money",
  pattern: "something I noticed",
};

const WHEN = new Intl.DateTimeFormat("en-MY", { day: "numeric", month: "short" });

type MoreProps = {
  memories: Memory[] | undefined;
  isLoading: boolean;
  profile?: UserResponse;
  profileLoading?: boolean;
  profileSaving?: boolean;
  onUpdateProfile?: (value: FinancialProfileUpdate) => Promise<unknown>;
};

/** Which of More's own screens is showing. The tab is one entry in the bar. */
type Page = "menu" | "profile";

/**
 * The tab that holds everything that is not a number on a screen.
 *
 * A menu rather than a page: profile, settings and memory are three different
 * questions, and stacking all of them under one heading meant the answer to
 * each was somewhere in the same scroll. The settings live behind a disclosure
 * because they are the ones you open to change something, not to read it.
 */
export function More({
  memories,
  isLoading,
  profile,
  profileLoading = false,
  profileSaving = false,
  onUpdateProfile,
}: MoreProps) {
  const [page, setPage] = useState<Page>("menu");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const panelId = useId();

  if (page === "profile") {
    return (
      <Profile
        profile={profile}
        loading={profileLoading}
        onBack={() => setPage("menu")}
      />
    );
  }

  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0 }}>
            More
          </p>
          <h1>You, and how Kira works</h1>
        </div>
      </div>

      <div className="pad">
        <Reveal>
          <button className="card-flat tapp more-row" onClick={() => setPage("profile")}>
            <span className="more-ic">
              <IcUser size={18} />
            </span>
            <span className="more-body">
              <b>My profile</b>
              <span>Your name, your cycle and your payday</span>
            </span>
            <span className="more-chev">
              <IcChev size={17} />
            </span>
          </button>
        </Reveal>

        <Reveal delay={70} style={{ marginTop: 12 }}>
          <div className="card-flat more-card">
            <button
              className="more-row"
              aria-expanded={settingsOpen}
              aria-controls={panelId}
              onClick={() => setSettingsOpen((open) => !open)}
            >
              <span className="more-ic">
                <IcGear size={18} />
              </span>
              <span className="more-body">
                <b>Settings</b>
                <span>Your income, and what Kira remembers</span>
              </span>
              <span className={`more-chev ${settingsOpen ? "down" : ""}`}>
                <IcChev size={17} />
              </span>
            </button>

            {settingsOpen && (
              <div className="more-panel" id={panelId}>
                {onUpdateProfile && (
                  <IncomeProfileCard
                    profile={profile}
                    loading={profileLoading}
                    saving={profileSaving}
                    onSave={onUpdateProfile}
                  />
                )}

                <section className="more-group">
                  <p className="eyebrow" style={{ margin: 0 }}>
                    What Kira remembers
                  </p>
                  <p className="voice" style={{ margin: "8px 0 2px", fontSize: 14.5, lineHeight: 1.5 }}>
                    These shape every answer. If one of them is wrong, correct it — I would rather
                    be told than keep repeating it.
                  </p>
                  {isLoading && <p className="mem-meta">Reading…</p>}
                  {!isLoading && (memories?.length ?? 0) === 0 && (
                    <p className="mem-meta">
                      Nothing yet. Tell me something in the Butler and it will land here.
                    </p>
                  )}
                  {memories?.map((memory) => (
                    <MemoryRow key={memory.id} memory={memory} />
                  ))}
                </section>

                <section className="more-group">
                  <p className="eyebrow" style={{ margin: 0 }}>
                    Still to come
                  </p>
                  <p style={{ margin: "9px 0 0", fontSize: 13.5, color: "var(--muted)", lineHeight: 1.5 }}>
                    Bills, accounts, and the full audit trail.
                  </p>
                </section>
              </div>
            )}
          </div>
        </Reveal>
      </div>
    </>
  );
}

function IncomeProfileCard({
  profile,
  loading,
  saving,
  onSave,
}: {
  profile?: UserResponse;
  loading: boolean;
  saving: boolean;
  onSave: (value: FinancialProfileUpdate) => Promise<unknown>;
}) {
  const [income, setIncome] = useState("");
  const [payday, setPayday] = useState("");
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState("");
  const currentIncome = profile?.monthly_income_sen ?? 0;

  const edit = () => {
    setIncome(toRinggitInput(currentIncome));
    setPayday(profile?.next_payday ?? "");
    setNotice("");
    setEditing(true);
  };
  const save = async () => {
    const monthlyIncomeSen = parseNonNegativeSen(income);
    if (monthlyIncomeSen === null) return;
    try {
      await onSave({
        monthly_income_sen: monthlyIncomeSen,
        ...(payday ? { next_payday: payday } : {}),
      });
      setEditing(false);
      setNotice("Recurring income updated. This changes forecasts, not your cash balance.");
    } catch {
      setNotice("That did not save. Your recurring income is unchanged.");
    }
  };

  return (
    <section className="more-group">
      <p className="eyebrow" style={{ margin: 0 }}>Income profile</p>
      <h2 style={{ fontSize: 18, margin: "7px 0" }}>Salary and recurring income</h2>
      {loading ? <p className="mem-meta">Reading…</p> : editing ? (
        <div style={{ display: "grid", gap: 10 }}>
          <label style={{ fontSize: 13 }}>Monthly income (RM)
            <input className="mem-input" aria-label="Monthly recurring income" inputMode="decimal" value={income} onChange={(event) => setIncome(event.target.value)} />
          </label>
          <label style={{ fontSize: 13 }}>Next payday
            <input className="mem-input" aria-label="Next payday" type="date" value={payday} onChange={(event) => setPayday(event.target.value)} />
          </label>
          <div className="mem-acts">
            <button className="btn btn-primary btn-sm" disabled={saving || parseNonNegativeSen(income) === null} onClick={() => void save()}>{saving ? "Saving…" : "Save"}</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <>
          <p className="money" style={{ fontSize: 21, margin: "10px 0 2px" }}>RM{toRinggitInput(currentIncome)}</p>
          <p className="mem-meta">Forecast only · next payday {profile?.next_payday ?? "not set"}</p>
          <button className="btn btn-line btn-sm" onClick={edit}>Update income</button>
        </>
      )}
      {notice && <p className="mem-meta" role="status">{notice}</p>}
    </section>
  );
}

function MemoryRow({ memory }: { memory: Memory }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(memory.fact);
  const correct = useCorrectMemory();
  const forget = useForgetMemory();

  return (
    <div className="mem">
      <div className="mem-head">
        <span className="mem-kind">{memory.kind}</span>
        <span className="mem-meta" style={{ margin: 0 }}>
          {memory.confidence}% sure
        </span>
      </div>

      {editing ? (
        <>
          <input
            className="mem-input"
            style={{ marginTop: 7 }}
            value={draft}
            aria-label="Correct this memory"
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="mem-acts">
            <button
              className="btn btn-brass btn-sm"
              disabled={correct.isPending || !draft.trim()}
              onClick={() =>
                correct.mutate(
                  { id: memory.id, fact: draft.trim() },
                  { onSuccess: () => setEditing(false) },
                )
              }
            >
              Save
            </button>
            <button
              className="btn btn-sm btn-ghost"
              onClick={() => {
                setDraft(memory.fact);
                setEditing(false);
              }}
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="mem-fact">{memory.fact}</p>
          <p className="mem-meta">
            {KIND_BLURB[memory.kind] ?? memory.kind} · learned {WHEN.format(new Date(memory.created_at))}
          </p>
          <div className="mem-acts">
            <button className="btn btn-sm btn-ghost" onClick={() => setEditing(true)}>
              Correct
            </button>
            <button
              className="btn btn-sm btn-ghost"
              disabled={forget.isPending}
              aria-label={`Forget: ${memory.fact}`}
              onClick={() => forget.mutate(memory.id)}
            >
              <IcTrash size={14} /> Forget
            </button>
          </div>
        </>
      )}
    </div>
  );
}
