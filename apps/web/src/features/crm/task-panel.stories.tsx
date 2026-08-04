import type { Meta, StoryObj } from '@storybook/react';

import { TaskPanel, type TaskEntry } from './task-panel';

const tasks: TaskEntry[] = [
  {
    id: 'task-1',
    title: 'Send the revised proposal',
    status: 'open',
    priority: 'high',
    due_at: '2026-08-06T09:30:00+05:30',
    is_overdue: false,
    assignee_name: 'Asha Menon',
    version: 1,
  },
  {
    id: 'task-2',
    title: 'Chase the signed MSA',
    status: 'open',
    priority: 'urgent',
    due_at: '2026-07-30T09:30:00+05:30',
    is_overdue: true,
    assignee_name: 'Rahul Nair',
    version: 4,
  },
  {
    id: 'task-3',
    title: 'Log the discovery call notes',
    status: 'done',
    priority: 'normal',
    due_at: null,
    is_overdue: false,
    assignee_name: null,
    version: 2,
  },
];

/**
 * Follow-ups on one record. Overdue is conveyed by more than colour - the a11y
 * gate fails a story that leans on a red badge alone.
 */
const meta = {
  title: 'CRM/TaskPanel',
  component: TaskPanel,
  parameters: { layout: 'padded' },
  args: { parent: 'contacts' as const, parentId: 'contact-1' },
} satisfies Meta<typeof TaskPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithTasks: Story = {
  args: { tasks },
};

export const Overdue: Story = {
  args: { tasks: tasks.filter((task) => task.is_overdue) },
};

export const Empty: Story = {
  args: { tasks: [] },
};
