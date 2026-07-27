import { useEffect, useRef, useState } from 'react';
import {
  ArrowDownCircle,
  RefreshCw,
  Search,
  Terminal,
} from 'lucide-react';
import { useSystemLogs } from '@/api/hooks';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';

export function LogsPage() {
  const [level, setLevel] = useState<string | undefined>(undefined);
  const [search, setSearch] = useState<string>('');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data, isLoading, refetch, isFetching } = useSystemLogs(300, level, search);
  const logs = data?.logs ?? [];

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  function getLevelBadgeVariant(lvl: string) {
    if (lvl === 'ERROR') return 'destructive' as const;
    if (lvl === 'WARNING') return 'warning' as const;
    if (lvl === 'INFO') return 'secondary' as const;
    return 'outline' as const;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Terminal className="h-6 w-6 text-primary" /> System &amp; Governor Logs
          </h1>
          <p className="text-sm text-muted-foreground">
            Real-time system events, poller status, auto-fan PID decisions, and Guardian actions.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="subtle" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-4 w-4 mr-1 ${isFetching ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      <Card className="border-border shadow-md">
        <CardHeader className="py-3 px-4 flex flex-row items-center justify-between border-b border-border">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <span>Live Stream</span>
            <Badge variant="outline" className="text-xs font-normal">
              {logs.length} records
            </Badge>
          </CardTitle>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant={autoScroll ? 'default' : 'subtle'}
              onClick={() => setAutoScroll(!autoScroll)}
              className="h-7 text-xs px-2"
            >
              <ArrowDownCircle className="h-3.5 w-3.5 mr-1" />
              Auto-scroll {autoScroll ? 'ON' : 'OFF'}
            </Button>
          </div>
        </CardHeader>

        <CardContent className="p-4 space-y-4">
          {/* Controls Bar */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-muted-foreground mr-1">Level:</span>
              {[
                { label: 'All', val: undefined },
                { label: 'INFO', val: 'INFO' },
                { label: 'WARNING', val: 'WARNING' },
                { label: 'ERROR', val: 'ERROR' },
              ].map((b) => (
                <Button
                  key={b.label}
                  size="sm"
                  variant={level === b.val ? 'default' : 'subtle'}
                  onClick={() => setLevel(b.val)}
                  className="h-7 text-xs px-2.5"
                >
                  {b.label}
                </Button>
              ))}
            </div>

            <div className="relative w-full sm:w-64">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                type="text"
                placeholder="Filter logs..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-8 pl-8 text-xs"
              />
            </div>
          </div>

          {/* Log Window */}
          <div
            ref={scrollRef}
            className="h-[520px] w-full rounded-md border border-border/80 bg-slate-950 p-3 font-mono text-xs overflow-y-auto space-y-1.5 selection:bg-slate-800"
          >
            {isLoading ? (
              <div className="h-full flex items-center justify-center text-slate-500">
                Loading system log stream...
              </div>
            ) : logs.length === 0 ? (
              <div className="h-full flex items-center justify-center text-slate-500">
                No matching log events recorded.
              </div>
            ) : (
              logs.map((log) => {
                const dateStr = new Date(log.ts * 1000).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                });
                return (
                  <div key={log.id} className="flex items-start gap-2 hover:bg-slate-900/60 p-0.5 rounded transition-colors leading-relaxed">
                    <span className="text-slate-500 shrink-0 select-none text-[11px]">{dateStr}</span>
                    <Badge variant={getLevelBadgeVariant(log.level)} className="text-[9px] uppercase px-1 py-0 font-bold shrink-0">
                      {log.level}
                    </Badge>
                    <span className="text-slate-400 text-[11px] font-semibold shrink-0">[{log.logger}]</span>
                    <span className="text-slate-200 break-all">{log.message}</span>
                  </div>
                );
              })
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
