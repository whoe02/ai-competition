import { useEffect, useRef, useState, type CSSProperties } from "react";

import type { ForesightDriver } from "@kira/contracts";

import {
  useActivity,
  useButlerThread,
  useBriefingToday,
  useConfirmDraft,
  useCorrectDraft,
  useDashboardToday,
  useDiscardDraft,
  useCategories,
  useForesight,
  useHindsight,
  useMemories,
  useUnconfirm,
} from "./api/hooks";
import { EntrySheet, type EntryAttachment } from "./components/EntrySheet";
import { IcActivity, IcMore, IcPlan, IcPlus, IcSpark, IcToday } from "./components/Icons";
import { Motes } from "./components/Motes";
import { NavItem } from "./components/NavItem";
import { ScrollContext } from "./components/Reveal";
import { SheetHostContext } from "./components/Sheet";
import { Activity } from "./screens/Activity";
import { Butler } from "./screens/Butler";
import { DayPlan } from "./screens/DayPlan";
import { Login } from "./screens/Login";
import { More } from "./screens/More";
import { Plan } from "./screens/Plan";
import { Today } from "./screens/Today";

export type Tab = "today" | "activity" | "butler" | "plan" | "more";

const TABS: Tab[] = ["today", "activity", "butler", "plan", "more"];

export function App() {
  const [tab, setTab] = useState<Tab>("today");
  const [dir, setDir] = useState(0);
  const [boot, setBoot] = useState(true);
  const [signedIn, setSignedIn] = useState(false);
  const [entry, setEntry] = useState(false);
  // A sentence raised from Today or Activity, handed to the Butler to ask.
  const [pending, setPending] = useState<{ text: string; attachment?: EntryAttachment } | null>(
    null,
  );
  const viewRef = useRef<HTMLDivElement>(null);
  const screenRef = useRef<HTMLDivElement>(null);
  const dashboard = useDashboardToday(signedIn);
  const briefing = useBriefingToday(signedIn);
  const foresight = useForesight(signedIn && tab === "plan");
  const hindsight = useHindsight(signedIn && tab === "butler");
  const [category, setCategory] = useState<string | null>(null);
  const activity = useActivity(signedIn && tab === "activity", category);
  // The thread is fetched once the user signs in, not on first open: the
  // Butler tab should already have its history when it appears.
  const butler = useButlerThread(signedIn);
  const memories = useMemories(signedIn && tab === "more");
  const categories = useCategories(signedIn);
  const confirm = useConfirmDraft();
  const discard = useDiscardDraft();
  const unconfirm = useUnconfirm();
  const correct = useCorrectDraft();
  const settlingId =
    [confirm, discard, unconfirm].find((mutation) => mutation.isPending)?.variables ?? null;
  const correctingId = correct.isPending ? (correct.variables?.id ?? null) : null;

  useEffect(() => {
    const timer = setTimeout(() => setBoot(false), 2500);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    viewRef.current?.scrollTo?.({ top: 0, behavior: "auto" });
  }, [tab]);

  // Scroll-linked parallax: write a CSS variable, never re-render.
  useEffect(() => {
    const view = viewRef.current;
    const screen = screenRef.current;
    if (!view || !screen) return;
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        screen.style.setProperty("--sy", String(view.scrollTop));
        frame = 0;
      });
    };
    view.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      view.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
    };
  }, [tab]);

  const go = (next: Tab) => {
    if (next === tab) return;
    const from = TABS.indexOf(tab);
    const to = TABS.indexOf(next);
    setDir(next === "butler" || tab === "butler" ? 0 : to > from ? 1 : -1);
    setTab(next);
  };

  const proposeDriver = (driver: ForesightDriver) => {
    const amount = `RM${(Math.abs(driver.lever.delta.sen) / 100).toFixed(2)}`;
    const goal = dashboard.data?.goals.find((item) => item.id === driver.lever.target_id);
    const revisedMonthly = goal ? goal.monthly_sen + driver.lever.delta.sen : null;
    const text =
      driver.lever.kind === "goal_monthly" && goal && revisedMonthly !== null
        ? `Please propose setting my monthly savings for ${goal.name} to RM${(revisedMonthly / 100).toFixed(2)}. Show me the approval card; do not apply anything yet.`
        : driver.lever.kind === "commitment_amount"
          ? `Please help me propose reducing this commitment by ${amount}. Show me the approval card; do not apply anything yet.`
          : `Help me make a plan to spend ${amount} less each day. Do not change anything yet.`;
    setPending({ text });
    go("butler");
  };

  const dark = tab === "butler";

  return (
    <div className="kira-root">
      <div className="stage-head">
        <div className="lockup">
          <b>Kira</b>
          <span>AI money butler</span>
        </div>
      </div>

      <div className="device">
        <div
          className={`screen ${dark ? "dim" : ""}`}
          ref={screenRef}
          style={{ "--dir": dir } as CSSProperties}
        >
          <Motes />

          {boot && (
            <div className="boot">
              <div style={{ textAlign: "center" }}>
                <div className="boot-mark">
                  {"KIRA".split("").map((character, index) => (
                    <span key={index} style={{ animationDelay: `${0.07 * index}s` }}>{character}</span>
                  ))}
                </div>
                <div className="boot-rule" />
                <p className="boot-sub">AI money butler</p>
              </div>
            </div>
          )}

          <div className="statusbar">
            <span>12:47</span>
            <span style={{ display: "flex", gap: 7, alignItems: "center" }}>
              <span className="sb-dots"><i /><i /><i /><i /></span>
              <span className="sb-batt" />
            </span>
          </div>

          <SheetHostContext.Provider value={screenRef}>
            <ScrollContext.Provider value={viewRef}>
              <div className="viewport" ref={viewRef}>
                <div className="page" key={signedIn ? tab : "login"}>
                  {!signedIn && <Login onSignedIn={() => setSignedIn(true)} />}
                  {signedIn && tab === "today" && (
                    <Today
                      data={dashboard.data}
                      isLoading={dashboard.isLoading}
                      isError={dashboard.isError}
                      briefing={briefing.data}
                      go={go}
                    />
                  )}
                  {signedIn && tab === "activity" && (
                    <Activity
                      data={activity.data}
                      isLoading={activity.isLoading}
                      isError={activity.isError}
                      onConfirm={confirm.mutate}
                      onDiscard={discard.mutate}
                      onUnconfirm={unconfirm.mutate}
                      // mutateAsync, not mutate: the card holds the entry open
                      // until the server answers, so a correction that failed
                      // cannot close as though it had been saved.
                      onCorrect={(id, amountSen) =>
                        correct.mutateAsync({ id, amount_sen: amountSen })}
                      settlingId={settlingId}
                      correctingId={correctingId}
                      category={category}
                      onCategory={setCategory}
                      go={go}
                    />
                  )}
                  {signedIn && tab === "butler" && (
                    <Butler
                      thread={butler.data}
                      isLoading={butler.isLoading}
                      record={hindsight.data}
                      categories={categories.data}
                      pending={pending}
                      onPendingAsked={() => setPending(null)}
                    />
                  )}
                  {signedIn && tab === "plan" && (
                    <Plan
                      data={foresight.data}
                      goals={dashboard.data?.goals}
                      isLoading={foresight.isLoading}
                      isError={foresight.isError}
                      onDriver={proposeDriver}
                      dayPlan={<DayPlan />}
                    />
                  )}
                  {signedIn && tab === "more" && (
                    <More memories={memories.data} isLoading={memories.isLoading} />
                  )}
                </div>
              </div>
            </ScrollContext.Provider>
          </SheetHostContext.Provider>

          {signedIn && (tab === "today" || tab === "activity") && (
            <button className="fab" onClick={() => setEntry(true)} aria-label="Add spending">
              <IcPlus size={21} />
            </button>
          )}

          {entry && (
            <EntrySheet
              onClose={() => setEntry(false)}
              onAsk={(text, attachment) => {
                setEntry(false);
                setPending({ text, attachment });
                go("butler");
              }}
            />
          )}

          {signedIn && (
            <nav className="nav">
              <NavItem id="today" tab={tab} go={go} Icon={IcToday} label="Today" />
              <NavItem id="activity" tab={tab} go={go} Icon={IcActivity} label="Activity" />
              <button
                className={`nav-butler ${tab === "butler" ? "active" : ""}`}
                onClick={() => go("butler")}
              >
                <span className="butler-orb"><IcSpark size={25} /></span>
                <span>Butler</span>
              </button>
              <NavItem id="plan" tab={tab} go={go} Icon={IcPlan} label="Plan" />
              <NavItem id="more" tab={tab} go={go} Icon={IcMore} label="More" />
            </nav>
          )}
        </div>
      </div>
    </div>
  );
}
