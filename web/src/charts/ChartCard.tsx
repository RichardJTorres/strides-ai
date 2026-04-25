import type { ReactNode } from "react";

interface Props {
  title: string;
  subtitle?: ReactNode;
  badge?: ReactNode;
  children: ReactNode;
}

export default function ChartCard({ title, subtitle, badge, children }: Props) {
  return (
    <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
      <div className="flex items-center gap-2 mb-0.5">
        <h3 className="text-gray-100 font-semibold">{title}</h3>
        {badge}
      </div>
      {subtitle && <p className="text-gray-500 text-xs mb-4">{subtitle}</p>}
      {children}
    </section>
  );
}
