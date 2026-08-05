import type { Meta, StoryObj } from '@storybook/react';

import { DuplicateReview, type Candidate, type LeadSummary } from './duplicate-review';

const lead: LeadSummary = {
  id: 'l1',
  first_name: 'Asha',
  last_name: 'Menon',
  email: 'asha@sharma-textiles.in',
  phone: null,
};

const candidates: Candidate[] = [
  {
    candidate_lead_id: 'l2',
    match_reason: 'exact_email',
    confidence: 0.98,
    candidate: {
      first_name: 'Asha',
      last_name: 'Menon',
      email: 'asha@sharma-textiles.in',
      phone: '+919812345678',
      status: 'new',
    },
  },
  {
    candidate_lead_id: 'l3',
    match_reason: 'fuzzy_name',
    confidence: 0.62,
    candidate: {
      first_name: 'Aasha',
      last_name: 'Menon',
      email: null,
      phone: '+919812345678',
      status: 'contacted',
    },
  },
];

const meta = {
  title: 'Leads/DuplicateReview',
  component: DuplicateReview,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof DuplicateReview>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithCandidates: Story = { args: { lead, candidates } };

export const NothingFlagged: Story = { args: { lead, candidates: [] } };
