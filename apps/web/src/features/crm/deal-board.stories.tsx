import type { Meta, StoryObj } from '@storybook/react';

import { DealBoard, type BoardStage } from './deal-board';

const stages: BoardStage[] = [
  {
    id: 'stage-new',
    name: 'New',
    probability: 10,
    is_lost: false,
    deal_count: 2,
    value_minor: 45_00_000,
    deals: [
      {
        id: 'deal-1',
        title: 'Sharma Textiles - ERP rollout',
        amount_minor: 25_00_000,
        currency: 'INR',
        status: 'open',
        stage_id: 'stage-new',
        account_name: 'Sharma Textiles',
        version: 1,
      },
      {
        id: 'deal-2',
        title: 'Kadam Logistics - fleet CRM',
        amount_minor: 20_00_000,
        currency: 'INR',
        status: 'open',
        stage_id: 'stage-new',
        account_name: 'Kadam Logistics',
        version: 3,
      },
    ],
  },
  {
    id: 'stage-proposal',
    name: 'Proposal',
    probability: 60,
    is_lost: false,
    deal_count: 1,
    value_minor: 80_00_000,
    deals: [
      {
        id: 'deal-3',
        title: 'Iyer Hospitals - patient intake',
        amount_minor: 80_00_000,
        currency: 'INR',
        status: 'open',
        stage_id: 'stage-proposal',
        account_name: 'Iyer Hospitals',
        version: 7,
      },
    ],
  },
  {
    id: 'stage-lost',
    name: 'Lost',
    probability: 0,
    is_lost: true,
    deal_count: 0,
    value_minor: 0,
    deals: [],
  },
];

/**
 * The pipeline as columns.
 *
 * The empty column is a story rather than an afterthought: an empty state that
 * renders as an unlabelled box is a real accessibility failure, and it is the
 * state most likely to be skipped in manual review.
 */
const meta = {
  title: 'CRM/DealBoard',
  component: DealBoard,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof DealBoard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Populated: Story = {
  args: { stages },
};

export const EmptyPipeline: Story = {
  args: { stages: stages.map((stage) => ({ ...stage, deals: [], deal_count: 0, value_minor: 0 })) },
};
