import type { LucideIcon } from "lucide-react";
import { ArrowUpRight } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  accent: "violet" | "blue" | "amber" | "green";
}

export function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  accent,
}: MetricCardProps) {
  return (
    <article className="metric-card">
      <div className="metric-top">
        <span className={`metric-icon ${accent}`}>
          <Icon size={19} strokeWidth={1.9} />
        </span>
        <ArrowUpRight className="metric-arrow" size={17} />
      </div>
      <p className="metric-label">{label}</p>
      <div className="metric-value">{value}</div>
      <p className="metric-detail">{detail}</p>
    </article>
  );
}
