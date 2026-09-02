import { useEffect, useState } from "react";

import type { Activity as ActivityData, Transaction } from "@kira/contracts";

import type { Tab } from "../App";
import { CategoryChips } from "../components/CategoryChips";
import { DraftCard } from "../components/DraftCard";
import { IcArrow } from "../components/Icons";
import { Reveal } from "../components/Reveal";
import { Sheet } from "../components/Sheet";
import { TxnRow } from "../components/TxnRow";
import { TxnSheet } from "../components/TxnSheet";
import { fmt } from "../lib/money";

const DAY = new Intl.DateTimeFormat("en-MY", { weekday: "long", day: "numeric", month: "long" });

type ActivityProps = {
  data: ActivityData | undefined;
  isLoading: boolean;
  isError: boolean;
  onConfirm: (id: string) => void;
  onDiscard: (id: string) => void;
  onUnconfirm: (id: string) => void;
  /** Resolves when the correction is saved, and rejects when it is not. */
  onCorrect: (id: string, amountSen: number) => void | Promise<unknown>;
  settlingId: string | null;
  correctingId: string | null;
  category: string | null;
  onCategory: (slug: string | null) => void;
  go: (tab: Tab) => void;
};

export function Activity({
  data,
  isLoading,
  isError,
  onConfirm,
  onDiscard,
  onUnconfirm,
  onCorrect,
  settlingId,
  correctingId,
  category,
  onCategory,
  go,
}: ActivityProps) {
  const [opened, setOpened] = useState<Transaction | null>(null);
  const onLedger = data?.days.some((day) =>
    day.transactions.some((txn) => txn.id === opened?.id),
  );

  // The sheet describes a transaction as counted. Once it no longer is —
  // moved back from this very sheet, or elsewhere — the sheet is a lie.
  useEffect(() => {
    if (opened && data && !onLedger) setOpened(null);
  }, [data, onLedger, opened]);

  // A half-drawn ledger reads as missing money, so neither state guesses.
  if (isLoading || !data) {
    return (
      <div className="pad" style={{ paddingTop: 90 }}>
        <p className="voice" style={{ fontSize: 17 }}>
          {isError ? "I couldn't reach your ledger just now." : "Fetching your ledger…"}
        </p>
        {isError && (
          <p style={{ fontSize: 13, color: "var(--muted)" }}>
            Nothing has changed. Nothing was confirmed while I was away.
          </p>
        )}
      </div>
    );
  }

  // The waiting drafts have their own empty state; the ledger needs its own too,
  // or a first-ever draft would leave the ledger showing a bare RM0.00 heading.
  const empty = data.days.length === 0;
  const active = data.categories.find((summary) => summary.slug === category) ?? null;
  // The All chip shows the whole cycle, which is not what a filtered total says.
  const wholeCycleSen = data.categories.reduce(
    (running, summary) => running + summary.spent_this_cycle_sen,
    0,
  );

  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0 }}>Activity</p>
          <h1>Where your money went</h1>
        </div>
      </div>

      <div className="pad">
        <Reveal>
          <button
            className="card-flat tapp"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              padding: "13px 15px",
              width: "100%",
              textAlign: "left",
            }}
            onClick={() => go("butler")}
          >
            <span style={{ fontSize: 13, color: "var(--muted)" }}>
              Spent something? <b style={{ color: "var(--ink)" }}>Tell Butler</b> and it lands
              here as a draft.
            </span>
            <IcArrow size={17} />
          </button>
        </Reveal>

        {data.drafts.length > 0 ? (
          <div style={{ marginTop: 22 }}>
            <p className="eyebrow" style={{ margin: "0 0 11px" }}>
              Waiting for you · {data.drafts.length} · RM{fmt(data.draft_total_sen)}
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {data.drafts.map((draft, index) => (
                <Reveal key={draft.id} delay={index * 90}>
                  <DraftCard
                    draft={draft}
                    onConfirm={onConfirm}
                    onDiscard={onDiscard}
                    onCorrect={onCorrect}
                    settling={settlingId === draft.id}
                    correcting={correctingId === draft.id}
                  />
                </Reveal>
              ))}
            </div>
          </div>
        ) : (
          <Reveal style={{ marginTop: 22 }}>
            <div className="card-flat" style={{ textAlign: "center", padding: "30px 20px" }}>
              <p className="voice" style={{ margin: 0, fontSize: 16 }}>Nothing waiting.</p>
              <p style={{ margin: "7px 0 0", fontSize: 13, color: "var(--muted)" }}>
                Snap a receipt or say what you spent, and it&apos;ll land here for review.
              </p>
            </div>
          </Reveal>
        )}

        {data.categories.length > 0 && (
          <Reveal delay={40} style={{ marginTop: 22 }}>
            <CategoryChips
              categories={data.categories}
              active={category}
              onPick={onCategory}
              totalSen={wholeCycleSen}
            />
          </Reveal>
        )}

        {empty ? (
          <Reveal delay={60} style={{ marginTop: 16 }}>
            <section className="card" style={{ textAlign: "center", padding: "30px 20px" }}>
              <p className="voice" style={{ margin: 0, fontSize: 16 }}>
                {active ? `Nothing under ${active.label} this cycle.` : "Nothing on your ledger yet."}
              </p>
              <p style={{ margin: "7px 0 0", fontSize: 13, color: "var(--muted)" }}>
                {active
                  ? "Try another category, or clear the filter."
                  : "Confirmed spending shows up here, newest day first."}
              </p>
            </section>
          </Reveal>
        ) : (
          <>
            <Reveal delay={60} style={{ marginTop: 18 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                }}
              >
                <p className="eyebrow" style={{ margin: 0 }}>
                  {active ? `${active.label} this cycle` : "Spent this cycle"}
                </p>
                <span className="money" style={{ fontSize: 17 }}>
                  RM{fmt(data.spent_this_cycle_sen)}
                </span>
              </div>
            </Reveal>

            {data.days.map((day, index) => (
              <Reveal key={day.date} delay={index * 50} style={{ marginTop: 12 }}>
                <section className="card">
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "baseline",
                      marginBottom: 4,
                    }}
                  >
                    <p className="eyebrow" style={{ margin: 0 }}>
                      {DAY.format(new Date(`${day.date}T00:00:00`))}
                    </p>
                    <span style={{ fontSize: 12.5, fontWeight: 700, color: "var(--muted)" }}>
                      {day.total_sen < 0 ? "+" : ""}RM{fmt(Math.abs(day.total_sen))}
                    </span>
                  </div>
                  {day.transactions.map((txn) => (
                    <TxnRow key={txn.id} txn={txn} onOpen={setOpened} />
                  ))}
                </section>
              </Reveal>
            ))}
          </>
        )}
      </div>

      {opened && (
        <Sheet label={opened.merchant} onClose={() => setOpened(null)}>
          <TxnSheet
            txn={opened}
            onUnconfirm={onUnconfirm}
            onClose={() => setOpened(null)}
            busy={settlingId === opened.id}
          />
        </Sheet>
      )}
    </>
  );
}
