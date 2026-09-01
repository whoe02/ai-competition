import type { ReactNode } from "react";

type IconProps = { size?: number; w?: number };

function Svg({ d, size = 20, w = 1.6 }: IconProps & { d: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={w}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {d}
    </svg>
  );
}

export const IcToday = (p: IconProps) => (
  <Svg {...p} d={<><path d="M4 13.5 12 6l8 7.5" /><path d="M6.5 12v6.5h11V12" /></>} />
);
export const IcActivity = (p: IconProps) => <Svg {...p} d={<path d="M4 12h4l2.5-5 3 10 2.5-5h4" />} />;
export const IcPlan = (p: IconProps) => (
  <Svg {...p} d={<><circle cx="12" cy="12" r="7.6" /><path d="M12 7.6V12l3 2" /></>} />
);
export const IcMore = (p: IconProps) => (
  <Svg
    {...p}
    d={<>
      <circle cx="6" cy="12" r="1.1" fill="currentColor" />
      <circle cx="12" cy="12" r="1.1" fill="currentColor" />
      <circle cx="18" cy="12" r="1.1" fill="currentColor" />
    </>}
  />
);
export const IcBell = (p: IconProps) => (
  <Svg {...p} d={<><path d="M8 15V11a4 4 0 0 1 8 0v4l1.5 2.2h-11L8 15Z" /><path d="M10.6 19.4a1.7 1.7 0 0 0 2.8 0" /></>} />
);
export const IcChev = (p: IconProps) => <Svg {...p} d={<path d="m9.5 6 6 6-6 6" />} />;
export const IcLock = (p: IconProps) => (
  <Svg {...p} d={<><rect x="5.5" y="10.5" width="13" height="9" rx="2.4" /><path d="M8.6 10.5V8.4a3.4 3.4 0 0 1 6.8 0v2.1" /></>} />
);
export const IcCheck = (p: IconProps) => <Svg {...p} w={2} d={<path d="m5.5 12.5 4.2 4.2 8.8-9.4" />} />;
export const IcSpark = (p: IconProps) => (
  <Svg {...p} d={<path d="M12 4.5 13.7 10 19 12l-5.3 2-1.7 5.5L10.3 14 5 12l5.3-2Z" />} />
);
export const IcArrow = (p: IconProps) => <Svg {...p} d={<path d="M5 12h13m-5-5 5 5-5 5" />} />;
export const IcPen = (p: IconProps) => (
  <Svg {...p} d={<><path d="M4 20h4L19 9a2.5 2.5 0 0 0-3.5-3.5L4.5 16.5 4 20Z" /></>} />
);
export const IcCam = (p: IconProps) => (
  <Svg
    {...p}
    d={
      <>
        <path d="M3 8.5h3.5L8 6h8l1.5 2.5H21v10H3v-10Z" />
        <circle cx="12" cy="13" r="3.2" />
      </>
    }
  />
);
export const IcMic = (p: IconProps) => (
  <Svg
    {...p}
    d={
      <>
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path d="M5.5 12a6.5 6.5 0 0 0 13 0M12 18.5V21" />
      </>
    }
  />
);
export const IcImg = (p: IconProps) => (
  <Svg
    {...p}
    d={
      <>
        <rect x="3.5" y="5" width="17" height="14" rx="2.6" />
        <circle cx="9" cy="10" r="1.6" />
        <path d="m4.5 17 4.6-4.3L13 16l2.6-2.2 3.9 3.4" />
      </>
    }
  />
);
export const IcPlus = (p: IconProps) => <Svg {...p} w={2} d={<path d="M12 5.5v13M5.5 12h13" />} />;
export const IcX = (p: IconProps) => <Svg {...p} d={<path d="m6.5 6.5 11 11m0-11-11 11" />} />;
export const IcStop = (p: IconProps) => (
  <Svg {...p} d={<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />} />
);
export const IcTrash = (p: IconProps) => (
  <Svg
    {...p}
    d={
      <>
        <path d="M5.5 7.5h13M9.5 7.5V5.8a1.3 1.3 0 0 1 1.3-1.3h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7" />
        <path d="M7 7.5 7.8 19a1.3 1.3 0 0 0 1.3 1.2h5.8a1.3 1.3 0 0 0 1.3-1.2L17 7.5" />
      </>
    }
  />
);
