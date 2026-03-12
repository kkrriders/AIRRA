"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  BrainCircuit,
  TrendingUp,
  Target,
  Zap,
  CheckCircle2,
  XCircle,
  Minus,
} from "lucide-react";

function ConfidenceBadge({ adjustment }: { adjustment: number }) {
  if (adjustment > 0) {
    return (
      <Badge className="bg-green-100 text-green-700 border-green-200 gap-1 font-mono">
        <TrendingUp className="h-3 w-3" />
        {`+${adjustment.toFixed(2)}`}
      </Badge>
    );
  }
  if (adjustment < 0) {
    return (
      <Badge className="bg-red-100 text-red-700 border-red-200 gap-1 font-mono">
        <XCircle className="h-3 w-3" />
        {adjustment.toFixed(2)}
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="gap-1 font-mono">
      <Minus className="h-3 w-3" />
      0.00
    </Badge>
  );
}

function SuccessRateBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const color = pct >= 70 ? "bg-green-500" : pct >= 40 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 bg-muted h-1.5 rounded-full overflow-hidden">
        <div className={cn("h-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-muted-foreground">{pct}%</span>
    </div>
  );
}

export default function LearningPage() {
  const { data: patternsData, isLoading: patternsLoading } = useQuery({
    queryKey: ["learning-patterns"],
    queryFn: () => api.getPatterns(),
    refetchInterval: 30000,
  });

  const { data: insights, isLoading: insightsLoading } = useQuery({
    queryKey: ["learning-insights"],
    queryFn: () => api.getInsights(),
    refetchInterval: 30000,
  });

  const patterns = patternsData?.patterns ?? [];

  return (
    <div className="min-h-screen bg-background text-foreground">
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <BrainCircuit className="h-7 w-7 text-primary" />
            <h1 className="text-3xl font-extrabold tracking-tight">AI Learning</h1>
          </div>
          <p className="text-muted-foreground text-sm">
            AIRRA improves hypothesis confidence over time by learning from operator feedback and incident outcomes.
          </p>
        </div>

        {/* Stats Row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <Card className="border-border/50 bg-card/50">
            <CardContent className="pt-6">
              <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">
                Patterns Learned
              </p>
              <p className="text-3xl font-extrabold">
                {insightsLoading ? "—" : (insights?.patterns_learned ?? 0)}
              </p>
            </CardContent>
          </Card>

          <Card className="border-border/50 bg-card/50">
            <CardContent className="pt-6">
              <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">
                Hypothesis Accuracy
              </p>
              <p className="text-3xl font-extrabold">
                {insightsLoading
                  ? "—"
                  : `${Math.round((insights?.hypothesis_accuracy ?? 0) * 100)}%`}
              </p>
            </CardContent>
          </Card>

          <Card className="border-border/50 bg-card/50">
            <CardContent className="pt-6">
              <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">
                Resolution Rate
              </p>
              <p className="text-3xl font-extrabold">
                {insightsLoading
                  ? "—"
                  : `${Math.round((insights?.resolution_rate ?? 0) * 100)}%`}
              </p>
            </CardContent>
          </Card>

          <Card className="border-border/50 bg-card/50">
            <CardContent className="pt-6">
              <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">
                Avg Resolution
              </p>
              <p className="text-3xl font-extrabold">
                {insightsLoading
                  ? "—"
                  : `${insights?.avg_resolution_time_minutes ?? 0}m`}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* How Learning Works */}
        <Card className="border-border/50 bg-card/50 mb-8">
          <CardHeader>
            <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <Zap className="h-4 w-4 text-primary" />
              How AIRRA Learns
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm">
              <div className="flex gap-3">
                <div className="bg-primary/10 text-primary w-7 h-7 rounded-full flex items-center justify-center font-bold text-xs shrink-0">1</div>
                <div>
                  <p className="font-semibold mb-1">Incident Resolved</p>
                  <p className="text-muted-foreground text-xs">Operator submits a Post-Incident Review confirming whether the AI hypothesis was correct.</p>
                </div>
              </div>
              <div className="flex gap-3">
                <div className="bg-primary/10 text-primary w-7 h-7 rounded-full flex items-center justify-center font-bold text-xs shrink-0">2</div>
                <div>
                  <p className="font-semibold mb-1">Pattern Updated</p>
                  <p className="text-muted-foreground text-xs">The learning engine updates the success rate for this service + category combination in PostgreSQL.</p>
                </div>
              </div>
              <div className="flex gap-3">
                <div className="bg-primary/10 text-primary w-7 h-7 rounded-full flex items-center justify-center font-bold text-xs shrink-0">3</div>
                <div>
                  <p className="font-semibold mb-1">Confidence Adjusted</p>
                  <p className="text-muted-foreground text-xs">Next time the same pattern appears, the hypothesis confidence score is boosted or reduced by the learned adjustment.</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Patterns Table */}
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Target className="h-5 w-5 text-primary" />
            <h2 className="text-xl font-bold tracking-tight">Learned Patterns</h2>
          </div>
          <Badge variant="outline" className="font-mono text-xs">
            {patterns.length} pattern{patterns.length !== 1 ? "s" : ""}
          </Badge>
        </div>

        {patternsLoading ? (
          <Card className="border-border/50 bg-card/50">
            <CardContent className="py-12 text-center">
              <div className="inline-block animate-spin rounded-full h-6 w-6 border-b-2 border-primary mb-3" />
              <p className="text-sm text-muted-foreground">Loading patterns...</p>
            </CardContent>
          </Card>
        ) : patterns.length === 0 ? (
          <Card className="border-border/50 bg-card/50">
            <CardContent className="py-16 text-center">
              <BrainCircuit className="h-10 w-10 text-muted-foreground mx-auto mb-4 opacity-20" />
              <p className="text-sm font-medium mb-1">No patterns learned yet</p>
              <p className="text-xs text-muted-foreground max-w-sm mx-auto">
                Patterns are discovered after incidents are resolved and operators submit post-incident reviews confirming or correcting the AI hypothesis.
              </p>
            </CardContent>
          </Card>
        ) : (
          <Card className="border-border/50 bg-card/50">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50">
                      <th className="text-left px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Pattern</th>
                      <th className="text-left px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Category</th>
                      <th className="text-left px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Occurrences</th>
                      <th className="text-left px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Success Rate</th>
                      <th className="text-left px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Confidence Δ</th>
                      <th className="text-left px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {patterns.map((pattern: any) => {
                      return (
                        <tr key={pattern.pattern_id} className="border-b border-border/30 hover:bg-muted/20 transition-colors">
                          <td className="px-6 py-4">
                            <div>
                              <p className="font-semibold font-mono text-xs">{pattern.pattern_id}</p>
                              <p className="text-xs text-muted-foreground mt-0.5">{pattern.name}</p>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <Badge variant="outline" className="text-[10px] font-mono">
                              {pattern.category}
                            </Badge>
                          </td>
                          <td className="px-6 py-4">
                            <span className="font-mono font-bold">{pattern.occurrence_count}</span>
                            <span className="text-muted-foreground text-xs ml-1">incidents</span>
                          </td>
                          <td className="px-6 py-4">
                            <SuccessRateBar rate={pattern.success_rate} />
                          </td>
                          <td className="px-6 py-4">
                            <ConfidenceBadge adjustment={pattern.confidence_adjustment} />
                          </td>
                          <td className="px-6 py-4">
                            {pattern.success_rate >= 0.7 ? (
                              <div className="flex items-center gap-1.5 text-green-600 text-xs">
                                <CheckCircle2 className="h-3.5 w-3.5" />
                                Reliable
                              </div>
                            ) : pattern.success_rate < 0.3 ? (
                              <div className="flex items-center gap-1.5 text-red-600 text-xs">
                                <XCircle className="h-3.5 w-3.5" />
                                Unreliable
                              </div>
                            ) : (
                              <div className="flex items-center gap-1.5 text-yellow-600 text-xs">
                                <Minus className="h-3.5 w-3.5" />
                                Learning
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  );
}
