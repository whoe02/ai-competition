import { useEffect, useRef, useState } from "react";

import type { ButlerThread, Capture, Category, HindsightResponse } from "@kira/contracts";
import { useQueryClient } from "@tanstack/react-query";

import {
  ask,
  decide,
  type ApprovalView,
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
import { TrackRecord } from "../components/TrackRecord";
import { VoiceSheet } from "../components/VoiceSheet";
import { takeButlerHandoff } from "../lib/butlerHandoff";

type Attachment = (Capture & { preview?: string }) | null;

type Turn = {
  role: "user" | "kira";
  text: string;
  evidence: EvidenceRow[];
  attachment?: Attachment;
  approval?: ApprovalView | null;
  approvals?: ApprovalView[];
  applied?: boolean;
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

function approvalView(
  id: string,
  summary: string,
  tool: string,
  args: Record<string, unknown> = {},
  before?: unknown,
  after?: unknown,
  basePlanVersion?: number,
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
};

export function Butler({
  thread,
  isLoading,
  categories,
  record,
  pending,
  onPendingAsked,
}: ButlerProps) {
  const queryClient = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [live, setLive] = useState<Live | null>(null);
  const [text, setText] = useState("");
  const [sheet, setSheet] = useState<"scan" | "voice" | null>(null);
  const [attachment, setAttachment] = useState<Attachment>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const loaded = useRef(false);

  // The thread is the record; the local turns are this session's view of it.
  useEffect(() => {
    if (!thread || loaded.current) return;
    loaded.current = true;
    const pending = thread.pending_approvals;
    setTurns(
      thread.messages.map((message, index) => ({
        role: message.role === "user" ? "user" : "kira",
        text: message.content,
        evidence: message.evidence as EvidenceRow[],
        attachment: (message.attachment as Attachment) ?? null,
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
    if (!pending || live) return;
    onPendingAsked?.();
    send(pending.text, pending.attachment ?? null);
    // Deliberately keyed on the question alone: re-running when `send` changes
    // identity would ask it twice.
  }, [pending]);

  const consume = async (events: AsyncGenerator<ButlerEvent>) => {
    let state: Live = { ...EMPTY };
    setLive(state);
    try {
      await read(events, state);
    } catch (error) {
      // The stream never opened, or it died mid-turn. Either way the user is
      // owed a sentence: a silent failure reads as the Butler ignoring them.
      setTurns((previous) => [
        ...previous,
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
      queryClient.invalidateQueries({ queryKey: briefingTodayKey }),
    ]);
  };

  const read = async (events: AsyncGenerator<ButlerEvent>, initial: Live) => {
    let state = initial;
    for await (const event of events) {
      switch (event.type) {
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
            ),
          };
          break;
        case "done":
          setTurns((previous) => [
            ...previous,
            {
              role: "kira",
              text: event.answer || state.text,
              evidence: event.evidence?.length ? event.evidence : state.evidence,
              approval: state.approval,
              applied: Boolean(event.applied),
            },
          ]);
          break;
        case "error":
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
    if (!trimmed || live) return;
    setSheet(null);
    setAttachment(null);
    setText("");
    setTurns((previous) => [
      ...previous,
      { role: "user", text: trimmed, evidence: [], attachment: attached },
    ]);
    void consume(ask(trimmed, attached ?? undefined));
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

      <div
        className="pad"
        style={{ paddingBottom: 176, display: "flex", flexDirection: "column", gap: 20 }}
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
            I answer from your confirmed transactions only, and I show you the numbers I used.
            I can&rsquo;t move money — that isn&rsquo;t mine to do.
          </p>
        )}

        {turns.map((turn, index) =>
          turn.role === "user" ? (
            <div className="bubble-user" key={index}>
              {turn.attachment && <AttachmentTag attachment={turn.attachment} />}
              <span style={{ display: "block" }}>{turn.text}</span>
            </div>
          ) : (
            <div className="bubble-kira" key={index}>
              <Answer text={turn.text} />
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

        <div ref={endRef} />

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

      <div className="composer">
        {attachment && <AttachmentTag attachment={attachment} />}
        <input
          value={text}
          placeholder="Ask, speak, or show me a receipt…"
          aria-label="Ask Kira"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") send(text);
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
        <button className="send" onClick={() => send(text)} disabled={busy} aria-label="Send">
          <IcArrow size={18} w={2.1} />
        </button>
      </div>

      {sheet === "scan" && (
        <ScanSheet
          onClose={() => setSheet(null)}
          onAsk={(question, read) => send(question, read)}
        />
      )}
      {sheet === "voice" && (
        <VoiceSheet
          onClose={() => setSheet(null)}
          onAsk={(question, read) => send(question, read)}
        />
      )}
    </>
  );
}

/** The first line is the answer; the rest is the reasoning behind it. */
function Answer({ text }: { text: string }) {
  const [head, ...rest] = text.split("\n");
  return (
    <>
      <p className="kira-say">{head}</p>
      {rest.length > 0 && <p className="kira-sub">{rest.join(" ")}</p>}
    </>
  );
}

/**
 * Built from the rows executed tools returned, never written by the model.
 * That is what stops the panel drifting from what actually happened.
 */
function Evidence({ rows }: { rows: EvidenceRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="evidence">
      <span className="eyebrow on-ink" style={{ marginBottom: 2 }}>
        What I used
      </span>
      {rows.map(([label, value], index) => (
        <div className="ev-row" key={`${label}-${index}`}>
          <span>{label}</span>
          <b>{value}</b>
        </div>
      ))}
    </div>
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
  amount_sen: { label: "Total", kind: "money" },
  occurred_on: { label: "Date", kind: "date" },
  category: { label: "Category", kind: "category" },
  name: { label: "Name", kind: "text" },
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
  return (
    <GenericApproval
      proposal={proposal}
      categories={categories}
      busy={busy}
      onDecide={onDecide}
    />
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
      <span className="eyebrow on-ink" style={{ color: "var(--brass-lit)" }}>
        Proposed change · not applied
      </span>
      {fields.length === 0 ? (
        <p style={{ margin: "10px 0 0", fontSize: 14.5, lineHeight: 1.5 }}>{proposal.summary}</p>
      ) : (
        <div style={{ marginTop: 11 }}>
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
          className="btn btn-brass btn-sm"
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
      <span className="eyebrow on-ink" style={{ color: "var(--brass-lit)" }}>
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
            className="btn btn-brass btn-sm"
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
            className="btn btn-brass btn-sm"
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
  return (
    <div>
      <span>{label}</span>
      {plan ? (
        <>
          <b>RM{displayRinggit(plan.required_contribution_per_payday_sen)} / payday</b>
          <small>RM{displayRinggit(plan.target_amount_sen)} by {plan.target_date}</small>
        </>
      ) : (
        <b>No active plan</b>
      )}
    </div>
  );
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
      {attachment.kind === "voice" ? "Voice note" : "Receipt"} · {attachment.merchant}
    </span>
  );
}
