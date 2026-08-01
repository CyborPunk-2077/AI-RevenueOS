'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import type { TenantId } from '@/lib/tenant-context';

/**
 * Switching tenants must remove every tenant-scoped cache entry and open a new
 * realtime subscription. Leaving stale entries behind would show one tenant's
 * data under another's context.
 */
export function useTenantSwitch(): (from: TenantId, to: TenantId) => Promise<void> {
  const queryClient = useQueryClient();

  return useCallback(
    async (from: TenantId, to: TenantId) => {
      if (from === to) return;

      // Remove, not merely invalidate: invalidation would keep the data readable.
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] === from });
      queryClient.cancelQueries({ predicate: (query) => query.queryKey[0] === from });

      window.dispatchEvent(new CustomEvent('tenant:switch', { detail: { from, to } }));

      const announcer = document.getElementById('status-announcer');
      if (announcer) announcer.textContent = 'Switched organisation. Loading data.';

      await queryClient.prefetchQuery({ queryKey: [to, 'tenant'] });
    },
    [queryClient],
  );
}
