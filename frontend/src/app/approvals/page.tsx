"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  getRiskColor,
  formatStatusText,
  formatDate,
  cn
} from "@/lib/utils";
import { ShieldCheck, CheckCircle, XCircle, RefreshCw, Mail, Activity, AlertTriangle, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { Navbar } from "@/components/layout/Navbar";

export default function ApprovalsPage() {
  const queryClient = useQueryClient();
  const [approverEmail, setApproverEmail] = useState("operator@example.com");

  const { data: pendingActions, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["pending-approvals"],
    queryFn: () => api.getPendingApprovals(),
  });

  const approveMutation = useMutation({
    mutationFn: ({ id, email }: { id: string; email: string }) =>
      api.approveAction(id, { approved_by: email, execution_mode: "dry_run" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pending-approvals"] });
      toast.success("Action approved successfully");
    },
    onError: (error: any) => {
      toast.error(error.message || "Approval failed");
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, email, reason }: { id: string; email: string; reason: string }) =>
      api.rejectAction(id, { rejected_by: email, rejection_reason: reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pending-approvals"] });
      toast.success("Action rejected");
    },
    onError: (error: any) => {
      toast.error(error.message || "Rejection failed");
    },
  });

  const handleApprove = (actionId: string) => {
    if (!approverEmail) {
      toast.error("Please enter your email");
      return;
    }
    approveMutation.mutate({ id: actionId, email: approverEmail });
  };

  const handleReject = (actionId: string) => {
    if (!approverEmail) {
      toast.error("Please enter your email");
      return;
    }
    const reason = prompt("Reason for rejection:");
    if (reason) {
      rejectMutation.mutate({ id: actionId, email: approverEmail, reason });
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight">Safety Approvals</h1>
            <p className="text-muted-foreground mt-1">
              Review and authorize autonomous remediation actions.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="h-9 gap-2"
          >
            <RefreshCw className={cn("h-4 w-4", isFetching && "animate-spin")} />
            Refresh
          </Button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
          {/* Sidebar Info */}
          <div className="lg:col-span-1 space-y-6">
            <Card className="border-border/50 bg-card/50">
              <CardHeader className="pb-4">
                <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground">Operator Context</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <label className="text-xs font-semibold flex items-center gap-2">
                    <Mail className="h-3 w-3" />
                    Authorized Email
                  </label>
                  <input
                    type="email"
                    placeholder="operator@example.com"
                    value={approverEmail}
                    onChange={(e) => setApproverEmail(e.target.value)}
                    className="w-full bg-background border border-border/50 rounded-lg py-2 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                </div>
                <div className="p-3 rounded-lg bg-primary/5 border border-primary/10">
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    Actions approved here will be executed in <span className="text-primary font-bold">dry-run</span> mode by default for maximum safety.
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border/50 bg-card/50">
              <CardHeader className="pb-4">
                <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground">Queue Status</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Pending Review</span>
                    <Badge variant="secondary">{pendingActions?.length || 0}</Badge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">High Risk</span>
                    <Badge variant="destructive">{pendingActions?.filter(a => a.risk_level === 'high' || a.risk_level === 'critical').length || 0}</Badge>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Main Queue */}
          <div className="lg:col-span-3">
            {isLoading ? (
              <div className="space-y-4">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-48 w-full animate-pulse bg-muted rounded-2xl" />
                ))}
              </div>
            ) : !pendingActions?.length ? (
              <div className="text-center py-24 border-2 border-dashed rounded-3xl bg-muted/20">
                <div className="bg-green-500/10 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
                  <ShieldCheck className="h-8 w-8 text-green-500" />
                </div>
                <h3 className="text-xl font-bold mb-2">Queue is Clear</h3>
                <p className="text-muted-foreground max-w-xs mx-auto">
                  No actions currently requiring manual authorization.
                </p>
              </div>
            ) : (
              <div className="space-y-6">
                {pendingActions.map((action) => (
                  <Card key={action.id} className="group border-border/50 bg-card/50 hover:border-primary/30 transition-all overflow-hidden">
                    <CardHeader className="border-b border-border/50 pb-4">
                      <div className="flex justify-between items-start">
                        <div className="space-y-1">
                          <CardTitle className="text-xl flex items-center gap-2">
                            {action.name}
                            <Badge variant="outline" className={cn("font-mono text-[10px]", getRiskColor(action.risk_level))}>
                              Risk: {action.risk_level}
                            </Badge>
                          </CardTitle>
                          <CardDescription>{action.description}</CardDescription>
                        </div>
                        <div className="text-right">
                          <p className="text-xs font-mono text-muted-foreground">ID: {action.id.split('-')[0]}</p>
                          <p className="text-xs text-muted-foreground mt-1">{formatDate(action.created_at)}</p>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="pt-6">
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-8">
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Target</p>
                          <div className="flex items-center gap-2">
                            <Activity className="h-4 w-4 text-primary" />
                            <span className="text-sm font-semibold">{action.target_service}</span>
                          </div>
                        </div>
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Type</p>
                          <div className="flex items-center gap-2">
                            <ShieldAlert className="h-4 w-4 text-orange-500" />
                            <span className="text-sm font-semibold">{formatStatusText(action.action_type)}</span>
                          </div>
                        </div>
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Risk Score</p>
                          <div className="flex items-center gap-2">
                            <div className="w-full bg-muted h-1.5 rounded-full overflow-hidden max-w-[60px]">
                              <div className="bg-primary h-full" style={{ width: `${action.risk_score * 100}%` }} />
                            </div>
                            <span className="text-sm font-mono font-bold">{(action.risk_score * 100).toFixed(0)}%</span>
                          </div>
                        </div>
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Blast Radius</p>
                          <Badge variant="secondary" className="capitalize text-[10px] px-2 py-0 h-5">
                            {action.blast_radius}
                          </Badge>
                        </div>
                      </div>

                      {/* Parameters */}
                      {Object.keys(action.parameters).length > 0 && (
                        <div className="mb-8">
                          <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-2">Parameters</p>
                          <div className="bg-background/80 p-4 rounded-xl border border-border/50 font-mono text-xs">
                            <pre className="text-muted-foreground">
                              {JSON.stringify(action.parameters, null, 2)}
                            </pre>
                          </div>
                        </div>
                      )}

                      {/* Footer Actions */}
                      <div className="flex flex-col sm:flex-row gap-3 pt-6 border-t border-border/50">
                        <Button
                          onClick={() => handleApprove(action.id)}
                          disabled={approveMutation.isPending || !approverEmail}
                          className="flex-1 h-11 gap-2 bg-green-600 hover:bg-green-700 text-white border-0 shadow-lg shadow-green-500/20"
                        >
                          <CheckCircle className="h-4 w-4" />
                          Approve Execution
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => handleReject(action.id)}
                          disabled={rejectMutation.isPending || !approverEmail}
                          className="flex-1 h-11 gap-2 border-red-500/20 hover:bg-red-500/10 hover:text-red-500"
                        >
                          <XCircle className="h-4 w-4" />
                          Reject Action
                        </Button>
                        <Link href={`/incidents/${action.incident_id}`}>
                          <Button variant="ghost" className="h-11 px-6">
                            View Incident
                          </Button>
                        </Link>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}