import React from "react";

export function ShowDate(props: { timestamp: number; sticky?: boolean }) {
  const stickyClass = props.sticky === false ? "" : "sticky top-1.5";

  return (
    <div
      className={`${stickyClass} bg-white mx-auto w-[120px] h-[28px] z-1 my-2 border-divider-gray flex items-center justify-center rounded-full`}
    >
      <span className="text-center text-s-bold">
        {new Date(props.timestamp).toLocaleDateString("ko-KR", {
          month: "long",
          day: "numeric",
          weekday: "long",
        })}
      </span>
    </div>
  );
}
