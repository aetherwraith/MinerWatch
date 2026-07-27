import { useState } from 'react';
import { ChevronDown, ChevronRight, ListFilter } from 'lucide-react';
import { useGovernorDecisions } from '@/api/hooks';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

interface Props {
  minerId: number;
  governorType: 'guardian' | 'autofan';
  title?: string;
}

export function GovernorDecisionLog({ minerId, governorType, title }: Props) {
  const [open, setOpen] = useState(true);
  const [actionFilter, setActionFilter] = useState<string>('all');
  const { data, isLoading } = useGovernorDecisions(minerId, governorType, 50);

  const decisions = data?.decisions ?? [];
  const filtered = decisions.filter((d) => {
    if (actionFilter === 'all') return true;
    return d.action_taken.toLowerCase() === actionFilter.toLowerCase();
  });

  function getBadgeVariant(action: string) {
    const act = action.toUpperCase();
    if (act === 'STEP_DOWN') return 'destructive' as const;
    if (act === 'STEP_UP') return 'success' as const;
    if (act === 'FAN_ADJUST') return 'secondary' as const;
    return 'outline' as const;
  }

  return (
    <div className="border border-border rounded-lg bg-card/40 overflow-hidden text-sm">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-3 bg-muted/30 hover:bg-muted/50 transition-colors text-left font-medium"
      >
        <div className="flex items-center gap-2">
          {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
          <span>{title || `${governorType === 'guardian' ? 'Guardian' : 'Auto-Fan'} Decision Log`}</span>
          <Badge variant="outline" className="text-xs">
            {decisions.length} entries
          </Badge>
        </div>
        <span className="text-xs text-muted-foreground">
          {open ? 'Click to collapse' : 'Click to expand'}
        </span>
      </button>

      {open && (
        <div className="p-3 space-y-3">
          {/* Action Filter */}
          <div className="flex items-center gap-2 text-xs">
            <ListFilter className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-muted-foreground">Filter:</span>
            <div className="flex gap-1">
              {['all', governorType === 'guardian' ? 'STEP_DOWN' : 'FAN_ADJUST', governorType === 'guardian' ? 'STEP_UP' : 'HOLD'].map((f) => (
                <Button
                  key={f}
                  size="sm"
                  variant={actionFilter === f ? 'default' : 'subtle'}
                  onClick={() => setActionFilter(f)}
                  className="h-6 text-xs px-2"
                >
                  {f}
                </Button>
              ))}
            </div>
          </div>

          {/* Decision list */}
          {isLoading ? (
            <p className="text-xs text-muted-foreground py-2">Loading decision log...</p>
          ) : filtered.length === 0 ? (
            <p className="text-xs text-muted-foreground py-2">No decision logs recorded yet.</p>
          ) : (
            <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
              {filtered.map((d) => {
                const dateStr = new Date(d.ts * 1000).toLocaleTimeString();
                return (
                  <div key={d.id} className="p-2 rounded border border-border/60 bg-background/60 text-xs space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Badge variant={getBadgeVariant(d.action_taken)} className="text-[10px] uppercase font-bold px-1.5 py-0">
                          {d.action_taken}
                        </Badge>
                        <span className="text-muted-foreground font-mono text-[11px]">{dateStr}</span>
                      </div>
                      <div className="text-[11px] text-muted-foreground tabular-nums">
                        {d.chip_temp != null && <span>ASIC: {d.chip_temp.toFixed(1)}°C </span>}
                        {d.vr_temp != null && <span>| VR: {d.vr_temp.toFixed(1)}°C</span>}
                      </div>
                    </div>
                    <p className="text-foreground/90 font-medium">{d.reason}</p>
                    {d.details && (
                      <div className="text-[11px] text-muted-foreground font-mono bg-muted/20 p-1 rounded">
                        {Object.entries(d.details).map(([k, v]) => `${k}: ${v}`).join(' | ')}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
