'use client';

import { useId, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Card } from '@/features/ui/primitives';

/**
 * Charts, each paired with the table it was drawn from.
 *
 * An SVG chart is close to unreadable with a screen reader, and a series
 * distinguished only by hue is unreadable to anyone with a colour vision
 * deficiency. So every chart here ships with a "View as table" toggle over the
 * same data, the chart itself is `aria-hidden`, and the table is the accessible
 * name. That is not a compromise: the table is frequently the faster way to read
 * an exact figure anyway.
 *
 * Colours come from the design tokens rather than Recharts defaults, so a theme
 * change moves the charts with everything else and dark mode does not produce
 * neon on charcoal.
 */

const SERIES = ['hsl(var(--primary))', 'hsl(var(--accent))', 'hsl(var(--success))'];
const AXIS = 'hsl(var(--muted-foreground))';
const GRID = 'hsl(var(--border))';

interface Row {
  readonly label: string;
  readonly value: number;
}

function ChartFrame({
  title,
  description,
  rows,
  valueHeader,
  format,
  children,
}: {
  title: string;
  description?: string;
  rows: Row[];
  valueHeader: string;
  format?: (value: number) => string;
  children: React.ReactNode;
}): JSX.Element {
  const [asTable, setAsTable] = useState(false);
  const tableId = useId();
  const render = format ?? ((value: number) => value.toLocaleString('en-IN'));

  return (
    <Card className="animate-fade-up">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="heading text-sm">{title}</h3>
          {description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          ) : null}
        </div>
        <button
          type="button"
          aria-expanded={asTable}
          aria-controls={tableId}
          onClick={() => setAsTable((current) => !current)}
          className="interactive rounded-full border border-border px-3 py-1 text-xs"
        >
          {asTable ? 'View as chart' : 'View as table'}
        </button>
      </div>

      {rows.length === 0 ? (
        <p className="mt-6 text-sm text-muted-foreground">Nothing to show for this period.</p>
      ) : asTable ? (
        <table id={tableId} className="mt-4 w-full text-left text-sm">
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr className="border-b border-border text-xs uppercase text-muted-foreground">
              <th scope="col" className="py-2">
                {title}
              </th>
              <th scope="col" className="py-2 text-right">
                {valueHeader}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-b border-border/60">
                <th scope="row" className="py-2 font-normal">
                  {row.label}
                </th>
                <td className="py-2 text-right tabular">{render(row.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <>
          {/* The chart is decorative once the table exists; the table below is the
              accessible representation and is always reachable. */}
          <div id={tableId} aria-hidden="true" className="mt-4 h-56">
            {children}
          </div>
          <p className="sr-only">
            {title}. {rows.map((row) => `${row.label}: ${render(row.value)}`).join('. ')}.
          </p>
        </>
      )}
    </Card>
  );
}

// A tooltip is an overlay, which is the one place a shadow is earned.
const tooltipStyle = {
  background: 'hsl(var(--surface))',
  border: '1px solid hsl(var(--border-strong))',
  borderRadius: 'var(--radius)',
  boxShadow: 'var(--shadow-overlay)',
  fontSize: '0.8125rem',
  color: 'hsl(var(--text-primary))',
};

export function PipelineByStage({ rows }: { rows: Row[] }): JSX.Element {
  return (
    <ChartFrame
      title="Pipeline by stage"
      description="Open value in each stage."
      rows={rows}
      valueHeader="Value"
      format={(value) => `₹${(value / 100).toLocaleString('en-IN')}`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke={AXIS} fontSize={11} tickLine={false} />
          <YAxis stroke={AXIS} fontSize={11} tickLine={false} axisLine={false} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'hsl(var(--primary) / 0.06)' }} />
          <Bar dataKey="value" radius={[6, 6, 0, 0]} animationDuration={600}>
            {rows.map((row, index) => (
              <Cell key={row.label} fill={SERIES[index % SERIES.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

export function LeadSourceMix({ rows }: { rows: Row[] }): JSX.Element {
  return (
    <ChartFrame
      title="Lead sources"
      description="Where leads came from in this period."
      rows={rows}
      valueHeader="Leads"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" stroke={AXIS} fontSize={11} tickLine={false} axisLine={false} />
          <YAxis
            type="category"
            dataKey="label"
            stroke={AXIS}
            fontSize={11}
            width={110}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'hsl(var(--primary) / 0.06)' }} />
          <Bar
            dataKey="value"
            fill="hsl(var(--primary))"
            radius={[0, 6, 6, 0]}
            animationDuration={600}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

export function WonOverTime({ rows }: { rows: Row[] }): JSX.Element {
  return (
    <ChartFrame
      title="Won over time"
      description="Daily won value."
      rows={rows}
      valueHeader="Won"
      format={(value) => `₹${(value / 100).toLocaleString('en-IN')}`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 8 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke={AXIS} fontSize={11} tickLine={false} />
          <YAxis stroke={AXIS} fontSize={11} tickLine={false} axisLine={false} />
          <Tooltip contentStyle={tooltipStyle} />
          <Line
            type="monotone"
            dataKey="value"
            stroke="hsl(var(--primary))"
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 5 }}
            animationDuration={700}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
