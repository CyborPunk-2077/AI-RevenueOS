import type { ReactNode } from 'react';
import { cn } from './cn';
import { SeverityMark, type Severity } from './status';

/**
 * The shared table.
 *
 * Tables are Sangam's primary interface, not a fallback for a chart that did not
 * fit. Everything density-related lives here so a change to row height or cell
 * padding happens once rather than in eight screens that drifted apart.
 *
 * The rules it encodes:
 *
 * - **No zebra striping.** A 1px rule per row is enough and far calmer.
 * - **The identifying column comes first**, at weight 500, and is the link
 *   target. Rows do not link as a whole: a row-wide click target makes text
 *   selection impossible and would need the 44px exemption removed to be dense.
 * - **Numeric and duration columns are right-aligned** and tabular. Text is
 *   left-aligned. Data is never centred.
 * - **Severity is a 2px rule**, absolutely positioned so an unmarked row's text
 *   does not sit two pixels to the left of a marked one.
 * - **Groups are headings inside the same table**, so the columns stay aligned
 *   across them and the eye reads one grid rather than four tables.
 * - **Every table has a caption**, and column dropping at narrow widths is
 *   declared per column rather than left to horizontal scrolling.
 */

export interface Column<T> {
  key: string;
  header: string;
  align?: 'left' | 'right';
  /** Fixed width for metadata columns; the identifying column flexes. */
  width?: string;
  /** The width below which this column is dropped, per the screen's own order. */
  dropAt?: 900 | 1100;
  cell: (row: T) => ReactNode;
}

export interface RowGroup<T> {
  key: string;
  label: string;
  count?: number;
  rows: T[];
  /** Said beside the heading where the grouping rule is not self-evident. */
  hint?: string;
  /**
   * The group's `tbody` marker. Several of these are asserted by browser tests
   * that predate the grouping - `no-reply-rows` has to keep meaning "the rows
   * nobody has replied to" wherever those rows are drawn.
   */
  testId?: string;
}

const DROP_CLASS: Record<number, string> = {
  900: 'hidden min-[900px]:table-cell',
  1100: 'hidden min-[1100px]:table-cell',
};

function headerClass<T>(column: Column<T>, sticky: boolean): string {
  return cn(
    'truncate px-4 py-2 text-xs font-medium uppercase tracking-[0.04em] text-muted-foreground',
    // On the cells, not on `thead`, and with no `overflow` ancestor between them
    // and the page. Any ancestor whose overflow is not `visible` becomes the
    // containing block for a sticky child: wrapping the table in `overflow-x-auto`
    // made the header stick 52px below the top of that wrapper instead of below
    // the utility bar, which drew a blank band where the first group heading
    // should have been.
    sticky && 'sticky top-[var(--utility-bar-height)] z-10 bg-surface-sunken',
    column.align === 'right' ? 'text-right' : 'text-left',
    column.dropAt ? DROP_CLASS[column.dropAt] : undefined,
  );
}

function cellClass<T>(column: Column<T>, index: number): string {
  return cn(
    // `overflow-hidden` is what makes `truncate` work inside a fixed layout. A
    // cell that wraps to three lines is how a dense table turns into a wall.
    'overflow-hidden px-4 py-2.5 align-middle text-sm',
    index === 0 && 'relative',
    column.align === 'right' ? 'text-right tabular' : 'text-left',
    column.dropAt ? DROP_CLASS[column.dropAt] : undefined,
  );
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  groups,
  rowKey,
  severity,
  bodyTestId,
  rowTestId,
  empty,
  /** Sticks under the utility bar for any table that can outgrow the screen. */
  stickyHeader = true,
  className = '',
}: {
  caption: string;
  columns: Array<Column<T>>;
  rows?: T[];
  groups?: Array<RowGroup<T>>;
  rowKey: (row: T) => string;
  severity?: (row: T) => { tone: Exclude<Severity, 'neutral'>; label: string } | null;
  bodyTestId?: string;
  rowTestId?: (row: T) => string | undefined;
  empty?: ReactNode;
  stickyHeader?: boolean;
  className?: string;
}): JSX.Element {
  const flat = groups ? groups.flatMap((group) => group.rows) : (rows ?? []);

  if (flat.length === 0 && empty) {
    return (
      <div className={cn('rounded-lg border border-border bg-surface', className)}>{empty}</div>
    );
  }

  const renderRow = (row: T): JSX.Element => {
    const mark = severity?.(row) ?? null;
    return (
      <tr
        key={rowKey(row)}
        data-testid={rowTestId?.(row)}
        className="border-b border-border last:border-b-0 transition-colors hover:bg-surface-hover"
      >
        {columns.map((column, index) => (
          <td key={column.key} data-label={column.header} className={cellClass(column, index)}>
            {index === 0 && mark ? <SeverityMark tone={mark.tone} label={mark.label} /> : null}
            {column.cell(row)}
          </td>
        ))}
      </tr>
    );
  };

  // A declared width means the caller has budgeted the row, so the browser is
  // told to respect it rather than letting one long task title decide how wide
  // every other column gets to be.
  const fixed = columns.some((column) => column.width);

  return (
    // No `overflow` on the wrapper: it would clip the sticky header's containing
    // block. The rounded top corners live on the first and last header cells
    // instead, which is why the header carries its own background.
    <div className={cn('rounded-lg border border-border bg-surface', className)}>
      {/* `table-stacked` is the media-query hook that turns rows into records
          below 700px. See the block at the foot of `globals.css`. */}
      <table
        className={cn('table-stacked w-full border-collapse text-left', fixed && 'table-fixed')}
      >
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border-strong">
            {columns.map((column, index) => (
              <th
                key={column.key}
                scope="col"
                title={column.header}
                style={column.width ? { width: column.width } : undefined}
                className={cn(
                  headerClass(column, stickyHeader),
                  !stickyHeader && 'bg-surface-sunken',
                  index === 0 && 'rounded-tl-lg',
                  index === columns.length - 1 && 'rounded-tr-lg',
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>

        {groups ? (
          groups.map((group) => (
            <tbody key={group.key} data-testid={group.testId ?? `group-${group.key}`}>
              <tr>
                {/*
                  A full-width heading row inside the same table. Four separate
                  tables would let four sets of columns disagree about where the
                  owner is, which is the thing that makes a long queue unscannable.
                */}
                <th
                  scope="colgroup"
                  colSpan={columns.length}
                  className="border-b border-border bg-surface px-4 pb-1.5 pt-4 text-left text-[13px] font-semibold text-foreground"
                >
                  {group.label}
                  {group.count === undefined ? null : (
                    <span className="ml-2 tabular font-normal text-muted-foreground">
                      {group.count}
                    </span>
                  )}
                  {group.hint ? (
                    <span className="ml-2 font-normal text-muted-foreground">{group.hint}</span>
                  ) : null}
                </th>
              </tr>
              {group.rows.map(renderRow)}
            </tbody>
          ))
        ) : (
          <tbody data-testid={bodyTestId}>{(rows ?? []).map(renderRow)}</tbody>
        )}
      </table>
    </div>
  );
}

/**
 * The empty state that sits inside the table frame.
 *
 * One sentence saying what would put rows here, plus the action that would. A
 * bare "No results" leaves somebody guessing whether the product is broken or
 * they simply have no data yet.
 */
export function TableEmpty({
  title,
  description,
  action,
  'data-testid': testId,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  'data-testid'?: string;
}): JSX.Element {
  return (
    <div data-testid={testId} className="px-6 py-12 text-center">
      <p className="text-[15px] font-semibold text-foreground">{title}</p>
      <p className="mx-auto mt-1.5 max-w-reading text-sm text-muted-foreground">{description}</p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
