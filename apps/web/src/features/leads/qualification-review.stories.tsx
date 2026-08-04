import type { Meta, StoryObj } from '@storybook/react';

import { QualificationReview, type Qualification } from './qualification-review';

const base: Qualification = {
  score: 82,
  category: 'hot',
  evidence: [
    {
      criterion: 'budget',
      value: '15L INR',
      source: 'web_form',
      excerpt: 'Approved budget for this quarter',
      confidence: 0.91,
    },
    { criterion: 'authority', value: 'Director', source: 'enrichment', confidence: 0.74 },
  ],
  reasons: ['Budget stated explicitly', 'Decision maker identified'],
  missing_fields: ['timeline'],
  qualified_by: 'ai',
  degraded: false,
  review_state: 'pending',
  provenance: { prompt_version: 'qualify_lead/v1', model: 'pinned' },
};

/**
 * Human review of a lead score. A person must be able to accept, edit, reject or
 * defer - the specification forbids an autonomous rejection - so every story
 * keeps all four decisions reachable by keyboard.
 */
const meta = {
  title: 'Leads/QualificationReview',
  component: QualificationReview,
  parameters: { layout: 'padded' },
  args: { onDecision: () => undefined },
} satisfies Meta<typeof QualificationReview>;

export default meta;
type Story = StoryObj<typeof meta>;

export const AiScoredHot: Story = {
  args: { qualification: base },
};

export const DegradedToRuleEngine: Story = {
  args: {
    qualification: {
      ...base,
      score: 45,
      category: 'warm',
      qualified_by: 'rule',
      degraded: true,
      reasons: ['Scored by rules: the model was unavailable'],
      evidence: [],
    },
  },
};

export const ColdWithMissingFields: Story = {
  args: {
    qualification: {
      ...base,
      score: 12,
      category: 'cold',
      reasons: ['No budget signal', 'No authority signal'],
      missing_fields: ['budget', 'authority', 'timeline'],
      evidence: [],
    },
  },
};

export const AlreadyReviewed: Story = {
  args: {
    qualification: { ...base, review_state: 'accepted' },
    disabled: true,
  },
};
