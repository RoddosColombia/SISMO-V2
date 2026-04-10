/**
 * BacklogBadge — Sidebar badge showing pending backlog count.
 * Polls GET /api/backlog/count every 60 seconds.
 */
import React, { useState, useEffect } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface BacklogBadgeProps {
  className?: string;
}

export default function BacklogBadge({ className }: BacklogBadgeProps) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    const fetchCount = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/backlog/count`);
        const data = await res.json();
        if (data.success) setCount(data.count);
      } catch {
        // Silently fail — badge just shows stale count
      }
    };

    fetchCount();
    const interval = setInterval(fetchCount, 60_000); // Poll every 60s
    return () => clearInterval(interval);
  }, []);

  if (count === 0) return null;

  return (
    <span
      className={className}
      style={{
        background: '#ef4444',
        color: 'white',
        borderRadius: '9999px',
        padding: '2px 8px',
        fontSize: 11,
        fontWeight: 600,
        marginLeft: 8,
      }}
    >
      {count}
    </span>
  );
}
