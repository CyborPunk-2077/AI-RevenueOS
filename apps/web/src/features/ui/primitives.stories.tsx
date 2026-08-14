import type { Meta, StoryObj } from '@storybook/react';

import { Avatar } from './avatar';
import { ChannelIcon } from './channel-icon';
import { Button, Checkbox, FieldRow } from './controls';
import { Column, DataTable, TableEmpty } from './data-table';
import { Money, RelativeTime } from './format';
import { MetricStrip } from './metric-strip';
import {
  Card,
  EmptyState,
  ListSkeleton,
  PageHeader,
  SectionHeader,
  Stat,
} from './primitives';
import { RecordHeader } from './record-header';
import { LabelChip, MissingValue, SeverityMark, StatusText } from './status';
import { ThemePair } from './theme-pair';
import { FilterLinks, Toolbar } from './toolbar';

/**
 * The design system, on one page, in both themes.
 *
 * If a contrast or labelling regression lands it fails here first, rather than in
 * whichever feature happened to import the component. Every story renders inside
 * `ThemePair` so the accessibility gate - which visits each story once - measures
 * the dark palette as well as the light one.
 */
const meta = {
  title: 'Design System/Primitives',
  parameters: { layout: 'padded' },
} satisfies Meta;

export default meta;
type Story = StoryObj;

/**
 * Section 9's preference order, shown in the order it should be reached for:
 * plain text, emphasised text, then a chip only where the word alone is
 * genuinely ambiguous.
 */
export const Status: Story = {
  render: () => (
    <ThemePair>
      <div className="space-y-3 text-sm">
        <p>
          <StatusText>Contacted</StatusText> · <StatusText tone="critical">Overdue</StatusText> ·{' '}
          <MissingValue>Unassigned</MissingValue> ·{' '}
          <StatusText tone="warning">Due today</StatusText> ·{' '}
          <StatusText tone="positive">Answered</StatusText>
        </p>
        <p className="flex flex-wrap gap-2">
          <LabelChip>sample</LabelChip>
          <LabelChip tone="critical">failed</LabelChip>
          <LabelChip tone="accent">pilot</LabelChip>
        </p>
        <p className="relative flex flex-wrap gap-2 border-l-2 border-critical pl-3">
          <SeverityMark tone="critical" label="Overdue" />
          <span className="text-muted-foreground">
            A row carrying the 2px critical mark, which is what a whole row gets
            instead of a badge.
          </span>
        </p>
      </div>
    </ThemePair>
  ),
};

export const People: Story = {
  render: () => (
    <ThemePair>
      <div className="flex items-center gap-3">
        <Avatar name="GreenField Foods" />
        <Avatar name="Amit Patel" size="md" />
        <Avatar name="Neha Sharma" size="lg" />
        <Avatar name="Anand Xerox" size="lg" tinted={false} />
      </div>
      <p className="mt-3 text-[13px] text-muted-foreground">
        Initials only, deterministic. No photograph is ever fetched or generated.
      </p>
    </ThemePair>
  ),
};

export const Channels: Story = {
  render: () => (
    <ThemePair>
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <ChannelIcon channel="whatsapp" withLabel />
        <ChannelIcon channel="email" withLabel />
        <ChannelIcon channel="call" withLabel />
        <ChannelIcon channel="web_chat" withLabel />
      </div>
    </ThemePair>
  ),
};

export const Metrics: Story = {
  render: () => (
    <ThemePair>
      <MetricStrip
        metrics={[
          { key: 'a', label: 'First response (typical)', value: '2 hrs' },
          { key: 'b', label: 'Waiting for a reply', value: '7' },
          { key: 'c', label: 'Answered', value: '23 of 30' },
          { key: 'd', label: 'Overdue follow-ups', value: '3', emphasis: 'critical' },
          { key: 'e', label: 'Open pipeline', value: '₹18,40,000' },
        ]}
      />
      <div className="mt-5">
        <Stat label="Open deals" value="4" hint="Not yet won or lost" />
      </div>
    </ThemePair>
  ),
};

interface Row {
  id: string;
  business: string;
  contact: string;
  owner: string;
  waiting: string;
  overdue: boolean;
}

const ROWS: Row[] = [
  {
    id: '1',
    business: 'GreenField Foods',
    contact: 'Amit Patel',
    owner: 'Neha Sharma',
    waiting: '3 days',
    overdue: true,
  },
  {
    id: '2',
    business: 'Anand Xerox',
    contact: '—',
    owner: 'Unassigned',
    waiting: '4 hrs',
    overdue: false,
  },
];

const COLUMNS: Array<Column<Row>> = [
  {
    key: 'business',
    header: 'Business',
    cell: (row) => (
      <span className="flex items-center gap-2">
        <Avatar name={row.business} />
        <span className="font-medium text-foreground">{row.business}</span>
      </span>
    ),
  },
  { key: 'contact', header: 'Primary contact', dropAt: 900, cell: (row) => row.contact },
  {
    key: 'owner',
    header: 'Owner',
    cell: (row) =>
      row.owner === 'Unassigned' ? (
        <MissingValue>Unassigned</MissingValue>
      ) : (
        row.owner
      ),
  },
  { key: 'waiting', header: 'Waiting', align: 'right', cell: (row) => row.waiting },
];

export const Table: Story = {
  render: () => (
    <ThemePair>
      <DataTable
        caption="Prospects waiting for a first reply"
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(row) => row.id}
        stickyHeader={false}
        severity={(row) => (row.overdue ? { tone: 'critical', label: 'Overdue' } : null)}
      />
    </ThemePair>
  ),
};

export const GroupedTable: Story = {
  render: () => (
    <ThemePair>
      <DataTable
        caption="Everything that needs attention now"
        columns={COLUMNS}
        rowKey={(row) => row.id}
        stickyHeader={false}
        groups={[
          { key: 'waiting', label: 'Waiting for a first reply', count: 2, rows: ROWS },
          { key: 'due', label: 'Follow-ups due today', count: 1, rows: [ROWS[0]!] },
        ]}
      />
    </ThemePair>
  ),
};

export const TableEmptyState: Story = {
  render: () => (
    <ThemePair>
      <DataTable
        caption="Prospects"
        columns={COLUMNS}
        rows={[]}
        rowKey={(row) => row.id}
        empty={
          <TableEmpty
            title="No prospects yet"
            description="Add a business, import a spreadsheet, or publish an enquiry form and they will arrive here."
            action={<Button variant="primary">Add a business</Button>}
          />
        }
      />
    </ThemePair>
  ),
};

export const Controls: Story = {
  render: () => (
    <ThemePair>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary">Add a business</Button>
          <Button variant="secondary">More details</Button>
          <Button variant="ghost">Cancel</Button>
          <Button variant="danger">Disqualify</Button>
          <Button variant="secondary" disabled>
            Export (not available)
          </Button>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <FieldRow id="story-name" label="Business name" width="md">
            {(props) => <input {...props} defaultValue="GreenField Foods" />}
          </FieldRow>
          <FieldRow
            id="story-phone"
            label="Phone"
            width="sm"
            error="Enter a valid phone number, for example +91 98450 12201."
          >
            {(props) => <input {...props} defaultValue="9845" />}
          </FieldRow>
        </div>

        <Checkbox id="story-check" label="Pin to the top" />
      </div>
    </ThemePair>
  ),
};

export const Headers: Story = {
  render: () => (
    <ThemePair>
      <div className="space-y-6">
        <PageHeader
          title="Prospects"
          description="4 enquiries have had no reply yet."
          actions={<Button variant="primary">Add a business</Button>}
        />
        <RecordHeader
          subject="GreenField Foods Pvt. Ltd."
          marker={<LabelChip>sample</LabelChip>}
          facts={[
            { key: 'contact', label: 'Primary contact', value: 'Amit Patel' },
            { key: 'phone', label: 'Phone', value: '+91 98450 12201' },
            { key: 'owner', label: 'Owner', value: 'Neha Sharma' },
            { key: 'source', label: 'Source', value: 'Referral' },
          ]}
          actions={<Button variant="secondary">Record an outreach</Button>}
        />
        <SectionHeader
          title="Needs attention now"
          description="Oldest wait first."
          actions={<span className="text-[13px] text-muted-foreground">12 prospects</span>}
        />
      </div>
    </ThemePair>
  ),
};

export const Filters: Story = {
  render: () => (
    <ThemePair>
      <Toolbar actions={<Button variant="primary">Add a business</Button>}>
        <FilterLinks
          active="awaiting"
          links={[
            { key: 'all', href: '#', label: 'All', count: 19 },
            { key: 'awaiting', href: '#', label: 'Waiting for a first reply', count: 4 },
            { key: 'unassigned', href: '#', label: 'Unassigned', count: 4 },
            { key: 'none', href: '#', label: 'No next action', count: 8 },
          ]}
        />
      </Toolbar>
    </ThemePair>
  ),
};

export const Times: Story = {
  render: () => (
    <ThemePair>
      <div className="space-y-1 text-sm">
        <p>
          Waiting <RelativeTime iso={new Date(Date.now() - 3 * 86_400_000).toISOString()} />
        </p>
        <p>
          Due <RelativeTime iso={new Date().toISOString()} mode="date" />
        </p>
        <p>
          Value <Money minor={1_84_00_000} />
        </p>
      </div>
    </ThemePair>
  ),
};

export const Surfaces: Story = {
  render: () => (
    <ThemePair>
      <Card>
        <p className="text-[13px] font-semibold text-foreground">A panel</p>
        <p className="mt-1 text-sm text-muted-foreground">
          One border, no shadow, no lift. Containment is earned.
        </p>
      </Card>
    </ThemePair>
  ),
};

export const Loading: Story = {
  render: () => (
    <ThemePair>
      <ListSkeleton rows={3} />
    </ThemePair>
  ),
};

export const Empty: Story = {
  render: () => (
    <ThemePair>
      <EmptyState
        title="Nothing is overdue"
        description="Every scheduled follow-up is still in the future. Open Prospects to pick up new enquiries."
      />
    </ThemePair>
  ),
};
