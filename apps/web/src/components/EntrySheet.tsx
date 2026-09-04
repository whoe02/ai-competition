import { useState } from "react";

import type { Capture, Category } from "@kira/contracts";

import { IcArrow, IcCam, IcMic, IcPen } from "./Icons";
import { ManualBody } from "./ManualSheet";
import { ScanBody } from "./ScanSheet";
import { Sheet } from "./Sheet";
import { VoiceBody } from "./VoiceSheet";

export type EntryAttachment = Capture & { preview?: string };

type EntrySheetProps = {
  onClose: () => void;
  onAsk: (text: string, attachment?: EntryAttachment) => void;
  /** The category vocabulary, when it has been fetched. The manual form needs it. */
  categories?: Category[];
};

type Mode = "type" | "say" | "show";
/** Who works out the fields: the user, or Kira from what they said. */
type Route = "ask" | "manual";

const MODES: { id: Mode; label: string; hint: string; Icon: typeof IcPen }[] = [
  { id: "type", label: "Type", hint: "Write it", Icon: IcPen },
  { id: "say", label: "Say", hint: "Speak it", Icon: IcMic },
  { id: "show", label: "Show", hint: "Photograph it", Icon: IcCam },
];

const ROUTES: { id: Route; label: string; hint: string }[] = [
  { id: "ask", label: "Ask Kira", hint: "Type, say or show it" },
  { id: "manual", label: "Manual", hint: "In or out, by hand" },
];

/**
 * One way in, by either route.
 *
 * Ask Kira is the same act said three ways — typing, speaking, photographing —
 * and it ends with a proposal to check, because a sentence has to be read
 * before it can become fields. The manual form skips the reading: when the user
 * already knows the merchant, the figure and the day, being asked to write a
 * sentence for a model to take apart again is the longer road to the same
 * draft. It is also the route that can say money went the other way in one tap,
 * which is why the direction lives inside it rather than above both.
 *
 * Either way it becomes a draft they confirm. Neither writes to the ledger.
 */
export function EntrySheet({ onClose, onAsk, categories }: EntrySheetProps) {
  const [route, setRoute] = useState<Route>("ask");
  const [mode, setMode] = useState<Mode>("type");

  return (
    <Sheet label="Tell Kira about money" onClose={onClose}>
      <div className="grab" />
      <div className="entry-flow" role="tablist" aria-label="How the entry gets its figures">
        {ROUTES.map(({ id, label, hint }) => (
          <button
            key={id}
            role="tab"
            aria-label={label}
            aria-selected={route === id}
            className={route === id ? "on" : ""}
            onClick={() => setRoute(id)}
          >
            <b>{label}</b>
            <span>{hint}</span>
          </button>
        ))}
      </div>

      {route === "manual" ? (
        <ManualBody onClose={onClose} categories={categories} />
      ) : (
        <>
          <div className="entry-tabs" role="tablist" aria-label="How to tell Kira">
            {MODES.map(({ id, label, hint, Icon }) => (
              <button
                key={id}
                role="tab"
                aria-label={label}
                aria-selected={mode === id}
                className={`entry-tab ${mode === id ? "on" : ""}`}
                onClick={() => setMode(id)}
              >
                <Icon size={17} />
                <b>{label}</b>
                <span>{hint}</span>
              </button>
            ))}
          </div>

          {mode === "type" && <TypeBody onAsk={onAsk} onClose={onClose} />}
          {mode === "say" && <VoiceBody onClose={onClose} onAsk={onAsk} />}
          {mode === "show" && <ScanBody onClose={onClose} onAsk={onAsk} />}
        </>
      )}
    </Sheet>
  );
}

/**
 * A sentence, in whatever shape it arrives.
 *
 * There is no form here on purpose: people do not remember spending in fields,
 * and a parser strict enough to demand them would reject most of what they say.
 * Kira reads the sentence and proposes the fields back.
 */
function TypeBody({
  onAsk,
  onClose,
}: {
  onAsk: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");

  const send = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onAsk(trimmed);
    onClose();
  };

  return (
    <>
      <div className="sheet-head">
        <div>
          <p className="eyebrow on-ink" style={{ margin: 0 }}>
            In your words
          </p>
          <h2 style={{ margin: "5px 0 0", fontSize: 20, fontWeight: 800, letterSpacing: "-.03em" }}>
            Tell me what moved
          </h2>
        </div>
      </div>

      <label className="entry-label" htmlFor="entry-text">
        What did you spend?
      </label>
      <textarea
        id="entry-text"
        className="entry-text"
        rows={3}
        placeholder="Spent RM12.50 on lunch — or received RM5,000 salary"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            send();
          }
        }}
      />
      <p className="sheet-note">
        Spending and income both come back as drafts before they affect your balance. If you
        leave out the amount, I will ask rather than guess.
      </p>
      <div style={{ display: "flex", gap: 9, marginTop: 16 }}>
        <button className="btn btn-sm btn-ghost" style={{ flex: 1 }} onClick={onClose}>
          Cancel
        </button>
        <button className="btn btn-brass btn-sm" style={{ flex: 1 }} onClick={send}>
          Tell Kira <IcArrow size={14} />
        </button>
      </div>
    </>
  );
}
