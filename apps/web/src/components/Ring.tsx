import { useEffect, useState } from "react";

type RingProps = { pct: number; size?: number; stroke?: string };

export function Ring({ pct, size = 96, stroke = "#B08C3E" }: RingProps) {
  const radius = size / 2 - 7;
  const circumference = 2 * Math.PI * radius;
  const [on, setOn] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setOn(true), 260);
    return () => clearTimeout(timer);
  }, []);

  return (
    <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }} aria-hidden="true">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="rgba(15,28,26,.09)"
        strokeWidth="6"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={stroke}
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={on ? circumference - circumference * pct : circumference}
        style={{ transition: "stroke-dashoffset 1.4s cubic-bezier(.22,1,.36,1)" }}
      />
    </svg>
  );
}
