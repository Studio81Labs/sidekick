import type { HTMLAttributes, ReactNode } from "react";

import "./SectionHeading.css";

export type SectionHeadingProps = HTMLAttributes<HTMLDivElement> & {
  heading: ReactNode;
  headingId: string;
};

function joinClassNames(...classNames: Array<string | undefined>) {
  return classNames.filter(Boolean).join(" ");
}

export function SectionHeading({
  children,
  className,
  heading,
  headingId,
  ...props
}: SectionHeadingProps) {
  return (
    <div {...props} className={joinClassNames("section-heading", className)}>
      <h3 id={headingId}>{heading}</h3>
      {children}
    </div>
  );
}
