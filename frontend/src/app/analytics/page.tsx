"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  Cell,
  PieChart,
  Pie
} from "recharts";
import { 
  Brain, 
  Target, 
  Clock, 
  TrendingUp, 
  Zap, 
  ShieldCheck,
  RefreshCw,
  Lightbulb
} from "lucide-react";
import { Navbar } from "@/components/layout/Navbar";
import { cn } from "@/lib/utils";

export default function AnalyticsPage() {
  const { data: insights, isLoading: isLoadingInsights, refetch: refetchInsights } = useQuery({
    queryKey: ["insights"],
    queryFn: () => api.getInsights(30),
  });

  const { data: patternsData, isLoading: isLoadingPatterns } = useQuery({
    queryKey: ["patterns"],
    queryFn: () => api.getPatterns(),
  });

  const stats = [
    {
      label: "Hypothesis Accuracy",
      value: insights ? `${(insights.hypothesis_accuracy * 100).toFixed(1)}%` : "0%",
      desc: "AI Correctness Rate",
      icon: Target,
      color: "text-green-500",
      bg: "bg-green-500/10"
    },
    {
      label: "Avg Resolution Time",
      value: insights ? `${insights.avg_resolution_time_minutes}m` : "0m",
      desc: "Mean Time to Resolve",
      icon: Clock,
      color: "text-blue-500",
      bg: "bg-blue-500/10"
    },
    {
      label: "Learned Patterns",
      value: insights?.patterns_learned || 0,
      desc: "Knowledge Base Size",
      icon: Brain,
      color: "text-purple-500",
      bg: "bg-purple-500/10"
    },
    {
      label: "Auto-Resolution",
      value: insights ? `${(insights.resolution_rate * 100).toFixed(1)}%` : "0%",
      desc: "Incidents Resolved",
      icon: Zap,
      color: "text-orange-500",
      bg: "bg-orange-500/10"
    }
  ];

  // Prepare data for charts
  const patternsChartData = patternsData?.patterns.map(p => ({
    name: p.category,
    value: p.occurrence_count,
    success: p.success_rate * 100
  })).sort((a, b) => b.value - a.value).slice(0, 5) || [];

  const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight">System Intelligence</h1>
            <p className="text-muted-foreground mt-1">
              Performance metrics of the autonomous reasoning engine.
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => refetchInsights()} className="gap-2">
            <RefreshCw className="h-4 w-4" />
            Refresh Data
          </Button>
        </div>

        {/* KPIs */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {stats.map((stat, i) => (
            <Card key={i} className="border-border/50 bg-card/50 backdrop-blur-sm">
              <CardContent className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <div className={`p-2 rounded-lg ${stat.bg}`}>
                    <stat.icon className={`h-5 w-5 ${stat.color}`} />
                  </div>
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-medium text-muted-foreground">{stat.label}</p>
                  <p className="text-3xl font-bold tracking-tight">{isLoadingInsights ? "..." : stat.value}</p>
                  <p className="text-xs text-muted-foreground">{stat.desc}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8">
          {/* Main Chart */}
          <Card className="lg:col-span-2 border-border/50 bg-card/50">
            <CardHeader>
              <CardTitle>Frequent Incident Patterns</CardTitle>
              <CardDescription>Top occurring incident categories and their success rates</CardDescription>
            </CardHeader>
            <CardContent className="h-[300px]">
              {isLoadingPatterns ? (
                <div className="h-full flex items-center justify-center">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
                </div>
              ) : patternsData?.patterns.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={patternsChartData} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="#333" opacity={0.2} />
                    <XAxis type="number" hide />
                    <YAxis dataKey="name" type="category" width={100} tick={{ fill: '#888', fontSize: 12 }} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#1f2937', border: 'none', borderRadius: '8px', color: '#fff' }}
                      cursor={{ fill: 'transparent' }}
                    />
                    <Bar dataKey="value" name="Occurrences" fill="#3b82f6" radius={[0, 4, 4, 0]} barSize={20} />
                    <Bar dataKey="success" name="Success Rate %" fill="#10b981" radius={[0, 4, 4, 0]} barSize={20} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
                  <Lightbulb className="h-8 w-8 mb-2 opacity-20" />
                  <p>No patterns learned yet</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Secondary Info */}
          <Card className="border-border/50 bg-card/50">
            <CardHeader>
              <CardTitle>Learning Status</CardTitle>
              <CardDescription>Engine adaptation metrics</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-6">
                <div>
                  <div className="flex justify-between text-sm mb-2">
                    <span className="text-muted-foreground">Hypothesis Confidence</span>
                    <span className="font-bold">{insights ? (insights.hypothesis_accuracy * 100).toFixed(0) : 0}%</span>
                  </div>
                  <div className="h-2 bg-muted rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-green-500 transition-all duration-1000" 
                      style={{ width: `${insights ? insights.hypothesis_accuracy * 100 : 0}%` }} 
                    />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-sm mb-2">
                    <span className="text-muted-foreground">Action Success Rate</span>
                    <span className="font-bold">
                      {insights && insights.successful_actions > 0 
                        ? ((insights.successful_actions / (insights.total_incidents || 1)) * 100).toFixed(0) 
                        : 0}%
                    </span>
                  </div>
                  <div className="h-2 bg-muted rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-blue-500 transition-all duration-1000" 
                      style={{ width: `${insights && insights.total_incidents ? (insights.successful_actions / insights.total_incidents) * 100 : 0}%` }} 
                    />
                  </div>
                </div>

                <div className="pt-6 border-t border-border/50">
                  <h4 className="text-sm font-semibold mb-3 flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-primary" />
                    Active Safeguards
                  </h4>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-xs p-2 rounded bg-background/50 border border-border/50">
                      <span>Dry Run Mode</span>
                      <Badge variant="outline" className="text-xs">Enabled</Badge>
                    </div>
                    <div className="flex items-center justify-between text-xs p-2 rounded bg-background/50 border border-border/50">
                      <span>Human-in-the-loop</span>
                      <Badge variant="outline" className="text-xs">Required</Badge>
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Detailed Patterns List */}
        <Card className="border-border/50 bg-card/50">
          <CardHeader>
            <CardTitle>Learned Knowledge Base</CardTitle>
            <CardDescription>Automatically generated signatures from historical incidents</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoadingPatterns ? (
              <div className="space-y-4">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-12 w-full animate-pulse bg-muted rounded-lg" />
                ))}
              </div>
            ) : patternsData?.patterns.length ? (
              <div className="space-y-2">
                {patternsData.patterns.map((pattern) => (
                  <div 
                    key={pattern.pattern_id} 
                    className="flex items-center justify-between p-4 rounded-lg bg-background/50 border border-border/50 hover:border-primary/50 transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <div className="bg-primary/10 p-2 rounded-md">
                        <TrendingUp className="h-4 w-4 text-primary" />
                      </div>
                      <div>
                        <p className="font-semibold text-sm">{pattern.name}</p>
                        <p className="text-xs text-muted-foreground">Category: {pattern.category}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-6">
                      <div className="text-right">
                        <p className="text-xs text-muted-foreground uppercase tracking-wider">Occurrences</p>
                        <p className="font-mono font-bold">{pattern.occurrence_count}</p>
                      </div>
                      <div className="text-right w-24">
                        <p className="text-xs text-muted-foreground uppercase tracking-wider">Success Rate</p>
                        <div className="flex items-center gap-2 justify-end">
                          <div className={`w-2 h-2 rounded-full ${
                            pattern.success_rate >= 0.8 ? 'bg-green-500' : 
                            pattern.success_rate >= 0.5 ? 'bg-yellow-500' : 'bg-red-500'
                          }`} />
                          <p className="font-mono font-bold">{(pattern.success_rate * 100).toFixed(0)}%</p>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-12">
                <p className="text-muted-foreground">No patterns recorded yet.</p>
              </div>
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
