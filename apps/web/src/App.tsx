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
  useFinancialProfile,
  useUpdateFinancialProfile,
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
import { Login } from "./screens/Login";
import { More } from "./screens/More";
import { Plan, type PlanView } from "./screens/Plan";
import { Today } from "./screens/Today";

export type Tab = "today" | "activity" | "butler" | "plan" | "more";

const TABS: Tab[] = ["today", "activity", "butler", "plan", "more"];

export function App() {
  const [tab, setTab] = useState<Tab>("today");
  const [dir, setDir] = useState(0);
  const [boot, setBoot] = useState(true);
  const [signedIn, setSignedIn] = useState(false);
  const [planView, setPlanView] = useState<PlanView>("daily");
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
  const profile = useFinancialProfile(signedIn);
  const updateProfile = useUpdateFinancialProfile();
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

  const go = (next: Tab, nextPlanView: PlanView = "daily") => {
    if (next === tab) return;
    if (next === "plan") setPlanView(nextPlanView);
    const from = TABS.indexOf(tab);
    const to = TABS.indexOf(next);
    setDir(next === "butler" || tab === "butler" ? 0 : to > from ? 1 : -1);
    setTab(next);
  };

  const proposeDriver = (driver: ForesightDriver) => {
    const amount = `RM${(Math.abs(driver.lever.delta.sen) / 100).toFixed(2)}`;
    const goal = dashboard.data?.goals.find((item) => item.id === driver.lever.target_id);
    const outlook = foresight.data?.outlooks.find(
      (item) => item.goal_id === driver.lever.target_id,
    );
    const text =
      driver.lever.kind === "goal_monthly" && goal
        ? `Please replan my ${goal.name} goal${outlook ? ` with target date ${outlook.target_date}` : ""} using the latest forecast. Calculate safe deterministic options and ask for approval before changing the active plan.`
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
        <span className="device-control device-action" aria-hidden="true" />
        <span className="device-control device-volume-up" aria-hidden="true" />
        <span className="device-control device-volume-down" aria-hidden="true" />
        <span className="device-control device-power" aria-hidden="true" />
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
                      initialView={planView}
                      data={foresight.data}
                      goals={dashboard.data?.goals}
                      isLoading={foresight.isLoading}
                      isError={foresight.isError}
                      onDriver={proposeDriver}
                    />
                  )}
                  {signedIn && tab === "more" && (
                    <More
                      memories={memories.data}
                      isLoading={memories.isLoading}
                      profile={profile.data}
                      profileLoading={profile.isLoading}
                      profileSaving={updateProfile.isPending}
                      onUpdateProfile={(value) => updateProfile.mutateAsync(value)}
                    />
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
