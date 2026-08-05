import type { Meta, StoryObj } from '@storybook/react';

import { FormBuilder, FormList, type CaptureForm } from './form-builder';

const schema = {
  fields: [
    { name: 'first_name', type: 'text', label: 'Name', required: true, options: [] },
    { name: 'email', type: 'email', label: 'Work email', required: true, options: [] },
  ],
  submit_label: 'Talk to sales',
};

const draft: CaptureForm = {
  id: 'f1',
  name: 'Contact us',
  type: 'embedded',
  schema,
  published_schema: {},
  allowed_origins: ['https://sharma-textiles.in'],
  is_published: false,
  published_at: null,
  has_unpublished_changes: false,
  version: 1,
};

const published: CaptureForm = {
  ...draft,
  published_schema: schema,
  is_published: true,
  published_at: '2026-08-04T10:00:00+05:30',
};

/**
 * The third story is the important one: a published form whose draft has moved
 * on. If that state is not obvious, someone will edit a field and assume the
 * change is live.
 */
const meta = {
  title: 'Forms/FormBuilder',
  component: FormBuilder,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof FormBuilder>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Draft: Story = { args: { form: draft } };

export const Published: Story = { args: { form: published } };

export const PublishedWithPendingChanges: Story = {
  args: { form: { ...published, has_unpublished_changes: true } },
};

export const List: StoryObj = {
  render: () => (
    <FormList
      forms={[draft, { ...published, has_unpublished_changes: true }]}
      tenantSlug="acme"
    />
  ),
};

export const EmptyList: StoryObj = {
  render: () => <FormList forms={[]} tenantSlug="acme" />,
};
