import { useRef, useState } from "react";

import type { Capture } from "@kira/contracts";

import { useCreateDraft, useReadCapture } from "../api/hooks";
import { IcArrow, IcCam, IcImg } from "./Icons";
import { Sheet } from "./Sheet";

type ScanSheetProps = {
  onClose: () => void;
  onAsk: (text: string, attachment: Capture & { preview?: string }) => void;
};

/**
 * Point the camera at a receipt.
 *
 * `capture="environment"` opens the rear camera on a phone and falls back to
 * the file picker everywhere else, so the same control works on the desk and
 * in the queue. The bytes go to the reader; what comes back is a proposal
 * with a confidence on every field, and it stays a proposal until confirmed.
 */
export function ScanSheet({ onClose, onAsk }: ScanSheetProps) {
  return (
    <Sheet label="Scan a receipt" onClose={onClose}>
      <div className="grab" />
      <ScanBody onClose={onClose} onAsk={onAsk} />
    </Sheet>
  );
}

/** The reading itself, so the entry sheet can host it beside the other ways in. */
export function ScanBody({ onClose, onAsk }: ScanSheetProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const read = useReadCapture("receipt");
  const draft = useCreateDraft();
  const result = read.data;

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setPreview(URL.createObjectURL(file));
    read.mutate(file);
  };

  return (
    <>
      <div className="sheet-head">
        <div>
          <p className="eyebrow on-ink" style={{ margin: 0 }}>
            {result ? "What I read" : "Receipt"}
          </p>
          <h2 style={{ margin: "5px 0 0", fontSize: 20, fontWeight: 800, letterSpacing: "-.03em" }}>
            {result ? "Check it before I use it" : "Show me the receipt"}
          </h2>
        </div>
      </div>

      {!result && (
        <>
          <div className="pick-grid">
            <button className="pick" onClick={() => fileRef.current?.click()}>
              <IcCam size={22} />
              <b>Take a photo</b>
              <span>Camera, or the camera roll.</span>
            </button>
            <button
              className="pick"
              onClick={() => read.mutate(new Blob(["sample-receipt"]))}
              disabled={read.isPending}
            >
              <IcImg size={22} />
              <b>Use a sample</b>
              <span>A Malaysian lunch receipt.</span>
            </button>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            capture="environment"
            aria-label="Receipt photo"
            onChange={(event) => void onFile(event.target.files?.[0])}
            style={{ display: "none" }}
          />
          <p className="sheet-note">
            The photo goes to the reader and nowhere else. Nothing reaches your ledger until
            you confirm it.
          </p>
        </>
      )}

      {preview && (
        <div className="scanframe">
          <img src={preview} alt="The receipt you chose" />
          {read.isPending && <span className="laser" />}
        </div>
      )}

      {read.isPending && (
        <div style={{ display: "flex", alignItems: "center", gap: 11, marginTop: 16 }}>
          <span className="thinking">
            <i />
            <i />
            <i />
          </span>
          <span style={{ fontSize: 13, color: "rgba(233,237,233,.6)" }}>
            Finding the merchant, the total and the date…
          </span>
        </div>
      )}

      {read.isError && <p className="sheet-note">I could not read that one. Try another photo.</p>}

      {result && (
        <>
          <div style={{ marginTop: 16 }}>
            {result.fields.map((field, index) => (
              <div className="field" key={field.label} style={{ animationDelay: `${index * 90}ms` }}>
                <span className="field-l">{field.label}</span>
                <span className="field-v">{field.value}</span>
                <span className="field-c">
                  <i style={{ width: `${field.confidence}%` }} />
                  <span>{field.confidence}%</span>
                </span>
              </div>
            ))}
          </div>
          <p className="sheet-note">{result.note}</p>
          <div style={{ display: "flex", gap: 9, marginTop: 18 }}>
            <button
              className="btn btn-sm btn-ghost"
              style={{ flex: 1 }}
              disabled={draft.isPending}
              onClick={() =>
                draft.mutate(
                  {
                    merchant: result.merchant,
                    amount_sen: result.amount_sen,
                    occurred_on: result.occurred_on,
                    category: result.category,
                    source: result.source,
                    confidence: result.confidence,
                    note: result.note,
                  },
                  { onSuccess: onClose },
                )
              }
            >
              Save as draft
            </button>
            <button
              className="btn btn-brass btn-sm"
              style={{ flex: 1 }}
              onClick={() =>
                onAsk("What does this receipt do to my day?", {
                  ...result,
                  preview: preview ?? undefined,
                })
              }
            >
              Ask Kira <IcArrow size={14} />
            </button>
          </div>
        </>
      )}
    </>
  );
}
