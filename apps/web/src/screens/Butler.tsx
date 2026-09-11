import { type ReactNode, useEffect, useRef, useState } from "react";

import type { ButlerThread, Capture, Category, HindsightResponse } from "@kira/contracts";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

import {
  ask,
  decide,
  resumeAnswer,
  type ApprovalView,
  type AppAction,
  type ButlerWorkRecommendation,
  type ChangeSetLine,
  type ButlerEvent,
  type EvidenceRow,
  type GoalPlanPreview,
} from "../api/butler";
import {
  activityKey,
  briefingTodayKey,
  butlerThreadKey,
  dashboardTodayKey,
  memoriesKey,
} from "../api/hooks";
import { IcArrow, IcCam, IcImg, IcMic } from "../components/Icons";
import { ScanSheet } from "../components/ScanSheet";
import { OnScreen } from "../components/Sheet";
import { TrackRecord } from "../components/TrackRecord";
import { VoiceSheet } from "../components/VoiceSheet";
import { takeButlerHandoff } from "../lib/butlerHandoff";
import { announceGoalRecommendationReady } from "../lib/goalRecommendationEvents";

type Attachment = (Capture & { preview?: string }) | null;

type Turn = {
  id?: string;
  role: "user" | "kira";
  text: string;
  evidence: EvidenceRow[];
  attachment?: Attachment;
  approval?: ApprovalView | null;
  approvals?: ApprovalView[];
  applied?: boolean;
  resumeMessageId?: string;
  workRecommendations?: ButlerWorkRecommendation[];
};

/** What the graph is doing right now, before there is an answer to show. */
type Live = {
  thinking: string;
  tools: string[];
  evidence: EvidenceRow[];
  text: string;
  approval: ApprovalView | null;
};

const EMPTY: Live = { thinking: "", tools: [], evidence: [], text: "", approval: null };

function planPreview(value: unknown): GoalPlanPreview | null {
  if (!value || typeof value !== "object") return null;
  const plan = value as Partial<GoalPlanPreview>;
  if (
    typeof plan.target_amount_sen !== "number" ||
    typeof plan.current_saved_sen !== "number" ||
    typeof plan.required_contribution_per_payday_sen !== "number" ||
    typeof plan.target_date !== "string" ||
    typeof plan.feasible !== "boolean"
  ) {
    return null;
  }
  return plan as GoalPlanPreview;
}

function savedWorkRecommendations(value: unknown): ButlerWorkRecommendation[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is ButlerWorkRecommendation => {
    if (!item || typeof item !== "object") return false;
    const recommendation = item as Partial<ButlerWorkRecommendation>;
    return typeof recommendation.goal_id === "string"
      && Array.isArray(recommendation.recommendations)
      && recommendation.recommendations.every((job) => (
        Boolean(job)
        && typeof job.role_title === "string"
        && typeof job.why_relevant === "string"
        && typeof job.estimated_hourly_rate_min_sen === "number"
        && typeof job.estimated_hourly_rate_max_sen === "number"
        && typeof job.estimated_monthly_income_min_sen === "number"
        && typeof job.estimated_monthly_income_max_sen === "number"
      ));
  });
}

function approvalView(
  id: string,
  summary: string,
  tool: string,
  args: Record<string, unknown> = {},
  before?: unknown,
  after?: unknown,
  basePlanVersion?: number,
  changes?: ChangeSetLine[],
): ApprovalView {
  return {
    id,
    summary,
    tool,
    args,
    before: planPreview(before ?? args.before),
    after: planPreview(after ?? args.after),
    basePlanVersion:
      basePlanVersion ??
      (typeof args.base_plan_version === "number" ? args.base_plan_version : undefined),
    changes: changes ?? (Array.isArray(args.changes) ? args.changes as ChangeSetLine[] : undefined),
  };
}

const PROMPTS = [
    "Can I afford RM60 dinner tonight?",
  "Why did safe-to-spend drop?",
  "How is my wedding goal doing?",
  "What bills are due?",
];

type ButlerProps = {
  thread: ButlerThread | undefined;
  isLoading: boolean;
  categories?: Category[];
  /** Kira's own record, shown above the thread. Absent until it has one. */
  record?: HindsightResponse;
  /** A question raised elsewhere — the entry sheet — for this screen to ask. */
  pending?: { text: string; attachment?: Attachment } | null;
  onPendingAsked?: () => void;
  onThreadStarted?: (id: string) => void;
  onOpenConversation?: (id: string | null) => void;
  onAppAction?: (action: AppAction) => void;
};

export function Butler({
  thread,
  isLoading,
  categories,
  record,
  pending,
  onPendingAsked,
  onThreadStarted,
  onOpenConversation,
  onAppAction,
}: ButlerProps) {
  const queryClient = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [live, setLive] = useState<Live | null>(null);
  const [text, setText] = useState("");
  const [sheet, setSheet] = useState<"scan" | "voice" | null>(null);
  const [attachment, setAttachment] = useState<Attachment>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const loaded = useRef(false);
  const sending = useRef(false);
  const activeThread = useRef<string | undefined>(thread?.id);
  const activeMessage = useRef<string | undefined>(undefined);
  const conversations = useQuery({
    queryKey: ["butler", "conversations"],
    queryFn: () => api.get<Pick<ButlerThread, "id" | "title">[]>("/v1/butler/threads"),
    enabled: Boolean(onOpenConversation),
  });

  // The thread is the record; the local turns are this session's view of it.
  useEffect(() => {
    if (!thread || loaded.current) return;
    activeThread.current = thread.id;
    loaded.current = true;
    const pending = thread.pending_approvals;
    setTurns(
      thread.messages.map((message, index) => ({
        id: message.id,
        role: message.role === "user" ? "user" : "kira",
        text: message.content,
        evidence: message.evidence as EvidenceRow[],
        attachment: (message.attachment as Attachment) ?? null,
        workRecommendations: savedWorkRecommendations(message.work_recommendations),
        resumeMessageId:
          index === thread.messages.length - 1 && message.role === "user"
            ? message.id
            : undefined,
        approvals:
          index === thread.messages.length - 1 && message.role !== "user"
            ? pending.map((approval) =>
                approvalView(
                  approval.id,
                  approval.summary,
                  approval.tool,
                  approval.args as Record<string, unknown>,
                ),
              )
            : [],
      })),
    );
  }, [thread]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, live]);

  useEffect(() => {
    if (!pending || live || isLoading) return;
    onPendingAsked?.();
    send(pending.text, pending.attachment ?? null);
    // Deliberately keyed on the question alone: re-running when `send` changes
    // identity would ask it twice.
  }, [pending, isLoading]);

  const consume = async (events: AsyncGenerator<ButlerEvent>) => {
    let state: Live = { ...EMPTY };
    setLive(state);
    try {
      await read(events, state);
    } catch (error) {
      // The stream never opened, or it died mid-turn. Either way the user is
      // owed a sentence: a silent failure reads as the Butler ignoring them.
      setTurns((previous) => [
        ...previous.map((turn) =>
          turn.id === activeMessage.current
            ? { ...turn, resumeMessageId: activeMessage.current }
            : turn,
        ),
        {
          role: "kira",
          text: `Something broke: ${error instanceof Error ? error.message : "I could not reach the server."}`,
          evidence: [],
        },
      ]);
    }
    setLive(null);
    // A turn may have applied a write, so every number on screen is suspect.
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: dashboardTodayKey }),
      queryClient.invalidateQueries({ queryKey: activityKey }),
      queryClient.invalidateQueries({ queryKey: memoriesKey }),
      queryClient.invalidateQueries({ queryKey: butlerThreadKey }),
      queryClient.invalidateQueries({ queryKey: ["butler", "conversations"] }),
      queryClient.invalidateQueries({ queryKey: briefingTodayKey }),
      queryClient.invalidateQueries({ queryKey: ["goals"] }),
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] }),
      queryClient.invalidateQueries({ queryKey: ["foresight"] }),
      queryClient.invalidateQueries({ queryKey: ["hindsight"] }),
      queryClient.invalidateQueries({ queryKey: ["day-plan"] }),
    ]);
  };

  const read = async (events: AsyncGenerator<ButlerEvent>, initial: Live) => {
    let state = initial;
    for await (const event of events) {
      switch (event.type) {
        case "message":
          activeMessage.current = event.id;
          setTurns((previous) => {
            let index = -1;
            for (let position = previous.length - 1; position >= 0; position -= 1) {
              const candidate = previous[position];
              if (candidate?.role === "user" && !candidate.id) {
                index = position;
                break;
              }
            }
            return previous.map((turn, position) =>
              position === index ? { ...turn, id: event.id } : turn,
            );
          });
          break;
        case "thinking":
          state = { ...state, thinking: event.text };
          break;
        case "tool":
          state = { ...state, tools: [...state.tools, event.label] };
          break;
        case "evidence":
          state = { ...state, evidence: [...state.evidence, ...event.rows] };
          break;
        case "token":
          state = { ...state, text: state.text + event.text };
          break;
        case "app_action":
          onAppAction?.(event);
          break;
        case "goal_recommendation_ready":
          announceGoalRecommendationReady(event.goal_id);
          break;
        case "approval":
          state = {
            ...state,
            approval: approvalView(
              event.approval_id,
              event.summary,
              event.tool,
              event.args,
              event.before,
              event.after,
              event.base_plan_version,
              event.changes,
            ),
          };
          break;
        case "done": {
          setTurns((previous) => previous.map((turn) =>
            turn.id === activeMessage.current ? { ...turn, resumeMessageId: undefined } : turn));
          // The mid-stream approval event carries the arguments a card needs to
          // be editable, but `done` is what says a proposal is still standing.
          // The graph replays its pending approval even on the turn that
          // rejected it, and a rejected change must not reappear as a new card.
          const standing = event.approval
            ? state.approval?.id === event.approval.approval_id
              ? state.approval
              : approvalView(event.approval.approval_id, event.approval.summary, "")
            : null;
          setTurns((previous) => [
            ...previous,
            {
              role: "kira",
              // `answer` is the server's sanitised final text. Never resurrect
              // raw streamed text when it is intentionally empty: that was how
              // a fenced start_goal_planning(...) call reappeared in chat.
              text: event.answer,
              evidence: event.evidence?.length ? event.evidence : state.evidence,
              workRecommendations: event.work_recommendations,
              approval: standing,
              applied: Boolean(event.applied),
            },
          ]);
          break;
        }
        case "error":
          setTurns((previous) => previous.map((turn) =>
            turn.id === activeMessage.current
              ? { ...turn, resumeMessageId: activeMessage.current }
              : turn));
          setTurns((previous) => [
            ...previous,
            { role: "kira", text: `Something broke: ${event.message}`, evidence: [] },
          ]);
          break;
      }
      setLive({ ...state });
    }
  };

  const send = (question: string, attached: Attachment = attachment) => {
    const trimmed = question.trim();
    if (!trimmed || live || sending.current || isLoading) return;
    sending.current = true;
    setSheet(null);
    setAttachment(null);
    setText("");
    setTurns((previous) => [
      ...previous,
      { role: "user", text: trimmed, evidence: [], attachment: attached },
    ]);
    setLive({ ...EMPTY, thinking: "Starting your conversation" });
    activeMessage.current = undefined;
    void (async () => {
      try {
        if (!activeThread.current && onThreadStarted) {
          const created = await api.post<ButlerThread>("/v1/butler/threads", {});
          activeThread.current = created.id;
          // The optimistic user message already exists; do not replace it with
          // the new thread's initially empty server response.
          loaded.current = true;
          onThreadStarted(created.id);
        }
        await consume(ask(trimmed, attached ?? undefined, activeThread.current));
      } catch {
        setTurns((previous) => [...previous, {
          role: "kira", text: "I couldn’t start this conversation. Please try again.", evidence: [],
        }]);
        setText(trimmed);
        setLive(null);
      } finally {
        sending.current = false;
      }
    })();
  };

  const resume = (messageId: string) => {
    const threadId = activeThread.current;
    if (!threadId || live || sending.current) return;
    sending.current = true;
    activeMessage.current = messageId;
    setTurns((previous) => previous.map((turn) =>
      turn.id === messageId ? { ...turn, resumeMessageId: undefined } : turn));
    setLive({ ...EMPTY, thinking: "Resuming your saved request" });
    void (async () => {
      try {
        await consume(resumeAnswer(threadId, messageId));
      } finally {
        sending.current = false;
      }
    })();
  };

  /**
   * A question handed over from another screen, asked as though it were typed
   * here — because it was, a tab ago, and re-wording it would be answering a
   * sentence the user never wrote.
   *
   * Held until the history has arrived: the effect above replaces the turns
   * wholesale on first load, and a question sent before it would drop out of
   * the conversation the moment the thread landed. The slot empties on the
   * take, so the re-runs a strict-mode mount causes find nothing left.
   */
  useEffect(() => {
    if (isLoading) return;
    const handed = takeButlerHandoff();
    if (handed) send(handed);
  }, [isLoading]);

  const respond = (
    id: string,
    action: "accept" | "edit" | "reject",
    args?: Record<string, unknown>,
  ) => {
    if (live) return;
    setTurns((previous) =>
      previous.map((turn) => ({
        ...turn,
        approval: turn.approval?.id === id ? null : turn.approval,
        approvals: turn.approvals?.filter((approval) => approval.id !== id),
      })),
    );
    void consume(decide({ id }, action, args));
  };

  const busy = live !== null;

  return (
    <>
      <div className="topbar" style={{ paddingBottom: 10 }}>
        <div>
          <p className="eyebrow on-ink" style={{ margin: 0 }}>
            Butler
          </p>
          <h1 style={{ color: "#EDF1ED" }}>Ask me anything about your money</h1>
        </div>
      </div>

      {onOpenConversation && (
        <div className="conversation-controls">
          <button className="chip" disabled={busy} onClick={() => onOpenConversation(null)}>
            New conversation
          </button>
          <select aria-label="Conversation history" disabled={busy}
            value={thread?.id ?? activeThread.current ?? ""}
            onChange={(event) => { if (event.target.value) onOpenConversation(event.target.value); }}>
            <option value="">Conversation history</option>
            {(conversations.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>{item.title}</option>
            ))}
          </select>
          {conversations.isError && <span>Couldn’t load previous conversations.</span>}
        </div>
      )}

      <div
        className="pad"
        style={{ paddingBottom: 208, display: "flex", flexDirection: "column", gap: 20 }}
      >
        <TrackRecord data={record} />

        {turns.length === 0 && !isLoading && (
          <p
            className="voice"
            style={{
              fontSize: 20,
              lineHeight: 1.45,
              color: "rgba(233,237,233,.82)",
              margin: "6px 0 0",
            }}
          >
            Ask about your money, record an expense, or plan your next goal.
            We can work through it together. I&rsquo;ll show you the calculation and ask
            you to confirm before changing anything.
          </p>
        )}

        {turns.map((turn, index) =>
          turn.role === "user" ? (
            <div className="bubble-user" key={index}>
              {turn.attachment && <AttachmentTag attachment={turn.attachment} />}
              <span style={{ display: "block" }}>{turn.text}</span>
              {turn.resumeMessageId && (
                <button
                  className="btn btn-accent btn-sm"
                  style={{ marginTop: 12 }}
                  disabled={busy}
                  onClick={() => resume(turn.resumeMessageId!)}
                >
                  Resume Butler&rsquo;s answer
                </button>
              )}
            </div>
          ) : (
            <div className="bubble-kira" key={index}>
              {!turn.workRecommendations?.length && <Answer text={turn.text} />}
              {turn.workRecommendations?.map((recommendation) => (
                <ButlerWorkRecommendations key={recommendation.goal_id} data={recommendation} />
              ))}
              <Evidence rows={turn.evidence} />
              {[...(turn.approvals ?? []), ...(turn.approval ? [turn.approval] : [])].map((proposal) => (
                <Approval
                  key={proposal.id}
                  proposal={proposal}
                  categories={categories}
                  busy={busy}
                  onDecide={(action, args) => respond(proposal.id, action, args)}
                />
              ))}
            </div>
          ),
        )}

        {live && (
          <div className="bubble-kira">
            {live.tools.map((label, index) => (
              <p className="tool-line" key={`${label}-${index}`} style={{ margin: "0 0 7px" }}>
                <span className="dot" />
                {label}
              </p>
            ))}
            {live.text ? (
              <Answer text={live.text} />
            ) : (
              <span className="thinking" aria-label={live.thinking || "Thinking"}>
                <i />
                <i />
                <i />
              </span>
            )}
            <Evidence rows={live.evidence} />
          </div>
        )}

        {/* The scroll target, not a spacer: its scroll-margin keeps the last
            thing said clear of the composer standing over the thread. */}
        <div className="thread-end" ref={endRef} />

        {turns.length === 0 && !isLoading && (
          <div className="chips" style={{ marginTop: 4 }}>
            {PROMPTS.map((prompt) => (
              <button className="chip" key={prompt} onClick={() => send(prompt)}>
                {prompt}
              </button>
            ))}
          </div>
        )}
      </div>

      <OnScreen>
        <div className="composer">
        {attachment && <AttachmentTag attachment={attachment} />}
        <textarea
          rows={2}
          maxLength={2000}
          value={text}
          placeholder="Ask, speak, or scan…"
          aria-label="Ask Kira"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              send(text);
            }
          }}
        />
        <button
          className="cbtn"
          onClick={() => setSheet("scan")}
          disabled={busy}
          aria-label="Scan a receipt"
        >
          <IcCam size={18} w={1.9} />
        </button>
        <button
          className="cbtn"
          onClick={() => setSheet("voice")}
          disabled={busy}
          aria-label="Record a voice note"
        >
          <IcMic size={18} w={1.9} />
        </button>
        <button className="send" onClick={() => send(text)} disabled={busy || !text.trim()} aria-label="Send">
          <IcArrow size={18} w={2.1} />
        </button>
        </div>
      </OnScreen>

      {sheet === "scan" && (
        <ScanSheet
          demo
          onClose={() => setSheet(null)}
          onAsk={(question, read) => send(question, read)}
        />
      )}
      {sheet === "voice" && (
        <VoiceSheet
          demo
          onClose={() => setSheet(null)}
          onAsk={(question, read) => send(question, read)}
        />
      )}
    </>
  );
}

/** The first line is the answer; the rest is the reasoning behind it. */
function Answer({ text }: { text: string }) {
  const [head = "", ...rest] = text.split("\n");
  return (
    <>
      <p className="kira-say"><InlineMarkdown text={head} /></p>
      {rest.length > 0 && <div className="kira-sub butler-answer-body"><InlineMarkdown text={rest.join("\n")} /></div>}
    </>
  );
}

function InlineMarkdown({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  const emphasis = /\*\*([^*\n]+)\*\*/g;
  let offset = 0;
  for (const match of text.matchAll(emphasis)) {
    const [source, content = ""] = match;
    const index = match.index ?? offset;
    if (index > offset) parts.push(text.slice(offset, index));
    parts.push(<strong key={`${index}-${content}`}>{content}</strong>);
    offset = index + source.length;
  }
  if (offset < text.length) parts.push(text.slice(offset));
  return <>{parts}</>;
}

const money = (sen: number) => `RM${(sen / 100).toLocaleString("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function ButlerWorkRecommendations({ data }: { data: ButlerWorkRecommendation }) {
  if (data.recommendations.length === 0) return null;
  return (
    <section className="butler-work-recommendations" aria-label={`Work recommendations for ${data.goal_name ?? "your goal"}`}>
      <p className="eyebrow on-ink">Live work ideas · {data.goal_name ?? "your goal"}</p>
      <div className="butler-work-table" role="table" aria-label={`Work recommendations for ${data.goal_name ?? "your goal"}`}>
        <div className="butler-work-table-head" role="row">
          <span role="columnheader">Role</span><span role="columnheader">Estimated pay</span><span role="columnheader">Apply</span>
        </div>
        {data.recommendations.map((job) => (
          <div className="butler-work-table-row" role="row" key={job.apply_url ?? `${job.role_title}-${job.job_company}`}>
            <span role="cell"><b>{job.role_title}</b><small>{[job.job_company, job.job_location].filter(Boolean).join(" · ")}</small><em>{job.why_relevant}</em></span>
            <span role="cell"><b>{money(job.estimated_hourly_rate_min_sen)}–{money(job.estimated_hourly_rate_max_sen)}/hr</b><small>{money(job.estimated_monthly_income_min_sen)}–{money(job.estimated_monthly_income_max_sen)}/month</small></span>
            <span role="cell">{job.apply_url ? <a className="butler-work-apply" href={job.apply_url} target="_blank" rel="noreferrer">View & apply<span className="sr-only"> for {job.role_title}</span></a> : <small>Link unavailable</small>}</span>
          </div>
        ))}
      </div>
      {data.overall_guidance && <p className="butler-work-guidance">{data.overall_guidance}</p>}
    </section>
  );
}

/**
 * Built from the rows executed tools returned, never written by the model.
 * That is what stops the panel drifting from what actually happened.
 */
function Evidence({ rows }: { rows: EvidenceRow[] }) {
  if (rows.length === 0) return null;
  return (
    <details className="evidence">
      <summary className="eyebrow on-ink" style={{ marginBottom: 2 }}>
        What I used
      </summary>
      {rows.map(([label, value], index) => (
        <div className="ev-row" key={`${label}-${index}`}>
          <span>{label}</span>
          <b>{value}</b>
        </div>
      ))}
    </details>
  );
}

/**
 * The fields of a proposal, in the order a person checks them.
 *
 * Only arguments named here are shown; anything else the tool needs travels
 * back untouched. Adding a write tool means adding a row, not a component.
 */
type FieldSpec = { label: string; kind: "text" | "money" | "date" | "category" };

const EDITABLE: Record<string, FieldSpec | undefined> = {
  merchant: { label: "Merchant", kind: "text" },
  display_name: { label: "Display name", kind: "text" },
  amount_sen: { label: "Total", kind: "money" },
  monthly_income_sen: { label: "Monthly income", kind: "money" },
  saved_sen: { label: "Saved", kind: "money" },
  occurred_on: { label: "Date", kind: "date" },
  due_date: { label: "Due date", kind: "date" },
  target_date: { label: "Target date", kind: "date" },
  next_payday: { label: "Next payday", kind: "date" },
  cycle_start: { label: "Cycle start", kind: "date" },
  cycle_days: { label: "Cycle days", kind: "text" },
  category: { label: "Category", kind: "category" },
  name: { label: "Name", kind: "text" },
  kind: { label: "Account type", kind: "text" },
  status: { label: "Status", kind: "text" },
  note: { label: "Note", kind: "text" },
  monthly_sen: { label: "Monthly", kind: "money" },
  target_sen: { label: "Target", kind: "money" },
};

const ringgit = (sen: unknown) => (typeof sen === "number" ? sen / 100 : 0);
const sen = (ringgit: string) => Math.round(Number(ringgit || 0) * 100);

function Approval({
  proposal,
  categories,
  busy,
  onDecide,
}: {
  proposal: ApprovalView;
  categories?: Category[];
  busy: boolean;
  onDecide: (action: "accept" | "edit" | "reject", args?: Record<string, unknown>) => void;
}) {
  if (proposal.tool === "apply_goal_plan_change" && proposal.after) {
    return <GoalPlanApproval approval={proposal} busy={busy} onDecide={onDecide} />;
  }
  if (proposal.tool === "change_set" && proposal.changes) {
    return <ChangeSetApproval proposal={proposal} categories={categories} busy={busy} onDecide={onDecide} />;
  }
  return (
    <GenericApproval
      proposal={proposal}
      categories={categories}
      busy={busy}
      onDecide={onDecide}
    />
  );
}

function ChangeSetApproval({
  proposal, categories, busy, onDecide,
}: {
  proposal: ApprovalView;
  categories?: Category[];
  busy: boolean;
  onDecide: (action: "accept" | "edit" | "reject", args?: Record<string, unknown>) => void;
}) {
  const [changes, setChanges] = useState(() => proposal.changes ?? []);
  const update = (index: number, patch: Partial<ChangeSetLine>) =>
    setChanges((prior) => prior.map((line, position) =>
      position === index ? { ...line, ...patch } : line));
  const updateArg = (index: number, key: string, value: unknown) =>
    update(index, { args: { ...(changes[index]?.args ?? {}), [key]: value } });
  const changed = JSON.stringify(changes) !== JSON.stringify(proposal.changes);

  return (
    <div className="approval">
      <span className="eyebrow on-ink" style={{ color: "var(--accent-lit)" }}>
        {changes.length} proposed changes · applied together
      </span>
      <div style={{ marginTop: 11, display: "grid", gap: 12 }}>
        {changes.map((line, index) => {
          const fields = Object.keys(line.args).flatMap((key) => {
            const spec = EDITABLE[key];
            return spec ? [{ key, spec }] : [];
          });
          return (
            <div key={line.id} style={{ opacity: line.enabled ? 1 : 0.5 }}>
              <label style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
                <input type="checkbox" checked={line.enabled} disabled={busy}
                  onChange={(event) => update(index, { enabled: event.target.checked })} />
                <span style={{ fontSize: 14, lineHeight: 1.45 }}>{line.summary}</span>
              </label>
              {line.enabled && fields.map(({ key, spec }) => (
                <ProposalField key={key} name={key} spec={spec} value={line.args[key]}
                  categories={categories} disabled={busy}
                  onChange={(value) => updateArg(index, key, value)} />
              ))}
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button className="btn btn-accent btn-sm" style={{ flex: 1 }} disabled={busy || !changes.some((line) => line.enabled)}
          onClick={() => changed ? onDecide("edit", { changes }) : onDecide("accept")}>Approve selected</button>
        <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => onDecide("reject")}>Reject all</button>
      </div>
      <p style={{ margin: "11px 0 0", fontSize: 11.5, color: "rgba(233,237,233,.45)" }}>
        Every enabled line is rechecked, then all are applied atomically.
      </p>
    </div>
  );
}

function GenericApproval({
  proposal,
  categories,
  busy,
  onDecide,
}: {
  proposal: ApprovalView;
  categories?: Category[];
  busy: boolean;
  onDecide: (action: "accept" | "edit" | "reject", args?: Record<string, unknown>) => void;
}) {
  const originalArgs = proposal.args ?? {};
  const [args, setArgs] = useState(originalArgs);
  const fields = Object.keys(originalArgs).flatMap((key) => {
    const spec = EDITABLE[key];
    return spec ? [{ key, spec }] : [];
  });
  const touched = fields.some(({ key }) => args[key] !== originalArgs[key]);
  const set = (key: string, value: unknown) => setArgs((prior) => ({ ...prior, [key]: value }));

  return (
    <div className="approval">
      <span className="eyebrow on-ink" style={{ color: "var(--accent-lit)" }}>
        Proposed change · not applied
      </span>
      {fields.length === 0 ? (
        <p style={{ margin: "10px 0 0", fontSize: 14.5, lineHeight: 1.5 }}>{proposal.summary}</p>
      ) : (
        <div style={{ marginTop: 11 }}>
          <p style={{ margin: "0 0 10px", fontSize: 14.5, lineHeight: 1.5 }}>
            {proposal.summary}
          </p>
          {fields.map(({ key, spec }) => (
            <ProposalField
              key={key}
              name={key}
              spec={spec}
              value={args[key]}
              categories={categories}
              disabled={busy}
              onChange={(value) => set(key, value)}
            />
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button
          className="btn btn-accent btn-sm"
          style={{ flex: 1 }}
          disabled={busy}
          onClick={() => (touched ? onDecide("edit", args) : onDecide("accept"))}
        >
          Approve
        </button>
        <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => onDecide("reject")}>
          Reject
        </button>
      </div>
      <p style={{ margin: "11px 0 0", fontSize: 11.5, color: "rgba(233,237,233,.45)", lineHeight: 1.45 }}>
        {touched
          ? "You changed this. I will record what you corrected, not what I heard."
          : "Nothing changes until you approve. Your buffer and protected bills are off limits either way."}
      </p>
    </div>
  );
}

function GoalPlanApproval({
  approval,
  busy,
  onDecide,
}: {
  approval: ApprovalView;
  busy: boolean;
  onDecide: (action: "accept" | "edit" | "reject", args?: Record<string, unknown>) => void;
}) {
  const [editing, setEditing] = useState(false);
  const after = approval.after!;
  const [target, setTarget] = useState(() => senToRinggit(after.target_amount_sen));
  const [contribution, setContribution] = useState(() =>
    senToRinggit(after.required_contribution_per_payday_sen),
  );
  const [targetDate, setTargetDate] = useState(after.target_date);
  const targetSen = ringgitToSen(target);
  const contributionSen = ringgitToSen(contribution);
  const validEdit = targetSen !== null && contributionSen !== null && Boolean(targetDate);

  return (
    <div className="approval">
      <span className="eyebrow on-ink" style={{ color: "var(--accent-lit)" }}>
        Proposed change · not applied
      </span>
      <p style={{ margin: "10px 0 0", fontSize: 14.5, lineHeight: 1.5 }}>
        {approval.summary}
      </p>
      {!editing ? (
        <div className="goal-plan-compare">
          <PlanPreview label="Before" plan={approval.before ?? null} />
          <PlanPreview label="After" plan={after} />
        </div>
      ) : (
        <div className="goal-plan-edit">
          <label>
            Target amount (RM)
            <input
              aria-label="Target amount (RM)"
              inputMode="decimal"
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            />
          </label>
          <label>
            Per payday (RM)
            <input
              aria-label="Per payday (RM)"
              inputMode="decimal"
              value={contribution}
              onChange={(event) => setContribution(event.target.value)}
            />
          </label>
          <label>
            Target date
            <input
              aria-label="Target date"
              type="date"
              value={targetDate}
              onChange={(event) => setTargetDate(event.target.value)}
            />
          </label>
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        {editing ? (
          <button
            className="btn btn-accent btn-sm"
            style={{ flex: 1 }}
            disabled={busy || !validEdit}
            onClick={() =>
              onDecide("edit", {
                target_amount_sen: targetSen,
                contribution_per_payday_sen: contributionSen,
                target_date: targetDate,
              })
            }
          >
            Recalculate
          </button>
        ) : (
          <button
            className="btn btn-accent btn-sm"
            style={{ flex: 1 }}
            disabled={busy}
            onClick={() => onDecide("accept")}
          >
            Approve
          </button>
        )}
        <button
          className="btn btn-sm btn-ghost"
          disabled={busy}
          onClick={() => setEditing((value) => !value)}
        >
          {editing ? "Cancel edit" : "Edit plan"}
        </button>
        <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => onDecide("reject")}>
          Reject
        </button>
      </div>
      <p style={{ margin: "11px 0 0", fontSize: 11.5, color: "rgba(233,237,233,.45)", lineHeight: 1.45 }}>
        Nothing changes until you approve. Your buffer and protected bills stay off limits.
      </p>
    </div>
  );
}

function PlanPreview({ label, plan }: { label: string; plan: GoalPlanPreview | null }) {
  const affordability = plan ? readableAffordability(plan.affordability_status) : null;
  return (
    <div>
      <span>{label}</span>
      {plan ? (
        <>
          {affordability && (
            <em className={`butler-goal-risk ${affordability.tone}`}>{affordability.label}</em>
          )}
          <b>RM{displayRinggit(plan.required_contribution_per_payday_sen)} / payday</b>
          <small>RM{displayRinggit(plan.target_amount_sen)} by {plan.target_date}</small>
          {plan.remaining_amount_sen !== undefined && (
            <small>RM{displayRinggit(plan.remaining_amount_sen)} remaining</small>
          )}
          {plan.monthly_goal_contributions_sen !== undefined && (
            <small>
              Goal saving RM{displayRinggit(plan.monthly_goal_contributions_sen)}
              {plan.contribution_ratio_bp != null
                ? ` · ${Math.round(plan.contribution_ratio_bp / 100)}% of income`
                : ""}
            </small>
          )}
          {plan.monthly_income_sen != null && (
            <small>
              Income RM{displayRinggit(plan.monthly_income_sen)} · protected RM
              {displayRinggit(plan.monthly_protected_commitments_sen ?? 0)}
            </small>
          )}
        </>
      ) : (
        <b>No active plan</b>
      )}
    </div>
  );
}

function readableAffordability(value: string | undefined): { label: string; tone: string } | null {
  if (!value) return null;
  const labels: Record<string, string> = {
    comfortable: "Comfortable",
    stretching: "Stretching",
    high_risk: "High risk",
    unsustainable: "Unsustainable",
    impossible: "Not possible",
    income_unavailable: "Income needed",
  };
  const tones: Record<string, string> = {
    comfortable: "comfortable",
    stretching: "stretching",
    high_risk: "high-risk",
    unsustainable: "unsustainable",
    impossible: "unsustainable",
    income_unavailable: "income-unavailable",
  };
  return {
    label: labels[value] ?? value.replaceAll("_", " "),
    tone: tones[value] ?? "income-unavailable",
  };
}

function senToRinggit(sen: number): string {
  const whole = Math.trunc(sen / 100);
  const cents = Math.abs(sen % 100).toString().padStart(2, "0");
  return `${whole}.${cents}`;
}

function displayRinggit(sen: number): string {
  const [whole, cents] = senToRinggit(sen).split(".");
  return `${Number(whole).toLocaleString("en-MY")}.${cents}`;
}

function ringgitToSen(value: string): number | null {
  const match = value.trim().match(/^(\d+)(?:\.(\d{1,2}))?$/);
  if (!match) return null;
  const whole = Number(match[1]);
  const cents = Number((match[2] ?? "").padEnd(2, "0"));
  if (!Number.isSafeInteger(whole) || whole <= 0) return null;
  const sen = whole * 100 + cents;
  return Number.isSafeInteger(sen) ? sen : null;
}

function ProposalField({
  name,
  spec,
  value,
  categories,
  disabled,
  onChange,
}: {
  name: string;
  spec: FieldSpec;
  value: unknown;
  categories?: Category[];
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const id = `approval-${name}`;
  // The current slug is always offered, even where the vocabulary has not
  // loaded: a field that cannot show its own value is worse than no field.
  const options = categories?.length
    ? categories
    : [{ slug: String(value), label: String(value) }];

  return (
    <label className="field field-edit" htmlFor={id}>
      <span className="field-l">{spec.label}</span>
      {spec.kind === "category" ? (
        <select
          id={id}
          className="field-in"
          value={String(value ?? "")}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        >
          {options.map((option) => (
            <option key={option.slug} value={option.slug}>
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          className="field-in"
          type={spec.kind === "money" ? "number" : spec.kind === "date" ? "date" : "text"}
          step={spec.kind === "money" ? "0.01" : undefined}
          value={spec.kind === "money" ? ringgit(value) : String(value ?? "")}
          disabled={disabled}
          onChange={(event) =>
            onChange(spec.kind === "money" ? sen(event.target.value) : event.target.value)
          }
        />
      )}
    </label>
  );
}

function AttachmentTag({ attachment }: { attachment: Attachment }) {
  if (!attachment) return null;
  if (attachment.preview) {
    return <img className="att-img" src={attachment.preview} alt="The receipt you sent" />;
  }
  return (
    <span className="att">
      {attachment.kind === "voice" ? <IcMic size={14} /> : <IcImg size={14} />}
      {attachment.kind === "voice" ? "Voice note" : "Receipt"} · {attachment.merchant ?? "transcript"}
    </span>
  );
}
