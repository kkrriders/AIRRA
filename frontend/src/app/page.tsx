"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { 
  AlertTriangle, 
  CheckCircle, 
  Clock, 
  Activity, 
  ChevronRight,
  ArrowRight,
  Zap,
  ShieldCheck
} from "lucide-react";
import { Navbar } from "@/components/layout/Navbar";

export default function HomePage() {
  const { data: incidents, isLoading: isLoadingIncidents } = useQuery({
    queryKey: ["incidents"],
    queryFn: () => api.getIncidents({ page: 1, page_size: 10 }),
  });

  const { data: pendingApprovals, isLoading: isLoadingApprovals } = useQuery({
    queryKey: ["pending-approvals"],
    queryFn: () => api.getPendingApprovals(),
  });

  const stats = {
    total: incidents?.total || 0,
    detected: incidents?.items.filter((i) => i.status === "detected").length || 0,
    resolved: incidents?.items.filter((i) => i.status === "resolved").length || 0,
    pendingApproval: pendingApprovals?.length || 0,
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Navigation */}
      <Navbar />

      {/* Hero Section */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="relative mb-12">
          <div className="absolute -left-4 -top-4 w-24 h-24 bg-primary/5 rounded-full blur-3xl" />
          <h2 className="text-4xl font-extrabold tracking-tight lg:text-5xl mb-4 relative">
            Autonomous Response <br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-primary to-blue-600">
              Intelligence Agent
            </span>
          </h2>
          <p className="text-xl text-muted-foreground max-w-[700px]">
            AI-powered incident management that monitors, analyzes, and resolves infrastructure issues automatically.
          </p>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-12">
          {[
            { label: "Total Incidents", value: stats.total, icon: Activity, color: "text-blue-500", bg: "bg-blue-500/10" },
            { label: "Active Now", value: stats.detected, icon: AlertTriangle, color: "text-orange-500", bg: "bg-orange-500/10" },
            { label: "Pending Review", value: stats.pendingApproval, icon: Clock, color: "text-yellow-500", bg: "bg-yellow-500/10" },
            { label: "Successfully Resolved", value: stats.resolved, icon: CheckCircle, color: "text-green-500", bg: "bg-green-500/10" },
          ].map((stat, i) => (
            <Card key={i} className="border-border/50 bg-card/50 backdrop-blur-sm transition-all hover:border-primary/50">
              <CardContent className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <div className={`p-2 rounded-lg ${stat.bg}`}>
                    <stat.icon className={`h-5 w-5 ${stat.color}`} />
                  </div>
                  <Badge variant="outline" className="font-mono">Live</Badge>
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">{stat.label}</p>
                  <p className="text-3xl font-bold tracking-tight">{stat.value}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Main Dashboard Area */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Recent Incidents */}
          <Card className="lg:col-span-2 border-border/50 bg-card/50">
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>Critical Incidents</CardTitle>
                <CardDescription>Recently detected system anomalies</CardDescription>
              </div>
              <Link href="/incidents">
                <Button variant="outline" size="sm">View all</Button>
              </Link>
            </CardHeader>
            <CardContent>
              {isLoadingIncidents ? (
                <div className="space-y-4">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-16 w-full animate-pulse bg-muted rounded-lg" />
                  ))}
                </div>
              ) : incidents?.items.length ? (
                <div className="space-y-1">
                  {incidents.items.slice(0, 5).map((incident) => (
                    <Link
                      key={incident.id}
                      href={`/incidents/${incident.id}`}
                      className="flex items-center justify-between p-4 rounded-xl hover:bg-muted/50 transition-colors group"
                    >
                      <div className="flex items-center gap-4">
                        <div className={`w-2 h-2 rounded-full ${
                          incident.severity === 'critical' ? 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]' : 
                          incident.severity === 'high' ? 'bg-orange-500' : 'bg-yellow-500'
                        }`} />
                        <div>
                          <p className="font-semibold text-sm group-hover:text-primary transition-colors">{incident.title}</p>
                          <p className="text-xs text-muted-foreground">{incident.affected_service} • {new Date(incident.created_at).toLocaleTimeString()}</p>
                        </div>
                      </div>
                      <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:translate-x-1 transition-transform" />
                    </Link>
                  ))}
                </div>
              ) : (
                <div className="text-center py-12 border-2 border-dashed rounded-2xl bg-muted/20">
                  <Activity className="h-8 w-8 text-muted-foreground mx-auto mb-3 opacity-20" />
                  <p className="text-sm text-muted-foreground">All systems operational</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Pending Approvals */}
          <Card className="border-border/50 bg-card/50">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Approvals
                {stats.pendingApproval > 0 && (
                  <Badge variant="destructive" className="animate-pulse">{stats.pendingApproval}</Badge>
                )}
              </CardTitle>
              <CardDescription>Actions requiring authorization</CardDescription>
            </CardHeader>
            <CardContent>
              {isLoadingApprovals ? (
                <div className="space-y-4">
                  {[1, 2].map((i) => (
                    <div key={i} className="h-20 w-full animate-pulse bg-muted rounded-lg" />
                  ))}
                </div>
              ) : pendingApprovals?.length ? (
                <div className="space-y-4">
                  {pendingApprovals.slice(0, 3).map((action) => (
                    <div
                      key={action.id}
                      className="p-4 rounded-xl border border-border/50 bg-background/50 space-y-3"
                    >
                      <div className="flex justify-between items-start">
                        <div>
                          <p className="font-semibold text-sm">{action.name}</p>
                          <p className="text-xs text-muted-foreground">{action.target_service}</p>
                        </div>
                        <Badge variant={action.risk_level === 'high' || action.risk_level === 'critical' ? 'destructive' : 'secondary'} className="text-[10px]">
                          {action.risk_level}
                        </Badge>
                      </div>
                      <Link href="/approvals" className="block">
                        <Button variant="secondary" size="sm" className="w-full h-8 text-xs gap-2">
                          Review Action
                          <ArrowRight className="h-3 w-3" />
                        </Button>
                      </Link>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-12 border-2 border-dashed rounded-2xl bg-muted/20">
                  <ShieldCheck className="h-8 w-8 text-muted-foreground mx-auto mb-3 opacity-20" />
                  <p className="text-sm text-muted-foreground">No pending safety reviews</p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Feature Grid */}
        <div className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-6">
          {[
            { title: "AI Analysis", desc: "LLM-based hypothesis generation for lightning-fast RCA.", icon: Zap },
            { title: "Safe Execution", desc: "Human-in-the-loop validation for all high-risk remediation.", icon: ShieldCheck },
            { title: "Smart Observability", desc: "Native Prometheus integration with anomaly detection.", icon: Activity },
          ].map((feature, i) => (
            <div key={i} className="p-6 rounded-2xl border border-border/50 bg-card/30 hover:bg-card/50 transition-colors">
              <div className="bg-primary/10 w-10 h-10 rounded-lg flex items-center justify-center mb-4">
                <feature.icon className="h-5 w-5 text-primary" />
              </div>
              <h3 className="font-bold mb-2">{feature.title}</h3>
              <p className="text-sm text-muted-foreground leading-relaxed">{feature.desc}</p>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}