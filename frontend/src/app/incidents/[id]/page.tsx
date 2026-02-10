"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  getSeverityColor,
  getStatusColor,
  formatDate,
  formatConfidence,
  formatStatusText,
  getRiskColor,
  getActionStatusColor,
  cn
} from "@/lib/utils";
import { 
  ArrowLeft, 
  Sparkles, 
  AlertTriangle, 
  Activity, 
  Clock, 
  ShieldCheck, 
  Zap, 
  Database, 
  Server,
  ChevronRight,
  Fingerprint
} from "lucide-react";
import { toast } from "sonner";
import { Navbar } from "@/components/layout/Navbar";

export default function IncidentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const queryClient = useQueryClient();

  const { data: incident, isLoading } = useQuery({
    queryKey: ["incident", id],
    queryFn: () => api.getIncident(id),
  });

  const analyzeMutation = useMutation({
    mutationFn: () => api.analyzeIncident(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["incident", id] });
      toast.success("Analysis completed successfully");
    },
    onError: (error: any) => {
      toast.error(error.message || "Analysis failed");
    },
  });

  if (isLoading) {
    return (
      <div className="min-h-screen bg-background flex flex-col">
        <Navbar />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            <p className="mt-2 text-muted-foreground">Hydrating incident context...</p>
          </div>
        </div>
      </div>
    );
  }

  if (!incident) {
    return (
      <div className="min-h-screen bg-background flex flex-col">
        <Navbar />
        <div className="flex-1 flex items-center justify-center">
          <Card className="max-w-md border-border/50 bg-card/50">
            <CardContent className="py-12 text-center">
              <div className="bg-destructive/10 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
                <AlertTriangle className="h-8 w-8 text-destructive" />
              </div>
              <h3 className="text-xl font-bold mb-2">Incident Not Found</h3>
              <p className="text-muted-foreground mb-6">This incident record may have been archived or deleted.</p>
              <Link href="/incidents">
                <Button variant="outline" className="w-full">
                  Return to Fleet
                </Button>
              </Link>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Navigation Breadcrumb */}
        <div className="mb-6">
          <Link href="/incidents" className="flex items-center gap-2 text-sm text-muted-foreground hover:text-primary transition-colors group">
            <ArrowLeft className="h-4 w-4 group-hover:-translate-x-1 transition-transform" />
            Back to Incidents
          </Link>
        </div>

        {/* Page Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-extrabold tracking-tight">{incident.title}</h1>
              <Badge variant="outline" className={cn("font-mono px-2", getSeverityColor(incident.severity))}>
                {incident.severity}
              </Badge>
            </div>
            <div className="flex items-center gap-4 text-sm text-muted-foreground">
              <span className="flex items-center gap-1.5 font-mono">
                <Fingerprint className="h-3.5 w-3.5" />
                {incident.id.split('-')[0]}
              </span>
              <span className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5" />
                Detected {formatDate(incident.detected_at)}
              </span>
            </div>
          </div>
          
          <div className="flex items-center gap-3">
            {incident.status === "detected" && (
              <Button
                onClick={() => analyzeMutation.mutate()}
                disabled={analyzeMutation.isPending}
                className="gap-2 bg-primary shadow-lg shadow-primary/20"
              >
                <Sparkles className={cn("h-4 w-4", analyzeMutation.isPending && "animate-pulse")} />
                {analyzeMutation.isPending ? "LLM Analysis in Progress..." : "Run AI Analysis"}
              </Button>
            )}
            <Badge className={cn("h-10 px-4 text-sm font-bold border-0", getStatusColor(incident.status))}>
              {formatStatusText(incident.status)}
            </Badge>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8">
          {/* Main Info */}
          <div className="lg:col-span-2 space-y-8">
            <Card className="border-border/50 bg-card/50">
              <CardHeader>
                <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground">Situation Report</CardTitle>
              </CardHeader>
              <CardContent className="space-y-6">
                <div>
                  <p className="text-sm leading-relaxed text-foreground/80">{incident.description}</p>
                </div>
                
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-6 pt-6 border-t border-border/50">
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-2 flex items-center gap-1.5">
                      <Server className="h-3 w-3" /> Affected Service
                    </p>
                    <p className="text-sm font-semibold">{incident.affected_service}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-2 flex items-center gap-1.5">
                      <Database className="h-3 w-3" /> Detection Source
                    </p>
                    <p className="text-sm font-semibold">{incident.detection_source}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-2 flex items-center gap-1.5">
                      <Activity className="h-3 w-3" /> Components
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {incident.affected_components.map((comp) => (
                        <Badge key={comp} variant="secondary" className="text-[10px] px-1.5 py-0">
                          {comp}
                        </Badge>
                      ))}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Hypotheses Section */}
            <div>
              <div className="flex items-center gap-2 mb-4">
                <Zap className="h-5 w-5 text-primary fill-primary/20" />
                <h2 className="text-xl font-bold tracking-tight">AI Hypotheses</h2>
              </div>
              
              {incident.hypotheses && incident.hypotheses.length > 0 ? (
                <div className="grid gap-4">
                  {incident.hypotheses.map((hypothesis) => (
                    <Card key={hypothesis.id} className="border-border/50 bg-card/30 hover:bg-card/50 transition-colors">
                      <CardContent className="p-6">
                        <div className="flex justify-between items-start gap-4 mb-4">
                          <div className="flex items-center gap-3">
                            <div className="bg-primary/10 text-primary w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm">
                              {hypothesis.rank}
                            </div>
                            <Badge variant="outline" className="bg-background/50 border-primary/20 text-primary font-mono text-[10px]">
                              {hypothesis.category}
                            </Badge>
                          </div>
                          <div className="text-right">
                            <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Confidence</p>
                            <div className="flex items-center gap-2">
                              <div className="w-24 bg-muted h-1.5 rounded-full overflow-hidden hidden sm:block">
                                <div className="bg-primary h-full transition-all duration-500" style={{ width: `${hypothesis.confidence_score * 100}%` }} />
                              </div>
                              <span className="text-lg font-mono font-bold text-primary">
                                {formatConfidence(hypothesis.confidence_score)}
                              </span>
                            </div>
                          </div>
                        </div>
                        <p className="text-sm text-foreground/90 leading-relaxed mb-4">{hypothesis.description}</p>
                        {hypothesis.supporting_signals.length > 0 && (
                          <div className="flex flex-wrap gap-1.5">
                            {hypothesis.supporting_signals.map((signal, i) => (
                              <Badge key={i} variant="secondary" className="bg-background/50 text-[10px] border-border/50">
                                {signal}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>
              ) : (
                <div className="text-center py-12 border-2 border-dashed rounded-3xl bg-muted/20">
                  <Sparkles className="h-8 w-8 text-muted-foreground mx-auto mb-3 opacity-20" />
                  <p className="text-sm text-muted-foreground">Run AI analysis to generate hypotheses</p>
                </div>
              )}
            </div>
          </div>

          {/* Right Column: Actions & Timeline */}
          <div className="space-y-8">
            <div>
              <div className="flex items-center gap-2 mb-4">
                <ShieldCheck className="h-5 w-5 text-green-500 fill-green-500/10" />
                <h2 className="text-xl font-bold tracking-tight">Remediation</h2>
              </div>
              
              {incident.actions && incident.actions.length > 0 ? (
                <div className="space-y-4">
                  {incident.actions.map((action) => (
                    <Card key={action.id} className="border-border/50 bg-card/50 overflow-hidden">
                      <CardContent className="p-5">
                        <div className="flex justify-between items-start mb-3">
                          <h4 className="font-bold text-sm leading-tight">{action.name}</h4>
                          <Badge className={cn("text-[9px] px-1.5 h-5", getActionStatusColor(action.status))}>
                            {formatStatusText(action.status)}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground mb-4 line-clamp-2">{action.description}</p>
                        
                        <div className="flex items-center justify-between pt-4 border-t border-border/50">
                          <div className="flex items-center gap-2">
                            <Badge variant="outline" className={cn("text-[9px] border-border/50", getRiskColor(action.risk_level))}>
                              Risk: {action.risk_level}
                            </Badge>
                          </div>
                          
                          {action.status === "pending_approval" ? (
                            <Link href="/approvals">
                              <Button size="sm" variant="secondary" className="h-7 text-[10px] gap-1 px-2">
                                <AlertTriangle className="h-3 w-3" />
                                Review Approval
                              </Button>
                            </Link>
                          ) : (
                            <span className="text-[10px] text-muted-foreground font-mono">
                              {action.target_service}
                            </span>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              ) : (
                <div className="text-center py-12 border-2 border-dashed rounded-3xl bg-muted/20">
                  <Activity className="h-8 w-8 text-muted-foreground mx-auto mb-3 opacity-20" />
                  <p className="text-sm text-muted-foreground">No actions proposed yet</p>
                </div>
              )}
            </div>

            {/* Metrics Snapshot Preview */}
            <Card className="border-border/50 bg-card/50">
              <CardHeader className="pb-4">
                <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center justify-between">
                  Metrics Snapshot
                  <Badge variant="outline" className="text-[9px] font-mono">Snapshot</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="bg-background/80 rounded-lg p-3 border border-border/50 overflow-x-auto">
                  <pre className="text-[10px] font-mono text-muted-foreground">
                    {JSON.stringify(incident.metrics_snapshot, null, 2)}
                  </pre>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  );
}