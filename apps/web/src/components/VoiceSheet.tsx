import { useEffect, useRef, useState } from "react";

import type { Capture } from "@kira/contracts";

import { useCreateDraft, useReadCapture } from "../api/hooks";
import { IcArrow, IcMic, IcStop } from "./Icons";
import { Sheet } from "./Sheet";

type VoiceSheetProps = {
  onClose: () => void;
  onAsk: (text: string, attachment: Capture) => void;
};

const BARS = 34;

/**
 * Say it rather than type it.
 *
 * The recording is real — `getUserMedia` and `MediaRecorder` — and the bytes
 * go to the same reader the receipt does. Where the browser will not give us a
 * microphone, the sheet says so and offers the sample instead of pretending.
 */
export function VoiceSheet({ onClose, onAsk }: VoiceSheetProps) {
  return (
    <Sheet label="Voice note" onClose={onClose}>
      <div className="grab" />
      <VoiceBody onClose={onClose} onAsk={onAsk} />
    </Sheet>
  );
}

/** The listening itself, so the entry sheet can host it beside the other ways in. */
export function VoiceBody({ onClose, onAsk }: VoiceSheetProps) {
  const [stage, setStage] = useState<"idle" | "listening" | "denied">("idle");
  const [ms, setMs] = useState(0);
  const bars = useRef<(HTMLElement | null)[]>([]);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const analyser = useRef<AnalyserNode | null>(null);
  const read = useReadCapture("voice");
  const draft = useCreateDraft();
  const result = read.data;

  useEffect(() => () => stopTracks(recorder.current), []);

  useEffect(() => {
    if (stage !== "listening") return;
    const timer = setInterval(() => setMs((value) => value + 100), 100);
    let frame = 0;
    const data = new Uint8Array(BARS * 2);
    const draw = () => {
      const node = analyser.current;
      if (node) node.getByteFrequencyData(data);
      bars.current.forEach((bar, index) => {
        if (!bar) return;
        const centre = 1 - Math.abs(index - (BARS - 1) / 2) / ((BARS - 1) / 2);
        const level = node ? (data[index] ?? 0) / 255 : 0.35;
        bar.style.transform = `scaleY(${(0.06 + level * (0.35 + centre * 0.65)).toFixed(3)})`;
      });
      frame = requestAnimationFrame(draw);
    };
    draw();
    return () => {
      clearInterval(timer);
      cancelAnimationFrame(frame);
    };
  }, [stage]);

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const context = new AudioContext();
      const node = context.createAnalyser();
      context.createMediaStreamSource(stream).connect(node);
      analyser.current = node;

      const media = new MediaRecorder(stream);
      chunks.current = [];
      media.ondataavailable = (event) => chunks.current.push(event.data);
      media.onstop = () => {
        stopTracks(media);
        read.mutate(new Blob(chunks.current, { type: media.mimeType || "audio/webm" }));
      };
      recorder.current = media;
      media.start();
      setMs(0);
      setStage("listening");
    } catch {
      setStage("denied");
    }
  };

  const stop = () => {
    recorder.current?.stop();
    setStage("idle");
  };

  const duration = `0:${String(Math.max(1, Math.round(ms / 1000))).padStart(2, "0")}`;

  return (
    <>
      <div className="sheet-head">
        <div>
          <p className="eyebrow on-ink" style={{ margin: 0 }}>
            {result ? "Before I answer" : stage === "listening" ? "Listening" : "Voice"}
          </p>
          <h2 style={{ margin: "5px 0 0", fontSize: 20, fontWeight: 800, letterSpacing: "-.03em" }}>
            {result ? "Did I hear that right?" : "Say it however you like"}
          </h2>
        </div>
      </div>

      {!result && (
        <>
          <div className="mic-stage">
            <span className="mic-glow" />
            <span className="mic-ring" />
            <span className="mic-ring" />
            <span className="mic-ring" />
            <div className="wave">
              {Array.from({ length: BARS }).map((_, index) => (
                <i
                  key={index}
                  ref={(element) => {
                    bars.current[index] = element;
                  }}
                />
              ))}
            </div>
          </div>
          {stage === "listening" && <p className="timer">{duration}</p>}
          {stage === "denied" && (
            <p className="sheet-note">
              This browser will not give me the microphone. Use the sample and I will read it
              the same way.
            </p>
          )}
        </>
      )}

      {read.isPending && (
        <div style={{ display: "flex", alignItems: "center", gap: 11, marginTop: 16 }}>
          <span className="thinking">
            <i />
            <i />
            <i />
          </span>
          <span style={{ fontSize: 13, color: "rgba(233,237,233,.6)" }}>Writing it down…</span>
        </div>
      )}

      {result && (
        <>
          <p className="tscript">{result.transcript}</p>
          <p className="sheet-note">
            I heard it at {result.confidence}% confidence. {result.note}
          </p>
          <div style={{ marginTop: 6 }}>
            {result.fields.map((field) => (
              <div className="field" key={field.label}>
                <span className="field-l">{field.label}</span>
                <span className="field-v">{field.value}</span>
                <span className="field-c">
                  <i style={{ width: `${field.confidence}%` }} />
                  <span>{field.confidence}%</span>
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      <div style={{ display: "flex", gap: 9, marginTop: 20 }}>
        {result ? (
          <>
            <button
              className="btn btn-sm btn-ghost"
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
              onClick={() => onAsk(result.transcript, result)}
            >
              Ask Kira <IcArrow size={14} />
            </button>
          </>
        ) : stage === "listening" ? (
          <>
            <button className="btn btn-sm btn-ghost" style={{ flex: 1 }} onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-brass btn-sm" style={{ flex: 1 }} onClick={stop}>
              <IcStop size={13} /> Stop
            </button>
          </>
        ) : (
          <>
            <button
              className="btn btn-sm btn-ghost"
              style={{ flex: 1 }}
              disabled={read.isPending}
              onClick={() => read.mutate(new Blob(["sample-voice-note"]))}
            >
              Use a sample
            </button>
            <button className="btn btn-brass btn-sm" style={{ flex: 1 }} onClick={() => void start()}>
              <IcMic size={14} /> Record
            </button>
          </>
        )}
      </div>
    </>
  );
}

function stopTracks(media: MediaRecorder | null) {
  media?.stream.getTracks().forEach((track) => track.stop());
}
