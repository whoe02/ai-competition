import { useState } from "react";

import type { Capture } from "@kira/contracts";

import { IcArrow, IcCam, IcMic, IcPen } from "./Icons";
import { ScanBody } from "./ScanSheet";
import { Sheet } from "./Sheet";
import { VoiceBody } from "./VoiceSheet";

export type EntryAttachment = Capture & { preview?: string };

type EntrySheetProps = {
  onClose: () => void;
  onAsk: (text: string, attachment?: EntryAttachment) => void;
};

type Mode = "type" | "say" | "show";

const MODES: { id: Mode; label: string; hint: string; Icon: typeof IcPen }[] = [
  { id: "type", label: "Type", hint: "Write it", Icon: IcPen },
  { id: "say", label: "Say", hint: "Speak it", Icon: IcMic },
  { id: "show", label: "Show", hint: "Photograph it", Icon: IcCam },
];

/**
 * One way in, three ways of saying it.
 *
 * Typing, speaking and photographing are the same act — telling Kira about
 * money that has already moved — so they belong behind one control rather than
 * three. Whichever way it arrives, it becomes a proposal the user checks, and
 * a draft they confirm. None of them writes to the ledger.
 */
export function EntrySheet({ onClose, onAsk }: EntrySheetProps) {
  const [mode, setMode] = useState<Mode>("type");

  return (
    <Sheet label="Add spending" onClose={onClose}>
      <div className="grab" />
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
            Just tell me what you spent
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
        placeholder="Grabbed lunch at the mamak, twelve fifty"
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
        I will read it back as a draft before anything is recorded — and if you leave out the
        amount, I will ask rather than guess.
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
