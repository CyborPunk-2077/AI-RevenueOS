import { ListSkeleton } from '@/features/ui/primitives';

/**
 * Shown while the server component fetches. A skeleton in the shape of the list
 * stops the page jumping when data lands, which a spinner does not.
 */
export default function Loading(): JSX.Element {
  return <ListSkeleton rows={6} />;
}
